"""Tạo chunk A/B và thống kê A/B/C bằng thư viện chuẩn Python."""
import csv
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "starter"))
from src.chunking import by_paragraph, fixed_size
from src.models import DocumentPage


def check_chunks(units, chunks, size):
    lookup = {u["unit_id"]: u for u in units}
    covered = {key: bytearray(len(unit["text"])) for key, unit in lookup.items()}
    if len({c.chunk_id for c in chunks}) != len(chunks):
        raise ValueError("ID chunk bị trùng")
    for chunk in chunks:
        meta = chunk.metadata
        unit = lookup[meta["unit_id"]]
        left, right = meta["unit_char_start"], meta["unit_char_end"]
        if not (0 <= left < right <= len(unit["text"]) and 0 < len(chunk.text) <= size):
            raise ValueError("Kích thước hoặc vị trí chunk không hợp lệ")
        if chunk.text != unit["text"][left:right]:
            raise ValueError("Text chunk không khớp nguồn")
        if (chunk.document_id, chunk.source, chunk.page) != (unit["document_id"], unit["source"], unit["page"]):
            raise ValueError("Chunk sai nguồn/trang")
        if meta["section"] != unit["metadata"]["section"]:
            raise ValueError("Chunk vượt phạm vi mục")
        if meta["page_char_start"] != unit["page_char_start"] + left or meta["page_char_end"] != unit["page_char_start"] + right:
            raise ValueError("Vị trí trong trang không khớp")
        covered[meta["unit_id"]][left:right] = b"\x01" * (right - left)
    for key, unit in lookup.items():
        if any(not covered[key][i] and not char.isspace() for i, char in enumerate(unit["text"])):
            raise ValueError(f"Bỏ sót nội dung nguồn: {key}")


def main():
    config = json.loads((ROOT / "starter/strategies.json").read_text(encoding="utf-8"))
    corpus_path = ROOT / config["corpus_path"]
    split = json.loads((ROOT / "benchmark/split.json").read_text(encoding="utf-8"))
    if hashlib.sha256(corpus_path.read_bytes()).hexdigest() != split["corpus_sha256"]:
        raise ValueError("Corpus khác bản đã chốt cho benchmark")
    units = [json.loads(line) for line in corpus_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    pages = [DocumentPage(u["document_id"], u["source"], u["page"], u["text"],
                          {**u["metadata"], "unit_id": u["unit_id"], "page_char_start": u["page_char_start"]}) for u in units]
    built, stats = {}, []
    for name, strategy in config["strategies"].items():
        started = time.perf_counter()
        reuse = strategy.get("reuse_chunks_from")
        if reuse:
            if reuse not in built or strategy["chunks_path"] != config["strategies"][reuse]["chunks_path"]:
                raise ValueError("C phải dùng đúng tập chunk của B")
            chunks = built[reuse]
            settings = config["strategies"][reuse]
        else:
            settings, chunks = strategy, []
            for page in pages:
                if strategy["chunking"] == "fixed":
                    chunks.extend(fixed_size(page, strategy["chunk_size"], strategy["overlap"]))
                elif strategy["chunking"] == "paragraph" and strategy["overlap"] == 0:
                    chunks.extend(by_paragraph(page, strategy["chunk_size"]))
                else:
                    raise ValueError("Cấu hình chia chunk chưa được hỗ trợ")
            check_chunks(units, chunks, strategy["chunk_size"])
        elapsed = time.perf_counter() - started
        lengths = sorted(len(c.text) for c in chunks)
        if not lengths:
            raise ValueError("Không tạo được chunk")
        built[name] = chunks
        stats.append({
            "strategy": name, "chunking": settings["chunking"], "chunk_size": settings["chunk_size"],
            "overlap": settings["overlap"], "question_filter": strategy["question_filter"],
            "chunk_count": len(chunks), "min_chars": min(lengths), "mean_chars": round(statistics.mean(lengths), 1),
            "median_chars": statistics.median(lengths), "p95_chars": lengths[math.ceil(len(lengths) * .95) - 1],
            "max_chars": max(lengths), "total_chars": sum(lengths),
            "content_pages": len({(c.document_id, c.page) for c in chunks}),
            "chunking_seconds": round(elapsed, 6), "reuses": reuse or "", "python": platform.python_version(),
        })
    if built["C"] is not built["B"] or config["strategies"]["B"]["question_filter"] or not config["strategies"]["C"]["question_filter"]:
        raise ValueError("B/C phải chỉ khác cách áp dụng filter")
    for name in ["A", "B"]:
        path = ROOT / config["strategies"][name]["chunks_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(asdict(c), ensure_ascii=False) + "\n" for c in built[name]), encoding="utf-8")
    output = ROOT / "results/chunk_stats.csv"
    output.parent.mkdir(exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(stats[0]))
        writer.writeheader()
        writer.writerows(stats)
    print(json.dumps({"chunks": {key: len(value) for key, value in built.items()}, "source_and_metadata_checks": "passed"}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Không chuẩn bị được chunk: {error}", file=sys.stderr)
        raise SystemExit(1)
