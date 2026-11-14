"""Tạo embedding thật, lưu A/B/C vào pgvector và kiểm tra nạp lại/truy xuất."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "starter"))

from dotenv import load_dotenv
from prepare_chunks import check_chunks
from src.embeddings import MyEmbedder
from src.models import Chunk
from src.store import PgVectorStore


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    started = time.perf_counter()
    load_dotenv(ROOT / "starter/.env", override=True)
    config = read_json(ROOT / "starter/strategies.json")
    embedding = read_json(ROOT / "starter/embedding.json")
    if not embedding["local_files_only"] or not embedding["normalize_embeddings"]:
        raise ValueError("Lab dùng model local đã tải và embedding được chuẩn hóa")
    corpus_path = ROOT / config["corpus_path"]
    if sha256(corpus_path) != read_json(ROOT / "benchmark/split.json")["corpus_sha256"]:
        raise ValueError("Corpus khác bản đã chốt cho benchmark")
    units = read_jsonl(corpus_path)
    model_started = time.perf_counter()
    embedder = MyEmbedder(**{key: embedding[key] for key in
                            ["model_name", "revision", "device", "batch_size", "document_prefix", "query_prefix", "dimensions"]})
    model_load_seconds = time.perf_counter() - model_started
    store = PgVectorStore(os.environ.get("DATABASE_URL"), embedder.dimensions, embedder.signature)
    store.create_schema()
    material, measurements = {}, []
    for name, settings in config["strategies"].items():
        ingest_started = time.perf_counter()
        reuse = settings.get("reuse_chunks_from")
        if reuse:
            chunks, vectors, lengths = material[reuse]
            cache_hit, embedding_seconds = True, 0.0
        else:
            chunk_path = ROOT / settings["chunks_path"]
            chunks = [Chunk(**row) for row in read_jsonl(chunk_path)]
            check_chunks(units, chunks, settings["chunk_size"])
            texts = [chunk.text for chunk in chunks]
            lengths = embedder.token_lengths(texts)
            cache_path = ROOT / f"data/processed/vectors_{name}.json"
            key = {"model_signature": embedder.signature, "chunks_sha256": sha256(chunk_path)}
            cached = read_json(cache_path) if cache_path.exists() else {}
            cache_hit = all(cached.get(k) == v for k, v in key.items()) and len(cached.get("vectors", [])) == len(chunks)
            encode_started = time.perf_counter()
            if cache_hit:
                vectors = cached["vectors"]
            else:
                print(f"{name}: tạo embedding cho {len(chunks)} chunk", flush=True)
                vectors = embedder.embed_documents(texts)
                cache_path.write_text(json.dumps({**key, "vectors": vectors}, allow_nan=False), encoding="utf-8")
            embedding_seconds = time.perf_counter() - encode_started
        material[name] = (chunks, vectors, lengths)
        before = store.count(name)
        write_started = time.perf_counter()
        store.upsert(name, chunks, vectors)
        write_seconds = time.perf_counter() - write_started
        after = store.count(name)
        ingest_seconds = time.perf_counter() - ingest_started
        store.upsert(name, chunks, vectors)
        repeated = store.count(name)
        if after != len(chunks) or repeated != after:
            raise ValueError("Số dòng sau khi nạp lại không ổn định")
        measurements.append({
            "strategy": name, "chunk_count": len(chunks), "characters": sum(len(c.text) for c in chunks),
            "document_tokens_including_prefix": sum(lengths), "max_document_tokens": max(lengths),
            "cache_hit": cache_hit, "embedding_reused_from": reuse,
            "embedding_seconds": round(embedding_seconds, 4), "database_write_seconds": round(write_seconds, 4),
            "ingest_seconds": round(ingest_seconds, 4), "rows_before": before,
            "rows_after": after, "rows_after_repeat": repeated, "service_cost_usd": 0,
        })
        print(f"{name}: lưu {after} chunk; nạp lại vẫn {repeated} dòng", flush=True)
    persistence = PgVectorStore(store.database_url, embedder.dimensions, embedder.signature)
    if any(persistence.count(name) != len(value[0]) for name, value in material.items()):
        raise ValueError("Không đọc lại được dữ liệu qua kết nối mới")

    # Chỉ kiểm tra hoạt động; không dùng câu test hoặc chấm điểm benchmark.
    question = "Trong phần công nghệ liên quan đến AI, hãy tìm đoạn giới thiệu BERT."
    query_vector = embedder.embed_query(question)
    sample = {"question": question, "provided_filter": {"section": "1.2"}, "hits": {}}
    for name, settings in config["strategies"].items():
        filters = sample["provided_filter"] if settings["question_filter"] else None
        hits = store.search(name, query_vector, top_k=config["top_k"], filters=filters)
        if len(hits) != config["top_k"]:
            raise ValueError("Truy xuất thử không trả đủ top-3")
        if filters and any(hit["metadata"]["section"] != filters["section"] for hit in hits):
            raise ValueError("Kết quả không tuân thủ filter")
        sample["hits"][name] = hits
    report = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(), "model": embedder.info,
        "model_signature": embedder.signature, "model_load_seconds": round(model_load_seconds, 4),
        "vector_store": "PostgreSQL + pgvector", "metric": "cosine", "search_mode": "exact",
        "corpus_sha256": sha256(corpus_path), "strategies": measurements,
        "checks": {"reingest_no_duplicates": "passed", "read_from_new_connection": "passed", "metadata_filter": "passed"},
        "sample_search": sample, "benchmark_executed": False,
        "elapsed_seconds": round(time.perf_counter() - started, 4), "service_cost_usd": 0,
    }
    output = ROOT / "results/ingestion.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log_path = ROOT / "artifacts/experiment_log.csv"
    with log_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns, rows = reader.fieldnames, list(reader)
    for row in rows:
        row["vectorizer"] = embedder.model_name + "@" + embedding["revision"]
    with log_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"model": embedder.model_name, "dimensions": embedder.dimensions,
                      "stored": {name: len(value[0]) for name, value in material.items()}, "checks": "passed"}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Không hoàn tất embedding/lưu vector: {error}", file=sys.stderr)
        raise SystemExit(1)
