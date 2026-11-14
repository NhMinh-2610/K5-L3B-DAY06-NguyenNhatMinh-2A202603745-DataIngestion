"""Embedding local; chỉ đọc model đã tải, không thay bằng vector giả khi lỗi."""
import hashlib
import importlib.metadata
import json
import os
from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class MyEmbedder:
    """Dùng cùng encoder và quy tắc tiền xử lý cho tài liệu/câu hỏi."""

    def __init__(self, model_name: str, revision: str, *, device: str = "cpu",
                 batch_size: int = 16, document_prefix: str = "passage: ",
                 query_prefix: str = "query: ", dimensions: int = 384) -> None:
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(4)
        self.model_name = model_name
        self.batch_size = batch_size
        self.document_prefix, self.query_prefix = document_prefix, query_prefix
        self.model = SentenceTransformer(model_name, revision=revision, device=device,
                                         local_files_only=True, trust_remote_code=False)
        self.model.float().eval()
        self.dimensions = self.model.get_embedding_dimension()
        if self.dimensions != dimensions:
            raise ValueError("Số chiều model khác cấu hình đã chốt")
        self.max_tokens = self.model.max_seq_length
        self.info = {
            "provider": "sentence-transformers-local", "model_name": model_name,
            "revision": revision, "dimensions": self.dimensions, "device": device,
            "dtype": "float32", "threads": 4, "batch_size": batch_size,
            "document_prefix": document_prefix, "query_prefix": query_prefix,
            "normalize_embeddings": True, "max_tokens": self.max_tokens,
            "libraries": {name: importlib.metadata.version(name) for name in
                          ["sentence-transformers", "transformers", "torch"]},
        }
        self.signature = hashlib.sha256(json.dumps(self.info, sort_keys=True).encode()).hexdigest()

    def token_lengths(self, texts: list[str], *, query: bool = False) -> list[int]:
        if not texts:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Nội dung embedding không được rỗng")
        prefix = self.query_prefix if query else self.document_prefix
        encoded = self.model.tokenizer([prefix + text for text in texts],
                                       truncation=False, padding=False)
        lengths = [len(ids) for ids in encoded["input_ids"]]
        if max(lengths) > self.max_tokens:
            raise ValueError(f"Nội dung vượt giới hạn {self.max_tokens} token; cần kiểm tra chunk")
        return lengths

    def _encode(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        if not texts:
            return []
        self.token_lengths(texts, query=query)
        prefix = self.query_prefix if query else self.document_prefix
        vectors = self.model.encode([prefix + text for text in texts], batch_size=self.batch_size,
                                    normalize_embeddings=True, convert_to_numpy=True,
                                    precision="float32", show_progress_bar=False)
        return vectors.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, question: str) -> list[float]:
        return self._encode([question], query=True)[0]
