"""Build a reproducible, reviewed PDF inventory; no embeddings or benchmark calls.

Run from any directory: python <repo>/starter/scripts/inventory_data.py
Source metadata and page review are inputs; manifest, JSONL and audit are outputs.
"""
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import logging
from pathlib import Path
import platform
import re
import sys
import time
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "starter"))

from src.ingestion import NORMALIZATION_VERSION, load_pdf, normalize_text


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_page(text: str, source: dict) -> tuple[str, int]:
    patterns = [re.compile(pattern) for pattern in source["running_header_regexes"]]
    kept, removed = [], 0
    for line in text.splitlines():
        if any(pattern.fullmatch(line) for pattern in patterns):
            removed += 1
        else:
            kept.append(line)
    cleaned = normalize_text("\n".join(kept))
    for old, new in source.get("verified_glyph_replacements", {}).items():
        cleaned = cleaned.replace(old, new)
    return cleaned, removed


def section_spans(text: str, current: dict, sections: list[dict], page: int):
    """Use verified body headings, not running headers or the page's first topic.

    A page may contain multiple sections. Offsets refer to cleaned page text;
    downstream chunking must stay within a section unit to keep filters correct.
    """
    changes = []
    for section in sections:
        heading = section["id"] + " " + section["title"]
        for match in re.finditer(r"(?m)^" + re.escape(heading) + r"$", text):
            if page != section["starts_on_page"]:
                raise ValueError(f"Heading {heading!r} found on unreviewed page {page}")
            changes.append((match.start(), section))
    changes.sort(key=lambda item: item[0])
    spans, start = [], 0
    for offset, section in changes:
        if text[start:offset].strip():
            spans.append({"start_char": start, "end_char": offset,
                          "section": current["id"], "section_title": current["title"]})
        current, start = section, offset
    if text[start:].strip():
        spans.append({"start_char": start, "end_char": len(text),
                      "section": current["id"], "section_title": current["title"]})
    return spans, current, {section["id"] for _, section in changes}


