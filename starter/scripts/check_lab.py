"""Đối chiếu corpus, chunk, benchmark, trace và database; không chạy lại test."""
import argparse
import ast
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from starter.src.evaluation import evaluate_query, summarize
from starter.src.models import Chunk
from starter.scripts.prepare_chunks import check_chunks


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8-sig"))


def lines(path):
    return [json.loads(line) for line in (ROOT / path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", action="store_true", help="Đọc và kiểm tra toàn bộ vector trong database")
    args = parser.parse_args()
    checks = []

    def check(name, action):
        try:
            action()
            checks.append({"check": name, "status": "passed"})
        except Exception as error:
            checks.append({"check": name, "status": "failed", "error": str(error)})

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    definition = read("benchmark/split.json")
    selection = read("results/selection.json")
    pages = lines("data/processed/pages.jsonl")
    units = lines("data/processed/corpus.jsonl")
    chunks = {s: lines(f"data/processed/chunks_{s}.jsonl") for s in ["A", "B"]}
    chunks["C"] = chunks["B"]
    gold = {q["id"]: q for q in lines("benchmark/questions.jsonl")}

    def corpus():
        require(digest("data/raw/978-981-19-2879-6_1.pdf") == definition["source_pdf_sha256"], "PDF thay đổi")
        require(len(pages) == 41 and sum(p["include_in_corpus"] for p in pages) == 35, "Số trang sai")
        for key, path in [("corpus_sha256", "data/processed/corpus.jsonl"), ("questions_sha256", "benchmark/questions.jsonl")]:
            require(digest(path) == definition[key] == selection["fingerprints"][key], "Hash không khớp: " + path)
        for strategy in ["A", "B"]:
            check_chunks(units, [Chunk(**c) for c in chunks[strategy]], 500)
            cache = read(f"data/processed/vectors_{strategy}.json")
            require(cache["chunks_sha256"] == digest(f"data/processed/chunks_{strategy}.jsonl"), "Cache chunk cũ")
            require(cache["model_signature"] == selection["model_signature"], "Cache model khác")
            require(len(cache["vectors"]) == len(chunks[strategy]), "Thiếu vector")
            require(all(len(v) == 384 and all(math.isfinite(x) for x in v) and abs(sum(x*x for x in v)-1) < 1e-4 for v in cache["vectors"]), "Vector không hợp lệ")
    check("corpus_chunks_vectors", corpus)

    def benchmark():
        for split in ["dev", "test"]:
            queries = lines(f"benchmark/{split}_queries.jsonl")
            require({q["id"] for q in queries} == set(definition[split+"_ids"]), "Sai split")
            require(all(set(q) == {"id", "split", "question", "filter"} and q["question"] == gold[q["id"]]["question"] and q["filter"] == gold[q["id"]]["filter"] for q in queries), "Query có gold hoặc không khớp câu hỏi")
            traces = lines(f"results/{split}_trace.jsonl")
            require(len(traces) == len(queries)*3, "Thiếu trace")
            lookup = {s: {c["chunk_id"]: c for c in chunks[s]} for s in chunks}
            for trace in traces:
                require(len(trace["hits"]) == 3, "Thiếu top-3")
                require(trace["applied_filter"] == (trace["provided_filter"] if trace["strategy"] == "C" else {}), "Sai filter")
                for hit in trace["hits"]:
                    source = lookup[trace["strategy"]][hit["chunk_id"]]
                    require(all(hit[k] == source[k] for k in ["document_id", "source", "page", "text"]), "Trace không khớp chunk")
                evaluated = evaluate_query(gold[trace["id"]], trace["hits"])
                require(all(trace[k] == evaluated[k] for k in ["hit_at_1", "evidence_hit_at_3"]), "Điểm trace sai")
            summary = read(f"results/{split}_summary.json")
            require(summarize(traces)["metrics"] == summary["metrics"], "Tổng hợp sai")
            with (ROOT / f"results/{split}_metrics.csv").open(encoding="utf-8-sig") as stream:
                actual = list(csv.DictReader(stream))
            require(actual == [{k: str(v) for k,v in row.items()} for row in summary["metrics"]], "CSV khác summary")
        require(selection["status"] == "fixed" and selection["fixed_at_utc"] < read("results/test_summary.json")["completed_at_utc"], "Chưa chốt trước test")
        for key, path in [("strategies_sha256", "starter/strategies.json"), ("embedding_sha256", "starter/embedding.json")]:
            require(digest(path) == selection["fingerprints"][key], "Cấu hình thay đổi")
    check("benchmark_traces_metrics_freeze", benchmark)

    def syntax():
        for path in (ROOT / "starter").rglob("*.py"):
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    check("python_syntax", syntax)

    if args.database:
        def database():
            import os
            import psycopg
            from dotenv import load_dotenv
            load_dotenv(ROOT / "starter/.env", override=True)
            with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5) as conn:
                conn.read_only = True
                with conn.cursor() as cur:
                    for strategy in chunks:
                        cur.execute("SELECT model_signature,dimensions FROM lab_vector_spaces WHERE strategy=%s", (strategy,))
                        require(cur.fetchone() == (selection["model_signature"],384), "Model database khác cấu hình")
                        cur.execute("SELECT chunk_id,source,page,text,metadata,embedding::text FROM lab_chunks WHERE strategy=%s", (strategy,))
                        rows = cur.fetchall()
                        expected = {c["chunk_id"]:c for c in chunks[strategy]}
                        cache = read(f"data/processed/vectors_{'B' if strategy == 'C' else strategy}.json")
                        vectors = dict(zip(expected,cache["vectors"]))
                        require(len(rows) == len(expected), "Số dòng sai: " + strategy)
                        for cid,source,page,text,meta,vector in rows:
                            c = expected[cid]
                            require((source,page,text,meta) == (c["source"],c["page"],c["text"],c["metadata"]), "Database khác chunk")
                            values = json.loads(vector)
                            require(len(values) == 384 and abs(sum(v*v for v in values)-1) < 1e-4, "Vector database sai")
                            require(all(abs(a-b) < 1e-6 for a,b in zip(values,vectors[cid])), "Vector database khác cache")
        check("database_all_592_rows", database)
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "checks": checks,
              "manual_review": "Điểm nháp cần người học rà và xác nhận; không thay cho kiểm tra thủ công.",
              "status": "passed" if all(c["status"] == "passed" for c in checks) else "failed"}
    (ROOT / "results/lab_check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
