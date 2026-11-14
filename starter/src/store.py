"""Lưu snapshot theo cấu hình và tìm kiếm cosine chính xác trong pgvector."""
import json
import math
import re
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .models import Chunk


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int, model_signature: str) -> None:
        if not database_url or not model_signature or type(dimensions) is not int or not 1 <= dimensions <= 16000:
            raise ValueError("Thiếu kết nối, phiên bản model hoặc số chiều hợp lệ")
        self.database_url, self.dimensions = database_url, dimensions
        self.model_signature = model_signature

    def _connect(self):
        return psycopg.connect(self.database_url, connect_timeout=5, row_factory=dict_row)

    @staticmethod
    def _strategy(strategy: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", strategy):
            raise ValueError("Tên cấu hình không hợp lệ")

    def _vector(self, values: list[float]) -> str:
        if len(values) != self.dimensions:
            raise ValueError("Vector không đúng số chiều")
        numbers = [float(value) for value in values]
        if not all(math.isfinite(value) for value in numbers) or not any(numbers):
            raise ValueError("Vector phải hữu hạn và khác vector không")
        return json.dumps(numbers, allow_nan=False)

    def _check_space(self, cursor, strategy: str) -> None:
        cursor.execute("SELECT model_signature,dimensions FROM lab_vector_spaces WHERE strategy=%s", (strategy,))
        space = cursor.fetchone()
        if not space or (space["model_signature"], space["dimensions"]) != (self.model_signature, self.dimensions):
            raise ValueError("Cấu hình chưa được nạp hoặc đang dùng model khác")

    def create_schema(self) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname='vector'")
            if not cursor.fetchone():
                raise ValueError("Database chưa bật pgvector; kiểm tra setup trước")
            cursor.execute("""CREATE TABLE IF NOT EXISTS lab_vector_spaces (
                strategy text PRIMARY KEY, model_signature text NOT NULL, dimensions integer NOT NULL
            )""")
            cursor.execute(f"""CREATE TABLE IF NOT EXISTS lab_chunks (
                strategy text NOT NULL REFERENCES lab_vector_spaces(strategy),
                chunk_id text NOT NULL, document_id text NOT NULL, source text NOT NULL,
                page integer NOT NULL CHECK (page>0), text text NOT NULL,
                metadata jsonb NOT NULL, embedding vector({self.dimensions}) NOT NULL,
                PRIMARY KEY (strategy,chunk_id)
            )""")
            cursor.execute("""SELECT format_type(atttypid,atttypmod) AS column_type
                FROM pg_attribute WHERE attrelid='lab_chunks'::regclass AND attname='embedding'""")
            if cursor.fetchone()["column_type"] != f"vector({self.dimensions})":
                raise ValueError("Bảng hiện tại dùng số chiều khác; không tự thay dữ liệu")

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Nhận TOÀN BỘ snapshot của một cấu hình, ghi và bỏ chunk cũ trong một transaction.

        Chạy lại giữ nguyên số dòng. Tài liệu sửa/xóa được phản ánh bằng snapshot
        mới; từ chối snapshot rỗng để tránh xóa dữ liệu do lỗi đọc corpus.
        """
        self._strategy(strategy)
        if not chunks or len(chunks) != len(vectors):
            raise ValueError("Cần snapshot đầy đủ và một vector cho mỗi chunk")
        ids = [chunk.chunk_id for chunk in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("Snapshot có ID chunk bị trùng")
        rows = []
        for chunk, vector in zip(chunks, vectors):
            if not chunk.text.strip() or not chunk.document_id or not chunk.source or chunk.page < 1 or not chunk.metadata.get("section"):
                raise ValueError("Chunk thiếu nội dung hoặc metadata truy nguồn")
            rows.append((strategy, chunk.chunk_id, chunk.document_id, chunk.source,
                         chunk.page, chunk.text, Jsonb(chunk.metadata), self._vector(vector)))
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("""INSERT INTO lab_vector_spaces VALUES (%s,%s,%s)
                ON CONFLICT (strategy) DO NOTHING""", (strategy, self.model_signature, self.dimensions))
            cursor.execute("SELECT strategy FROM lab_vector_spaces WHERE strategy=%s FOR UPDATE", (strategy,))
            self._check_space(cursor, strategy)
            cursor.executemany("""INSERT INTO lab_chunks
                (strategy,chunk_id,document_id,source,page,text,metadata,embedding)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::vector)
                ON CONFLICT (strategy,chunk_id) DO UPDATE SET
                document_id=excluded.document_id,source=excluded.source,page=excluded.page,
                text=excluded.text,metadata=excluded.metadata,embedding=excluded.embedding""", rows)
            cursor.execute("DELETE FROM lab_chunks WHERE strategy=%s AND NOT (chunk_id=ANY(%s))", (strategy, ids))

    def count(self, strategy: str) -> int:
        self._strategy(strategy)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) AS n FROM lab_chunks WHERE strategy=%s", (strategy,))
            return cursor.fetchone()["n"]

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """WHERE lọc metadata trước ORDER BY; không dùng chỉ mục approximate."""
        self._strategy(strategy)
        filters = {} if filters is None else filters
        if type(top_k) is not int or top_k < 1 or not isinstance(filters, dict) or set(filters) - {"section", "language", "year", "document_type"}:
            raise ValueError("top_k hoặc trường filter không hợp lệ")
        if any(value is None or isinstance(value, (dict, list)) for value in filters.values()):
            raise ValueError("Filter phải có giá trị đơn")
        vector = self._vector(query_vector)
        with self._connect() as connection, connection.cursor() as cursor:
            self._check_space(cursor, strategy)
            cursor.execute("""SELECT chunk_id,document_id,source,page,text,metadata,
                embedding <=> %s::vector AS distance FROM lab_chunks
                WHERE strategy=%s AND metadata @> %s
                ORDER BY distance,chunk_id LIMIT %s""", (vector, strategy, Jsonb(filters), top_k))
            hits = cursor.fetchall()
        for hit in hits:
            hit["score"] = 1.0 - hit.pop("distance")
            hit["metadata"] = {**hit["metadata"], "document_id": hit["document_id"],
                               "source": hit["source"], "page": hit["page"]}
        return hits
