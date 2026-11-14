"""Extract physical PDF pages while preserving paragraph and source boundaries."""
import logging
from pathlib import Path
import re
import unicodedata

from pypdf import PdfReader

from .models import DocumentPage

NORMALIZATION_VERSION = "nfkc-layout-whitespace-v1"
LOGGER = logging.getLogger(__name__)


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """Keep every physical page (one based), including empty or failed pages.

    Layout extraction retains blank lines between paragraphs and avoids spurious
    spaces around ligatures seen with plain extraction on the current corpus.
    Empty/error pages are explicit records, never silently removed or OCR'd.
    Source-specific running headers and page eligibility are handled separately.
    """
    reader = PdfReader(path)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError(f"PDF requires a password: {path}")

    pages = []
    for number, page in enumerate(reader.pages, start=1):
        metadata = {"extraction_backend": "pypdf-layout", "ocr_applied": False}
        try:
            LOGGER.info("Extracting document=%s physical_page=%s", document_id, number)
            raw_text = page.extract_text(extraction_mode="layout") or ""
            text = normalize_text(raw_text)
            metadata.update(
                extracted_char_count=len(raw_text),
                extraction_status="ok" if text else "empty",
            )
            if not text:
                LOGGER.warning("Empty text: document=%s page=%s", document_id, number)
        except Exception as exc:
            LOGGER.exception("Extraction failed: document=%s page=%s", document_id, number)
            text = ""
            metadata.update(extracted_char_count=0, extraction_status="error", error=str(exc))
        pages.append(DocumentPage(document_id, source, number, text, metadata))
    return pages


def normalize_text(text: str) -> str:
    """Expand Unicode ligatures; retain line/paragraph breaks and punctuation.

    Do not guess missing text, merge pages, remove captions or automatically join
    hyphenated words: those transformations need separate review.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00ad", "").replace("\u200b", "").replace("\ufeff", "")
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
