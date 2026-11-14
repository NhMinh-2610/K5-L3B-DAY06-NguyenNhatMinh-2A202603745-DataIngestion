"""Check gold evidence and fixed splits; export query-only inputs and review files.

This does not call an embedding provider, retrieve chunks or assign benchmark scores.
Existing student checklist entries are preserved on repeated runs.
"""
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def require(condition, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate() -> dict:
    folder = ROOT / "benchmark"
    questions = load_jsonl(folder / "questions.jsonl")
    split = json.loads((folder / "split.json").read_text(encoding="utf-8"))
    pages = load_jsonl(ROOT / "data/processed/pages.jsonl")
    corpus = load_jsonl(ROOT / "data/processed/corpus.jsonl")
    units = {unit["unit_id"]: unit for unit in corpus}
    page_lookup = {page["page_id"]: page for page in pages}
    require(sha256(folder / "questions.jsonl") == split["questions_sha256"], "Bộ câu hỏi đã thay đổi so với bản chốt; cần kiểm tra và ghi nhận phiên bản mới.")
    require(sha256(ROOT / "data/processed/corpus.jsonl") == split["corpus_sha256"], "Corpus đã thay đổi so với bản chốt.")
    require(sha256(ROOT / "data/raw/978-981-19-2879-6_1.pdf") == split["source_pdf_sha256"], "PDF gốc đã thay đổi.")
    require(len(questions) >= 20, "Cần ít nhất 20 câu hỏi.")
    ids = [q["id"] for q in questions]
    require(len(ids) == len(set(ids)), "ID câu hỏi bị trùng.")
    require(len({q["question"].strip().casefold() for q in questions}) == len(questions), "Nội dung câu hỏi bị trùng.")
    require(set(split["dev_ids"]).isdisjoint(split["test_ids"]), "Dev và test có ID trùng nhau.")
    require(len(split["dev_ids"]) == len(set(split["dev_ids"])) and len(split["test_ids"]) == len(set(split["test_ids"])), "Split chứa ID trùng.")
    require(set(ids) == set(split["dev_ids"]) | set(split["test_ids"]), "Split không khớp bộ câu hỏi.")
    counts = {name: sum(q["split"] == name for q in questions) for name in ["dev", "test"]}
    require(counts["dev"] >= 15 and counts["test"] >= 5, "Cần ít nhất 15 dev và 5 test.")
    filter_ids = [q["id"] for q in questions if q["filter"]]
    test_filter_ids = [q["id"] for q in questions if q["filter"] and q["split"] == "test"]
    require(len(filter_ids) >= 3 and len(test_filter_ids) >= 1, "Cần ít nhất 3 câu filter, trong đó ít nhất 1 câu test.")
    evidence_pages = {"dev": set(), "test": set()}
    details = []
    for question in questions:
        qid = question["id"]
        require(question["split"] in counts, f"{qid}: split không hợp lệ.")
        require(qid in split[question["split"] + "_ids"], f"{qid}: split khác bản chốt.")
        require(all(isinstance(question[key], str) and question[key].strip() for key in
                    ["question", "expected_answer", "gold_source_id", "evidence_quote"]), f"{qid}: thiếu nội dung bắt buộc.")
        require(isinstance(question["filter"], dict) and set(question["filter"]) <= {"section"}, f"{qid}: chỉ lọc theo section đã cung cấp trước.")
        require(not question["filter"] or question.get("filter_origin"), f"{qid}: thiếu nguồn của filter.")
        require(question["gold_source_id"] not in question["question"], f"{qid}: câu hỏi chứa gold source ID.")
        require(not re.search(r"\b(?:p\d{3}|gold_page|gold_source_id)\b", question["question"]), f"{qid}: câu hỏi có dấu hiệu chứa gold metadata.")
        golds = question["gold_evidence"]
        require(bool(golds), f"{qid}: thiếu gold evidence.")
        require(golds[0]["source_id"] == question["gold_source_id"] and golds[0]["page"] == question["gold_page"]
                and golds[0]["quote"] == question["evidence_quote"], f"{qid}: gold chính không nhất quán.")
        alternatives = set()
        for gold in golds:
            unit = units[gold["unit_id"]]
            page = page_lookup[unit["page_id"]]
            require(unit["document_id"] == gold["source_id"] and unit["page"] == gold["page"], f"{qid}: sai nguồn/trang.")
            require(page["include_in_corpus"], f"{qid}: bằng chứng thuộc trang bị loại.")
            require(unit["metadata"]["section"] == gold["section"], f"{qid}: sai mục của bằng chứng.")
            require(bool(gold["quote"].strip()) and gold["quote"] in unit["text"], f"{qid}: đoạn trích không tồn tại trong đơn vị nguồn.")
            left, right = gold["page_char_start"], gold["page_char_end"]
            require(isinstance(left, int) and isinstance(right, int) and 0 <= left < right <= page["char_count"], f"{qid}: offsets không hợp lệ.")
            require(page["text"][left:right] == gold["quote"], f"{qid}: offsets không khớp đoạn trích.")
            require(unit["page_char_start"] <= left < right <= unit["page_char_end"], f"{qid}: đoạn trích vượt ranh giới mục.")
            require(all(unit["metadata"].get(key) == value for key, value in question["filter"].items()), f"{qid}: filter loại mất bằng chứng hợp lệ.")
            key = (gold["source_id"], gold["page"], gold["page_char_start"], gold["page_char_end"])
            require(key not in alternatives, f"{qid}: gold thay thế bị trùng.")
            alternatives.add(key)
            evidence_pages[question["split"]].add((gold["source_id"], gold["page"]))
        details.append({"id": qid, "split": question["split"], "gold_count": len(golds),
                        "primary_page": question["gold_page"], "filter": question["filter"],
                        "source_text_check": "passed", "page_offset_check": "passed", "filter_scope_check": "passed"})
    require(evidence_pages["dev"].isdisjoint(evidence_pages["test"]), "Trang bằng chứng dev và test bị trùng.")

    checklist_path = folder / "review_checklist.csv"
    columns = ["id", "split", "question", "gold_page", "alternative_gold_pages", "expected_answer", "filter", "student_status", "student_note"]
    if checklist_path.exists():
        with checklist_path.open(encoding="utf-8-sig", newline="") as stream:
            checklist = list(csv.DictReader(stream))
        require(len(checklist) == len(ids) and {row["id"] for row in checklist} == set(ids), "Checklist không khớp ID câu hỏi; giữ file cũ để kiểm tra.")
        require(all(row["student_status"] in {"chua_kiem_tra", "dong_y", "can_sua"} for row in checklist), "Trạng thái checklist không hợp lệ.")
        question_lookup = {q["id"]: q for q in questions}
        for row in checklist:
            question = question_lookup[row["id"]]
            require(all(row[key] == str(question[key]) for key in ["split", "question", "gold_page", "expected_answer"]),
                    f"{row['id']}: nội dung checklist khác bộ câu hỏi; giữ góp ý cũ và kiểm tra trước khi cập nhật.")
            require(json.loads(row["filter"]) == question["filter"], f"{row['id']}: filter trong checklist không khớp.")
            require(row["alternative_gold_pages"] == "|".join(str(g["page"]) for g in question["gold_evidence"][1:]),
                    f"{row['id']}: trang bằng chứng thay thế trong checklist không khớp.")
    else:
        checklist = [{"id": q["id"], "split": q["split"], "question": q["question"], "gold_page": q["gold_page"],
                      "alternative_gold_pages": "|".join(str(g["page"]) for g in q["gold_evidence"][1:]),
                      "expected_answer": q["expected_answer"], "filter": json.dumps(q["filter"], ensure_ascii=False),
                      "student_status": "chua_kiem_tra", "student_note": ""} for q in questions]
        with checklist_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(checklist)
    for name in ["dev", "test"]:
        queries = [{key: q[key] for key in ["id", "split", "question", "filter"]} for q in questions if q["split"] == name]
        write_jsonl(folder / f"{name}_queries.jsonl", queries)
    readable = ["# Bộ câu hỏi đánh giá truy xuất", "",
                "Câu hỏi và đáp án dùng tiếng Việt. Bằng chứng giữ nguyên văn tiếng Anh để đối chiếu nguồn.",
                "Số trang là vị trí trong PDF, bắt đầu từ 1. Các đoạn trích lấy từ text đã chuẩn hóa.",
                "Bảng này dùng để rà soát gold trước thí nghiệm; chưa có kết quả hoặc điểm truy xuất.", "",
                "| Tập | Số câu | Câu có filter |", "|---|---|---|",
                f"| Dev | {counts['dev']} | {', '.join(q['id'] for q in questions if q['split']=='dev' and q['filter'])} |",
                f"| Test | {counts['test']} | {', '.join(test_filter_ids)} |", ""]
    for q in questions:
        readable.extend([f"## {q['id']} · {q['split']}", "", q["question"], "",
                         "**Đáp án:** " + q["expected_answer"], "",
                         "**Phạm vi lọc:** " + (q["filter_origin"] if q["filter"] else "Không giới hạn theo mục."), ""])
        for index, gold in enumerate(q["gold_evidence"]):
            label = "Bằng chứng chính" if index == 0 else "Bằng chứng thay thế"
            readable.extend([f"**{label}:** trang {gold['page']}, mục {gold['section']}.", "",
                             *["> " + line for line in gold["quote"].splitlines()], ""])
    (folder / "questions.md").write_text("\n".join(readable), encoding="utf-8")
    return {
        "status": "passed", "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "benchmark_version": split["benchmark_version"], "question_count": len(questions),
        "split_counts": counts, "filter_question_ids": filter_ids, "test_filter_question_ids": test_filter_ids,
        "gold_evidence_count": sum(len(q["gold_evidence"]) for q in questions),
        "dev_test_evidence_pages_disjoint": True,
        "student_checklist_counts": {status: sum(row["student_status"] == status for row in checklist)
                                     for status in ["chua_kiem_tra", "dong_y", "can_sua"]},
        "checks": details, "retrieval_executed": False,
        "scope": "Checks cover source text, page/section offsets, fixed split, filters and query-only inputs; no retrieval or answer-quality scores are assigned.",
        "files_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path) for path in
                         [folder / "questions.jsonl", folder / "split.json", ROOT / "data/processed/corpus.jsonl",
                          folder / "dev_queries.jsonl", folder / "test_queries.jsonl"]},
    }


if __name__ == "__main__":
    output = ROOT / "results/benchmark_validation.json"
    output.parent.mkdir(exist_ok=True)
    try:
        report = validate()
    except Exception as error:
        report = {"status": "failed", "checked_at_utc": datetime.now(timezone.utc).isoformat(), "error": str(error), "retrieval_executed": False}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ["status", "question_count", "split_counts", "error"] if key in report}, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "passed" else 1)
