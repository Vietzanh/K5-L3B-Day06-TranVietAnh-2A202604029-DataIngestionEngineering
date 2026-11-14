"""Read and normalize source data while keeping every page traceable to the PDF."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from pypdf import PdfReader

from .models import DocumentPage

# Physical PDF page = printed Arabic page + 24 for this report.
PRINTED_PAGE_OFFSET = 24

# (first physical page, last physical page, section type, chapter, section label)
LAYOUT: list[tuple[int, int, str, str, str]] = [
    (1, 12, "front_matter", "", "Cover, copyright and contents"),
    (13, 16, "foreword", "", "Foreword"),
    (17, 18, "front_matter", "", "Acknowledgments"),
    (19, 22, "key_takeaways", "", "Key Takeaways"),
    (23, 26, "front_matter", "", "Abbreviations"),
    (
        27,
        74,
        "analysis",
        "1",
        "Chapter 1. Analysis of External Debt Stocks and Debt Flows as of End-2025",
    ),
    (75, 106, "analysis", "2", "Chapter 2. Debt Dynamics: Policy Implications"),
    (107, 134, "analysis", "3", "Chapter 3. Advancing Debt Transparency"),
    (135, 136, "profile_guide", "", "How to Read the Aggregate and Country Profiles"),
    (137, 263, "country_profile", "", ""),
    (264, 266, "appendix", "", "Appendix"),
    (267, 268, "appendix", "", "Data Sources"),
    (269, 270, "appendix", "", "Country Groups"),
    (271, 277, "appendix", "", "Glossary"),
    (278, 280, "back_matter", "", "Back cover"),
]

COUNTED_SECTION_TYPES = {"foreword", "key_takeaways", "analysis", "appendix"}
NOT_INDEXED_SECTION_TYPES = {"front_matter", "back_matter"}
MIN_TEXT_CHARS = 200

_ROMAN = re.compile(r"^[ivxlc]+$", re.IGNORECASE)
_DIGITS = re.compile(r"^\d{1,3}$")
_REPORT_TITLE = "INTERNATIONAL DEBT REPORT 2026"
_PROFILE_HEADING = re.compile(r"^[A-ZÀ-Ý][A-ZÀ-Ý ,.'’&()\-]{2,}$")
_INVISIBLE = re.compile(r"[\u00ad\u200b\ufeff]")
_SINGLE_QUOTES = re.compile(r"[‘’]")
_DOUBLE_QUOTES = re.compile(r"[“”]")
_DASHES = re.compile(r"[–—]")


def normalize_text(text: str) -> str:
    """Normalize Unicode and whitespace while preserving useful line structure."""
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE.sub("", text)
    text = text.replace("\t", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r" {2,}", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def match_key(text: str) -> str:
    """Comparison key resilient to PDF line wraps and typographic punctuation."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _SINGLE_QUOTES.sub("'", text)
    text = _DOUBLE_QUOTES.sub('"', text)
    text = _DASHES.sub("-", text)
    return re.sub(r"\s+", "", text)


def _strip_running_header(lines: list[str]) -> list[str]:
    """Remove the running report title and printed page number near page top."""
    for index, line in enumerate(lines[:3]):
        if _DIGITS.match(line) or _ROMAN.match(line):
            return lines[index + 1 :]
    if lines and lines[0] == _REPORT_TITLE:
        remaining = lines[1:]
        if remaining and (_DIGITS.match(remaining[0]) or _ROMAN.match(remaining[0])):
            remaining = remaining[1:]
        return remaining
    return list(lines)


def _layout_for(page: int) -> tuple[str, str, str]:
    for first, last, section_type, chapter, section in LAYOUT:
        if first <= page <= last:
            return section_type, chapter, section
    raise ValueError(f"PDF physical page {page} is outside the known report layout")


def _profile_name(lines: list[str]) -> str:
    """Find a country/profile heading in the first few extracted body lines."""
    for line in lines[:5]:
        if line.startswith(("Source:", "US$", "Note:")):
            continue
        if _PROFILE_HEADING.match(line) and not line.startswith(
            ("TOTAL", "PUBLIC", "MULTILATERAL", "BILATERAL")
        ):
            return line
    return ""


def printed_page_label(page: int) -> str:
    return "" if page <= PRINTED_PAGE_OFFSET else str(page - PRINTED_PAGE_OFFSET)


def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """Extract all physical pages, retaining extraction status and report metadata.

    The supplied International Debt Report PDF is born-digital, so this loader
    records extraction failures but deliberately does not silently invoke OCR.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    reader = PdfReader(str(path))
    pages: list[DocumentPage] = []
    for page_number, pdf_page in enumerate(reader.pages, start=1):
        try:
            raw = pdf_page.extract_text() or ""
            error = ""
        except Exception as exc:  # keep processing the remaining pages
            raw = ""
            error = f"{type(exc).__name__}: {exc}"

        normalized = normalize_text(raw)
        lines = [line for line in normalized.split("\n") if line]
        body_lines = _strip_running_header(lines)
        body = "\n".join(body_lines)

        section_type, chapter, section = _layout_for(page_number)
        if section_type == "country_profile":
            section = _profile_name(body_lines)
            if not section:
                error = error or "profile heading not found"

        if error and not body:
            status = "error"
        elif not body:
            status = "empty"
        elif len(body) < MIN_TEXT_CHARS:
            status = "low_text"
        else:
            status = "ok"

        is_reference_page = bool(body_lines) and body_lines[0].casefold() in {
            "notes",
            "references",
        }
        counted = (
            status == "ok"
            and section_type in COUNTED_SECTION_TYPES
            and not is_reference_page
        )
        indexed = (
            status in {"ok", "low_text"}
            and section_type not in NOT_INDEXED_SECTION_TYPES
        )

        pages.append(
            DocumentPage(
                document_id=document_id,
                source=source,
                page=page_number,
                text=body,
                metadata={
                    "printed_page": printed_page_label(page_number),
                    "section_type": section_type,
                    "chapter": chapter,
                    "section": section,
                    "extraction_status": status,
                    "extraction_error": error,
                    "char_count": len(body),
                    "counted_as_content": counted,
                    "indexed": indexed,
                    "document_type": "report",
                    "year": 2026,
                    "language": "en",
                },
            )
        )
    return pages