class WarningCollector(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def main() -> int:
    started = time.perf_counter()
    (ROOT / "results").mkdir(exist_ok=True)
    log_path = ROOT / "results/data_preparation.log"
    handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(name)s %(message)s")
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    warnings = WarningCollector()
    logging.getLogger("pypdf").addHandler(warnings)
    sources = read_json(ROOT / "data/sources.json")
    review = read_json(ROOT / "data/page_review.json")
    documents, pages, corpus, inventory = [], [], [], []
    seen_ids = set()
    for source in sources["documents"]:
        source_id = source["source_id"]
        if source_id in seen_ids:
            raise ValueError(f"Duplicate source ID: {source_id}")
        seen_ids.add(source_id)
        path = (ROOT / source["local_path"]).resolve()
        if not path.is_relative_to((ROOT / "data/raw").resolve()):
            raise ValueError("Source PDF must be inside data/raw")
        reviewed = review["documents"][source_id]
        sha256 = digest(path)
        if sha256 != reviewed["sha256"]:
            raise ValueError(f"{source_id}: PDF changed; re-review it before rebuilding")
        loaded = load_pdf(path, source_id, source["source_path_or_url"])
        if len(loaded) != reviewed["expected_physical_pages"]:
            raise ValueError(f"{source_id}: unexpected page count")
        included = set()
        for first, last in reviewed["included_page_ranges"]:
            selected = set(range(first, last + 1))
            if first < 1 or last < first or included & selected:
                raise ValueError(f"{source_id}: invalid/overlapping included page ranges")
            included.update(selected)
        excluded = {int(key): value for key, value in reviewed["excluded_pages"].items()}
        expected = set(range(1, len(loaded) + 1))
        if included & excluded.keys() or included | excluded.keys() != expected:
            raise ValueError(f"{source_id}: review must cover every physical page exactly once")
        current, found_headings, document_pages = source["initial_section"], set(), []
        for page in loaded:
            text, removed = clean_page(page.text, source)
            spans, current, found = section_spans(text, current, source["sections"], page.page)
            found_headings.update(found)
            include = page.page in included
            flags = []
            if len(text) < 500:
                flags.append("sparse_text_check_visual_review")
            if re.search(r"\b(?:Fig\.|Figs\.|Figure|Table)\s*\d", text):
                flags.append("figure_or_table_information_may_be_missing")
            if re.search(r"\w-\n\w", text):
                flags.append("line_end_hyphenation_preserved")
            if any(unicodedata.category(char) == "Cc" and char != "\n" for char in text):
                flags.append("unusual_control_character")
            if include and (not text or page.metadata["extraction_status"] != "ok"):
                raise ValueError(f"Included page {page.page} has no usable extraction")
            sections = list(dict.fromkeys(span["section"] for span in spans))
            exclusion = excluded.get(page.page, {})
            common = {
                "page_id": f"{source_id}:p{page.page:03d}", "page": page.page,
                "extracted_char_count": page.metadata["extracted_char_count"],
                "char_count": len(text), "include_in_corpus": include,
                "review_status": "source_checked", "exclusion_reason": exclusion.get("reason"),
                "exclusion_kind": exclusion.get("kind"),
                "extraction_status": page.metadata["extraction_status"],
                "ocr_applied": False, "removed_running_header_lines": removed,
                "sections": sections, "section_spans": spans, "quality_flags": flags,
                "review_note": reviewed.get("page_notes", {}).get(str(page.page)),
            }
            if page.metadata.get("error"):
                common["extraction_error"] = page.metadata["error"]
            document_pages.append(common)
            metadata = {"language": source["language"], "year": source["year"],
                        "document_type": source["document_type"], "license": source["license_or_permission"]}
            pages.append({**common, "document_id": source_id,
                          "source": source["source_path_or_url"], "text": text, "metadata": metadata})
            if include:
                for span in spans:
                    left, right = span["start_char"], span["end_char"]
                    while left < right and text[left].isspace():
                        left += 1
                    while right > left and text[right - 1].isspace():
                        right -= 1
                    if left == right:
                        continue
                    corpus.append({
                        "unit_id": f"{common['page_id']}:s{span['section']}",
                        "document_id": source_id, "source": source["source_path_or_url"],
                        "page": page.page, "page_id": common["page_id"],
                        "page_char_start": left, "page_char_end": right,
                        "text": text[left:right], "char_count": right - left,
                        "metadata": {**metadata, "section": span["section"],
                                     "section_title": span["section_title"]},
                    })
            inventory.append({
                "document_id": source_id, "page": page.page, "page_id": common["page_id"],
                "char_count": len(text), "included": include, "sections": "|".join(sections),
                "extraction_status": common["extraction_status"],
                "quality_flags": "|".join(flags), "exclusion_reason": exclusion.get("reason", ""),
                "review_note": common["review_note"] or "",
            })
        if found_headings != {item["id"] for item in source["sections"]}:
            raise ValueError(f"{source_id}: missing reviewed section headings")
        documents.append({**source, "file_sha256": sha256, "file_size_bytes": path.stat().st_size,
                          "physical_page_count": len(loaded), "included_page_count": len(included),
                          "included_pages": sorted(included), "excluded_pages": sorted(excluded),
                          "included_char_count": sum(p["char_count"] for p in document_pages if p["include_in_corpus"]),
                          "review": {"status": review["review_status"], "student_confirmation": review["student_confirmation"], "reviewed_at": review["reviewed_at"],
                                     "method": reviewed["review_method"]}, "pages": document_pages})
        logging.info("Inventoried %s: physical=%s included=%s excluded=%s", source_id, len(loaded), len(included), len(excluded))
    actual_raw = {p.resolve() for p in (ROOT / "data/raw").iterdir() if p.suffix.lower() == ".pdf"}
    configured_raw = {(ROOT / source["local_path"]).resolve() for source in sources["documents"]}
    if actual_raw != configured_raw:
        raise ValueError("PDF files and sources.json differ; register/review new PDFs explicitly")
    eligible = [p for p in pages if p["include_in_corpus"]]
    if len(eligible) < 30:
        raise ValueError(f"Need at least 30 reviewed content pages; got {len(eligible)}")
    if len({p["page_id"] for p in pages}) != len(pages) or len({p["unit_id"] for p in corpus}) != len(corpus):
        raise ValueError("Duplicate page or section-unit IDs")
    per_section = {}
    for unit in corpus:
        key = unit["metadata"]["section"]
        entry = per_section.setdefault(key, {"title": unit["metadata"]["section_title"], "units": 0, "pages": set()})
        entry["units"] += 1
        entry["pages"].add(unit["page_id"])
    per_section = {key: {**value, "pages": sorted(value["pages"]), "page_count": len(value["pages"])}
                   for key, value in per_section.items()}
    runtime = {"python": platform.python_version(), "pypdf": importlib.metadata.version("pypdf"),
               "extraction_mode": "layout", "normalization": NORMALIZATION_VERSION}
    run_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "generated_at_utc": run_at, "document_count": len(documents),
        "physical_pages": len(pages), "included_content_pages": len(eligible),
        "excluded_pages": [p["page"] for p in pages if not p["include_in_corpus"]],
        "meets_minimum_30_pages": True, "section_units": len(corpus),
        "included_page_characters": sum(p["char_count"] for p in eligible),
        "min_included_page_characters": min(p["char_count"] for p in eligible),
        "max_included_page_characters": max(p["char_count"] for p in eligible),
        "empty_pages_after_cleanup": [p["page"] for p in pages if not p["text"]],
        "extraction_error_pages": [p["page"] for p in pages if p["extraction_status"] == "error"],
        "mixed_section_pages": [p["page"] for p in eligible if len(p["sections"]) > 1],
        "ocr_applied": False, "paid_api_calls": 0, "paid_service_cost": 0,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "pdf_warning_count": len(warnings.messages),
        "optional_fonttools_missing_warning_count": sum("fontTools is required" in msg for msg in warnings.messages),
        "other_pdf_warnings": sorted({msg for msg in warnings.messages if "fontTools is required" not in msg}),
        "unusual_control_character_pages": [p["page"] for p in pages if "unusual_control_character" in p["quality_flags"]],
        "warning_log": "results/data_preparation.log", "per_section": per_section, "runtime": runtime,
        "review_status": review["review_status"], "student_confirmation": review["student_confirmation"],
    }
    manifest = {
        "schema_version": "1.0", "generated_at_utc": run_at,
        "page_numbering": "physical_pdf_1_based", "counting_rule": review["counting_rule"],
        "character_count_definition": "Python len(text) after NFKC normalization, whitespace cleanup, verified glyph replacement and removal of reviewed running headers; includes retained newlines.",
        "runtime": runtime, "configuration_sha256": {"sources": digest(ROOT / "data/sources.json"),
                                                     "review": digest(ROOT / "data/page_review.json")},
        "outputs": {"all_pages": "data/processed/pages.jsonl", "selected_section_units": "data/processed/corpus.jsonl",
                    "inventory": "results/data_inventory.csv", "quality": "results/data_quality.json"},
        "summary": summary, "documents": documents,
    }
    write_jsonl(ROOT / "data/processed/pages.jsonl", pages)
    write_jsonl(ROOT / "data/processed/corpus.jsonl", corpus)
    with (ROOT / "results/data_inventory.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(inventory[0]))
        writer.writeheader()
        writer.writerows(inventory)
    write_json(ROOT / "data/manifest.json", manifest)
    write_json(ROOT / "results/data_quality.json", summary)
    report = [
        "# Kiểm kê dữ liệu", "",
        f"- Chọn **{len(eligible)}/{len(pages)} trang**, đạt tối thiểu 30 trang nội dung.",
        f"- Loại trang: {', '.join(map(str, summary['excluded_pages']))}; lý do trong `data_inventory.csv`.",
        f"- Số ký tự: {summary['included_page_characters']:,}; số đơn vị theo mục: {len(corpus)}.",
        f"- Trích bằng pypdf {runtime['pypdf']}, chế độ layout, chuẩn hóa {NORMALIZATION_VERSION}.",
        "- Đếm trang vật lý từ 1; đơn vị theo mục không được tính thêm thành trang.",
        f"- Lỗi trích xuất: {summary['extraction_error_pages']}; trang rỗng sau bỏ header: {summary['empty_pages_after_cleanup']}.",
        f"- Cảnh báo PDF: {summary['pdf_warning_count']}, gồm {summary['optional_fonttools_missing_warning_count']} cảnh báo thiếu fontTools tùy chọn; chi tiết ở `data_preparation.log`.",
        "", "Các trang có nhiều mục được tách thành các khoảng ký tự để giữ đúng filter.",
        "Text trong hình và quan hệ ô/cột của bảng chưa được trích đầy đủ. Dấu nối cuối",
        "dòng được giữ nguyên; cần đối chiếu nguồn khi chọn evidence. Các số liệu trong",
        "sách được hiểu theo phiên bản tài liệu, không xem là thông tin hiện hành.",
        "", "Nguồn, giấy phép, SHA-256 và metadata: `../data/manifest.json`.",
        "Cách chạy và kiểm tra dữ liệu: `../data/README.md`.", "",
    ]
    (ROOT / "results/data_quality.md").write_text("\n".join(report), encoding="utf-8")
    logging.info("Completed: pages=%s content=%s units=%s", len(pages), len(eligible), len(corpus))
    print(json.dumps({key: summary[key] for key in ["physical_pages", "included_content_pages", "excluded_pages",
                                                  "section_units", "included_page_characters", "elapsed_seconds"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        logging.exception("Inventory failed")
        print(f"Inventory failed: {error}", file=sys.stderr)
        raise SystemExit(1)
