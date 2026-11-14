"""Fixed-size and paragraph-aware chunking with stable source traceability."""

from __future__ import annotations

import re

from .models import Chunk, DocumentPage

_BULLET = re.compile(r"^(?:[•●▪◦*-]|\d+[.)])\s+")
_SENTENCE_END = re.compile(r"[.!?][\"'’”)]?$")


def _chunk(
    page: DocumentPage, text: str, start: int, end: int, method: str, ordinal: int
) -> Chunk:
    metadata = dict(page.metadata)
    metadata.update(
        {
            "chunking": method,
            "chunk_start": start,
            "chunk_end": end,
            "chunk_ordinal": ordinal,
        }
    )
    return Chunk(
        chunk_id=f"{method}-{page.document_id}-p{page.page:03d}-{start:07d}-{end:07d}",
        document_id=page.document_id,
        source=page.source,
        page=page.page,
        text=text,
        metadata=metadata,
    )


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Split a page into overlapping character windows."""
    if size <= 0:
        raise ValueError("size must be greater than zero")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be >= 0 and smaller than size")
    text = page.text.strip()
    if not text:
        return []

    step = size - overlap
    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        segment = text[start:end].strip()
        if segment:
            # Store offsets against the normalized page text. Leading/trailing
            # whitespace trimming is intentionally not used to change the bounds.
            chunks.append(_chunk(page, segment, start, end, "fixed", len(chunks)))
        if end == len(text):
            break
        start += step
    return chunks


def _looks_like_heading(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 120 or _BULLET.match(line):
        return False
    if _SENTENCE_END.search(line) or len(line.split()) > 14:
        return False
    if line.startswith(("Figure ", "Box ", "Table ", "Sources:", "Source:", "Note:")):
        return True
    words = [word for word in re.findall(r"[A-Za-zÀ-ÿ]+", line) if len(word) > 1]
    if not words:
        return False
    title_case_ratio = sum(word[0].isupper() for word in words) / len(words)
    upper_ratio = sum(word.isupper() for word in words) / len(words)
    return title_case_ratio >= 0.70 or upper_ratio >= 0.70


def _paragraphs(text: str) -> list[str]:
    """Reconstruct paragraphs from PDF line wraps using punctuation and headings."""
    result: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            paragraph = " ".join(part.strip() for part in current if part.strip())
            paragraph = re.sub(r"\s+", " ", paragraph).strip()
            if paragraph:
                result.append(paragraph)
            current.clear()

    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            flush()
            continue
        if current and (
            _BULLET.match(line)
            or _looks_like_heading(line)
            or _SENTENCE_END.search(current[-1])
        ):
            flush()
        current.append(line)
        if _BULLET.match(line) and _SENTENCE_END.search(line):
            flush()
    flush()
    return result


def _split_long_paragraph(paragraph: str, max_size: int) -> list[str]:
    """Split an oversized paragraph on sentence boundaries, then safe word cuts."""
    if len(paragraph) <= max_size:
        return [paragraph]

    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = f"{current} {sentence}".strip()
        if len(candidate) <= max_size:
            current = candidate
            continue
        if current:
            pieces.append(current)
            current = ""
        if len(sentence) <= max_size:
            current = sentence
        else:
            remaining = sentence
            while len(remaining) > max_size:
                cut = remaining.rfind(" ", 0, max_size + 1)
                if cut < max_size // 2:
                    cut = max_size
                pieces.append(remaining[:cut].strip())
                remaining = remaining[cut:].strip()
            current = remaining
    if current:
        pieces.append(current)
    return pieces


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Group reconstructed paragraphs up to max_size; split very long paragraphs."""
    if max_size <= 0:
        raise ValueError("max_size must be greater than zero")
    text = page.text.strip()
    if not text:
        return []

    paragraphs = _paragraphs(text)
    expanded: list[str] = []
    for paragraph in paragraphs:
        expanded.extend(_split_long_paragraph(paragraph, max_size))

    chunks: list[Chunk] = []
    current_parts: list[str] = []
    current_length = 0
    current_start = 0
    cursor = 0

    def flush() -> None:
        nonlocal current_parts, current_length, current_start
        if not current_parts:
            return
        chunk_text = "\n\n".join(current_parts).strip()
        chunks.append(
            _chunk(
                page,
                chunk_text,
                current_start,
                current_start + len(chunk_text),
                "paragraph",
                len(chunks),
            )
        )
        current_parts = []
        current_length = 0

    for paragraph in expanded:
        addition = len(paragraph) + (2 if current_parts else 0)
        if current_parts and current_length + addition > max_size:
            flush()
            current_start = cursor
        elif not current_parts:
            current_start = cursor
        current_parts.append(paragraph)
        current_length += addition
        cursor += len(paragraph) + 2
    flush()
    return chunks
