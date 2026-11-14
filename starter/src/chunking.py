"""Chia theo số ký tự hoặc đoạn văn, giữ vị trí trong trang nguồn."""
import hashlib
import re

from .models import Chunk, DocumentPage


def _chunk(page: DocumentPage, start: int, end: int, method: str,
           size: int, overlap: int = 0) -> Chunk:
    text = page.text[start:end]
    identity = f"{page.document_id}|{page.page}|{page.metadata.get('unit_id', '')}|{method}|{size}|{overlap}|{start}|{end}|{text}"
    chunk_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    base = page.metadata.get("page_char_start", 0)
    metadata = {
        **page.metadata, "chunking": method, "chunk_size": size, "overlap": overlap,
        "unit_char_start": start, "unit_char_end": end,
        "page_char_start": base + start, "page_char_end": base + end,
    }
    return Chunk(chunk_id, page.document_id, page.source, page.page, text, metadata)


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Cửa sổ cố định; dừng khi đã chạm cuối đơn vị nguồn."""
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Cần size > 0 và 0 <= overlap < size")
    chunks = []
    for start in range(0, len(page.text), size - overlap):
        end = min(start + size, len(page.text))
        if page.text[start:end].strip():
            chunks.append(_chunk(page, start, end, "fixed", size, overlap))
        if end == len(page.text):
            break
    return chunks


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Gộp các đoạn vừa giới hạn; đoạn quá dài được tách ở khoảng trắng.

    Một từ dài hơn giới hạn buộc phải cắt theo ký tự. Mọi khoảng ký tự đều trỏ
    về text gốc, nên có thể kiểm chứng evidence và metadata sau khi chia.
    """
    if max_size <= 0:
        raise ValueError("max_size phải lớn hơn 0")
    text, parts, start = page.text, [], 0
    boundaries = [(m.start(), m.end()) for m in re.finditer(r"\n{2,}", text)]
    for end, next_start in boundaries + [(len(text), len(text))]:
        left, right = start, end
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        while right - left > max_size:
            limit = left + max_size
            cut = max(text.rfind(" ", left, limit + 1), text.rfind("\n", left, limit + 1))
            if cut <= left:
                cut = limit
            parts.append((left, cut))
            left = cut
            while left < right and text[left].isspace():
                left += 1
        if left < right:
            parts.append((left, right))
        start = next_start
    groups = []
    for left, right in parts:
        if groups and right - groups[-1][0] <= max_size:
            groups[-1] = (groups[-1][0], right)
        else:
            groups.append((left, right))
    return [_chunk(page, left, right, "paragraph", max_size) for left, right in groups]
