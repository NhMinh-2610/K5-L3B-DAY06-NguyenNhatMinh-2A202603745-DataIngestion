"""Đối chiếu nguồn/trang và toàn bộ bằng chứng; không tự gán nhãn grounding."""
from collections import defaultdict
import re
from typing import Any
import unicodedata


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Một hit phải chứa đủ một gold hợp lệ trong cùng chunk, ở đúng nguồn/trang.

    Chỉ chuẩn hóa Unicode/khoảng trắng khi so khớp. Bằng chứng tương đương khác
    cần được đối chiếu riêng; kết quả này không suy ra từ việc thấy đúng trang.
    """
    golds = question["gold_evidence"]
    if not golds or any(not _text(gold["quote"]) for gold in golds):
        raise ValueError("Câu hỏi thiếu bằng chứng hợp lệ")
    checked = []
    for rank, original in enumerate(hits[:3], start=1):
        hit = dict(original)
        source_page = [gold for gold in golds if
                       hit["document_id"] == gold["source_id"] and hit["page"] == gold["page"]]
        matched = [gold for gold in source_page if _text(gold["quote"]) in _text(hit["text"])]
        hit.update(rank=rank, source_page_match=bool(source_page), evidence_hit=bool(matched),
                   matched_gold=[{"source_id": g["source_id"], "page": g["page"], "quote": g["quote"]} for g in matched])
        checked.append(hit)
    return {
        "id": question["id"], "split": question["split"], "question": question["question"],
        "expected_answer": question["expected_answer"], "gold_evidence": golds,
        "hits": checked, "hit_at_1": bool(checked and checked[0]["evidence_hit"]),
        "evidence_hit_at_3": any(hit["evidence_hit"] for hit in checked),
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Tổng hợp theo cấu hình/split, giữ cả tử số và mẫu số."""
    groups = defaultdict(list)
    for trace in traces:
        groups[(trace["strategy"], trace["split"])].append(trace)
    rows = []
    for (strategy, split), group in sorted(groups.items()):
        n = len(group)
        if len({t["id"] for t in group}) != n:
            raise ValueError("Có câu hỏi bị tính lặp trong cùng cấu hình")
        h1 = sum(t["hit_at_1"] for t in group)
        h3 = sum(t["evidence_hit_at_3"] for t in group)
        scoped = [t for t in group if t.get("provided_filter")]
        compliant = sum(bool(t["hits"]) and all(
            hit["metadata"].get(key) == value for hit in t["hits"]
            for key, value in t["provided_filter"].items()) for t in scoped)
        rows.append({
            "strategy": strategy, "split": split, "question_count": n,
            "hit1_n": h1, "hit1_rate": h1 / n, "evidence_hit3_n": h3, "evidence_hit3_rate": h3 / n,
            "filter_questions": len(scoped), "filter_compliant_n": compliant,
            "filter_compliance_rate": compliant / len(scoped) if scoped else None,
            "mean_search_ms": sum(t.get("search_seconds", 0) for t in group) * 1000 / n,
        })
    return {"metrics": rows, "matching": "source_page_and_full_quote_whitespace_normalized"}
