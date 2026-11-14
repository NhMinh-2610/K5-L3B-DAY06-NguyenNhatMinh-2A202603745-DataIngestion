"""Chạy truy xuất trước, sau đó đối chiếu gold và ghi kết quả benchmark."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time

from dotenv import load_dotenv

from .embeddings import MyEmbedder
from .evaluation import evaluate_query, summarize
from .store import PgVectorStore

ROOT = Path(__file__).resolve().parents[2]


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(split):
    config = _json(ROOT / "starter/strategies.json")
    model_config = _json(ROOT / "starter/embedding.json")
    definition = _json(ROOT / "benchmark/split.json")
    selection_path = ROOT / "results/selection.json"
    fingerprints = {
        "questions_sha256": _sha(ROOT / "benchmark/questions.jsonl"),
        "corpus_sha256": _sha(ROOT / config["corpus_path"]),
        "strategies_sha256": _sha(ROOT / "starter/strategies.json"),
        "embedding_sha256": _sha(ROOT / "starter/embedding.json"),
    }
    if any(fingerprints[key] != definition[key] for key in ["questions_sha256", "corpus_sha256"]):
        raise ValueError("Câu hỏi hoặc corpus khác bản đã chốt")
    previous_selection = _json(selection_path) if selection_path.exists() else {}
    if split == "test":
        if previous_selection.get("status") != "fixed" or previous_selection.get("selected_strategy") not in config["strategies"]:
            raise ValueError("Cần chốt cấu hình trên dev trước khi chạy test")
        if previous_selection["fingerprints"] != fingerprints:
            raise ValueError("Cấu hình đã thay đổi sau khi chốt; không chạy test")
    elif previous_selection.get("status") == "fixed" and previous_selection["fingerprints"] != fingerprints:
        raise ValueError("Cấu hình đã chốt khác dữ liệu hiện tại; cần ghi nhận thí nghiệm mới")
    queries = _jsonl(ROOT / f"benchmark/{split}_queries.jsonl")
    ids = [query["id"] for query in queries]
    if len(ids) != len(set(ids)) or set(ids) != set(definition[split + "_ids"]):
        raise ValueError("Danh sách đầu vào không khớp split")
    if any(set(query) != {"id", "split", "question", "filter"} or query["split"] != split for query in queries):
        raise ValueError("Đầu vào tìm kiếm chỉ được chứa ID, split, câu hỏi và filter")
    load_dotenv(ROOT / "starter/.env", override=True)
    model_started = time.perf_counter()
    embedder = MyEmbedder(**{key: model_config[key] for key in
                            ["model_name", "revision", "device", "batch_size", "document_prefix", "query_prefix", "dimensions"]})
    model_load_seconds = time.perf_counter() - model_started
    ingest = _json(ROOT / "results/ingestion.json")
    if embedder.signature != ingest["model_signature"]:
        raise ValueError("Model/cách xử lý query khác lần tạo vector")
    if split == "test" and previous_selection["model_signature"] != embedder.signature:
        raise ValueError("Model hoặc thư viện khác lần chọn cấu hình trên dev")
    store = PgVectorStore(os.environ.get("DATABASE_URL"), embedder.dimensions, embedder.signature)
    for row in ingest["strategies"]:
        if store.count(row["strategy"]) != row["chunk_count"]:
            raise ValueError("Số chunk trong database khác lần nạp đã kiểm tra")
    trace_path = ROOT / f"results/{split}_trace.jsonl"
    raw = []
    with trace_path.open("w", encoding="utf-8") as stream:
        for query in queries:
            query_started = time.perf_counter()
            query_vector = embedder.embed_query(query["question"])
            query_seconds = time.perf_counter() - query_started
            for name, settings in config["strategies"].items():
                applied_filter = query["filter"] if settings["question_filter"] else {}
                search_started = time.perf_counter()
                hits = store.search(name, query_vector, top_k=definition["retrieval_top_k"], filters=applied_filter)
                trace = {"id": query["id"], "split": split, "question": query["question"],
                         "strategy": name, "provided_filter": query["filter"], "applied_filter": applied_filter,
                         "query_embedding_seconds_shared": query_seconds,
                         "search_seconds": time.perf_counter() - search_started, "hits": hits}
                raw.append(trace)
                stream.write(json.dumps(trace, ensure_ascii=False) + "\n")
                stream.flush()
            print(f"Đã chạy {query['id']}: A/B/C", flush=True)

    # Chỉ đối chiếu đáp án/bằng chứng sau khi đã lấy xong kết quả tìm kiếm.
    gold = {question["id"]: question for question in _jsonl(ROOT / "benchmark/questions.jsonl")}
    checked = []
    for trace in raw:
        question = gold[trace["id"]]
        if (trace["question"], trace["provided_filter"], split) != (question["question"], question["filter"], question["split"]):
            raise ValueError("Đầu vào tìm kiếm khác bộ câu hỏi đã chốt")
        checked.append({**trace, **evaluate_query(question, trace["hits"])})
    trace_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in checked), encoding="utf-8")
    summary = summarize(checked)
    summary.update(status="complete", split=split, completed_at_utc=datetime.now(timezone.utc).isoformat(),
                   model=embedder.info, model_signature=embedder.signature, model_load_seconds=model_load_seconds,
                   fingerprints=fingerprints, top_k=definition["retrieval_top_k"], trace_rows=len(checked),
                   trace_path=str(trace_path.relative_to(ROOT)).replace("\\", "/"),
                   query_embedding="Mỗi câu được embed một lần và dùng chung vector cho A/B/C.",
                   evidence_review="Đối chiếu toàn bộ quote đã chốt; trường hợp bằng chứng tương đương cần kiểm tra riêng.",
                   service_cost_usd=0)
    csv_path = ROOT / f"results/{split}_metrics.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary["metrics"][0]))
        writer.writeheader()
        writer.writerows(summary["metrics"])
    if split == "dev":
        resources = {row["strategy"]: row for row in ingest["strategies"]}
        best = min(summary["metrics"], key=lambda row: (
            -row["evidence_hit3_n"], -row["hit1_n"],
            resources[row["strategy"]]["ingest_seconds"], resources[row["strategy"]]["chunk_count"], row["strategy"]))
        summary["suggested_strategy"] = best["strategy"]
        if previous_selection.get("status") != "fixed":
            _save(selection_path, {"status": "dev_review_pending", "suggested_strategy": best["strategy"],
                                   "fingerprints": fingerprints, "model_signature": embedder.signature,
                                   "criteria": definition["selection_criteria_in_order"],
                                   "dev_summary": "results/dev_summary.json"})
    else:
        summary["selected_strategy"] = previous_selection["selected_strategy"]
        summary["selection_fixed_at_utc"] = previous_selection["fixed_at_utc"]
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Chạy dev trước; test cần cấu hình đã chốt.")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    args = parser.parse_args()
    output = ROOT / f"results/{args.split}_summary.json"
    output.parent.mkdir(exist_ok=True)
    _save(output, {"status": "running", "split": args.split})
    try:
        summary = run(args.split)
    except Exception as error:
        _save(output, {"status": "failed", "split": args.split, "error": str(error)})
        parser.exit(1, f"Không hoàn tất benchmark: {error}\n")
    _save(output, summary)
    for row in summary["metrics"]:
        n = row["question_count"]
        print(f"{row['strategy']}: Hit@1 {row['hit1_n']}/{n}; Evidence Hit@3 {row['evidence_hit3_n']}/{n}")
    if args.split == "dev":
        print(f"Cấu hình được đề xuất từ dev: {summary['suggested_strategy']} (chờ kiểm tra/chốt).")


if __name__ == "__main__":
    main()
