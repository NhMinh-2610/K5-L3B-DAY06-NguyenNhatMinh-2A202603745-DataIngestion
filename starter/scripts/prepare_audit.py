"""Chuẩn bị mẫu chấm, tổng hợp nháp và nhãn đã được người học xác nhận."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def save_csv(path, data):
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            old_columns, old = reader.fieldnames, list(reader)
        if len(old) != len(data) or {r["sample_id"] for r in old} != {r["sample_id"] for r in data}:
            raise ValueError(f"{path.name} có mẫu khác; giữ nguyên để kiểm tra")
        if set(data[0]) <= set(old_columns):
            return
        lookup = {row["sample_id"]: row for row in old}
        data = [{**row, **lookup[row["sample_id"]]} for row in data]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)


def summarize_audit(draft=False):
    data = {}
    for name, count in [("coherence", 30), ("grounding", 15), ("metadata", 45)]:
        path = ROOT / f"results/manual_{name}.csv"
        with path.open(encoding="utf-8-sig", newline="") as stream:
            data[name] = list(csv.DictReader(stream))
        if len(data[name]) != count or len({r["sample_id"] for r in data[name]}) != count:
            raise ValueError(f"{path.name}: số mẫu không khớp")
        fields = ["source_ok", "page_ok", "section_ok"] if name == "metadata" else ["score"]
        if name == "grounding":
            fields += ["verified_hit1", "verified_hit3"]
        for row in data[name]:
            if not draft and row.get("review_status") != "confirmed":
                raise ValueError(f"{path.name}, {row['sample_id']}: cần rà và đặt review_status=confirmed; dùng --draft để xem tổng hợp nháp")
            for field in fields:
                allowed = {"0", "1", "2"} if field == "score" else {"0", "1"}
                if row[field].strip() not in allowed:
                    raise ValueError(f"{path.name}, {row['sample_id']}: cần điền {field}")
            if name == "grounding" and int(row["verified_hit1"]) > int(row["verified_hit3"]):
                raise ValueError(f"{row['sample_id']}: Hit@1 đúng thì Hit@3 cũng phải đúng")
            needs_reason = name != "metadata" or any(row[field].strip() == "0" for field in fields)
            if needs_reason and not row["reason"].strip():
                raise ValueError(f"{path.name}, {row['sample_id']}: cần ghi lý do")
    output = []
    test = json.loads((ROOT / "results/test_summary.json").read_text(encoding="utf-8"))
    for strategy in ["A", "B", "C"]:
        coherence = [r for r in data["coherence"] if r["strategy"] == strategy]
        grounding = [r for r in data["grounding"] if r["strategy"] == strategy]
        metadata = [r for r in data["metadata"] if r["strategy"] == strategy]
        if (len(coherence), len(grounding), len(metadata)) != (10, 5, 15):
            raise ValueError("Số mẫu từng cấu hình không khớp")
        automatic = next(r for r in test["metrics"] if r["strategy"] == strategy)
        output.append({
            "sample_id": strategy, "strategy": strategy,
            "review_status": "draft" if draft else "confirmed",
            "coherence_mean_out_of_2": sum(int(r["score"]) for r in coherence) / 10,
            "coherence_n": 10,
            "metadata_correct_n": sum(all(r[k].strip() == "1" for k in ["source_ok", "page_ok", "section_ok"]) for r in metadata),
            "metadata_checked_n": 15,
            "filter_compliant_questions": automatic["filter_compliant_n"],
            "filter_questions": automatic["filter_questions"],
            "grounding_0": sum(r["score"].strip() == "0" for r in grounding),
            "grounding_1": sum(r["score"].strip() == "1" for r in grounding),
            "grounding_2": sum(r["score"].strip() == "2" for r in grounding),
            "grounding_mean_out_of_2": sum(int(r["score"]) for r in grounding) / 5,
            "grounding_n": 5,
            "verified_hit1_n": sum(int(r["verified_hit1"]) for r in grounding),
            "verified_hit3_n": sum(int(r["verified_hit3"]) for r in grounding),
            "verified_retrieval_n": 5,
        })
    path = ROOT / ("results/draft_manual_metrics.csv" if draft else "results/manual_metrics.csv")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    print(json.dumps({"manual_metrics": str(path.relative_to(ROOT)), "status": "draft" if draft else "complete"}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coherence-only", action="store_true")
    parser.add_argument("--summarize", action="store_true")
    parser.add_argument("--draft", action="store_true", help="Tổng hợp nháp, chưa xác nhận điểm thủ công")
    args = parser.parse_args()
    if args.summarize:
        summarize_audit(draft=args.draft)
        return
    corpus_path = ROOT / "data/processed/corpus.jsonl"
    fingerprint = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    pages = sorted((p for p in rows(ROOT / "data/processed/pages.jsonl") if p["include_in_corpus"]),
                   key=lambda p: (p["document_id"], p["page"]))[:10]
    sample_path = ROOT / "results/audit_sampling.json"
    if sample_path.exists():
        sampling = json.loads(sample_path.read_text(encoding="utf-8"))
        if sampling["corpus_sha256"] != fingerprint:
            raise ValueError("Corpus khác lần chọn mẫu")
    else:
        anchors = []
        for page in pages:
            position = len(page["text"]) // 2
            while position < len(page["text"]) and page["text"][position].isspace():
                position += 1
            anchors.append({"page_id": page["page_id"], "document_id": page["document_id"],
                            "page": page["page"], "page_char": position})
        sampling = {"chosen_at_utc": datetime.now(timezone.utc).isoformat(),
                    "chosen_before_test_retrieval": not (ROOT / "results/test_trace.jsonl").exists(),
                    "rule": "10 trang nội dung đầu theo document_id/page; điểm giữa text trang, dịch đến ký tự không trắng. Nếu nhiều chunk phủ điểm, chọn chunk có vị trí bắt đầu nhỏ nhất.",
                    "corpus_sha256": fingerprint, "anchors": anchors}
        sample_path.write_text(json.dumps(sampling, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    chunks = {"A": rows(ROOT / "data/processed/chunks_A.jsonl"),
              "B": rows(ROOT / "data/processed/chunks_B.jsonl")}
    coherence = []
    for anchor in sampling["anchors"]:
        for strategy in ["A", "B", "C"]:
            candidates = [c for c in chunks["B" if strategy == "C" else strategy]
                          if c["document_id"] == anchor["document_id"] and c["page"] == anchor["page"]
                          and c["metadata"]["page_char_start"] <= anchor["page_char"] < c["metadata"]["page_char_end"]]
            if not candidates:
                raise ValueError("Không có chunk phủ vị trí đã chọn")
            chunk = min(candidates, key=lambda c: (c["metadata"]["page_char_start"], c["chunk_id"]))
            coherence.append({"sample_id": anchor["page_id"] + ":" + strategy,
                              "strategy": strategy, "page": anchor["page"], "anchor_char": anchor["page_char"],
                              "chunk_id": chunk["chunk_id"], "section": chunk["metadata"]["section"],
                              "chunk_text": chunk["text"], "score": "", "reason": ""})
    save_csv(ROOT / "results/manual_coherence.csv", coherence)
    if args.coherence_only:
        print(json.dumps({"coherence_rows": len(coherence), "points": len(sampling["anchors"])}))
        return
    summary = json.loads((ROOT / "results/test_summary.json").read_text(encoding="utf-8"))
    if summary["status"] != "complete":
        raise ValueError("Cần chạy test hoàn tất trước khi chuẩn bị bảng chấm")
    traces = rows(ROOT / "results/test_trace.jsonl")
    grounding, metadata = [], []
    for trace in traces:
        sample = trace["strategy"] + ":" + trace["id"]
        retrieved = "\n\n".join(f"Hạng {h['rank']}, trang {h['page']}, mục {h['metadata']['section']}:\n{h['text']}" for h in trace["hits"])
        grounding.append({"sample_id": sample, "strategy": trace["strategy"], "question_id": trace["id"],
                          "question": trace["question"], "expected_answer": trace["expected_answer"],
                          "gold_pages": "|".join(str(g["page"]) for g in trace["gold_evidence"]),
                          "top3_text": retrieved, "auto_hit1": int(trace["hit_at_1"]),
                          "auto_hit3": int(trace["evidence_hit_at_3"]), "verified_hit1": "", "verified_hit3": "",
                          "score": "", "reason": ""})
        for hit in trace["hits"]:
            metadata.append({"sample_id": sample + ":r" + str(hit["rank"]), "strategy": trace["strategy"],
                             "question_id": trace["id"], "rank": hit["rank"], "chunk_id": hit["chunk_id"],
                             "source": hit["source"], "page": hit["page"], "section": hit["metadata"]["section"],
                             "provided_filter": json.dumps(trace["provided_filter"], ensure_ascii=False),
                             "chunk_text": hit["text"], "source_ok": "", "page_ok": "", "section_ok": "", "reason": ""})
    save_csv(ROOT / "results/manual_grounding.csv", grounding)
    save_csv(ROOT / "results/manual_metadata.csv", metadata)
    print(json.dumps({"coherence_rows": len(coherence), "grounding_rows": len(grounding), "metadata_rows": len(metadata)}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError) as error:
        raise SystemExit(f"Chưa hoàn tất bảng chấm: {error}")
