"""Evidence-based retrieval evaluation and JSON-friendly trace aggregation."""

from __future__ import annotations

import unicodedata
import re
from typing import Any


def _match_key(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"[‘’]", "'", text)
    text = re.sub(r"[“”]", '"', text)
    text = re.sub(r"[–—]", "-", text)
    return re.sub(r"\s+", "", text)


def _gold_items(question: dict[str, Any]) -> list[dict[str, Any]]:
    items = [
        {
            "source_id": question.get("gold_source_id"),
            "page": question.get("gold_page"),
            "evidence_quotes": [question.get("evidence_quote", "")],
        }
    ]
    for alternative in question.get("alternative_gold", []):
        if isinstance(alternative, dict):
            items.append(
                {
                    "source_id": alternative.get(
                        "gold_source_id", question.get("gold_source_id")
                    ),
                    "page": alternative.get("gold_page"),
                    "evidence_quotes": alternative.get("evidence_quotes")
                    or [alternative.get("evidence_quote", "")],
                }
            )
    return items


def _hit_matches_gold(hit: dict[str, Any], gold: dict[str, Any]) -> bool:
    source_matches = hit.get("document_id") == gold.get("source_id")
    try:
        page_matches = int(hit.get("page")) == int(gold.get("page"))
    except (TypeError, ValueError):
        page_matches = False
    if not (source_matches and page_matches):
        return False

    content_key = _match_key(str(hit.get("text", "")))
    quotes = [quote for quote in gold.get("evidence_quotes", []) if quote]
    # Exact normalized quote matching is an auditable automatic proxy. A human
    # may later accept equivalent evidence and record that override separately.
    return any(_match_key(str(quote)) in content_key for quote in quotes)


def evaluate_query(
    question: dict[str, Any], hits: list[dict[str, Any]]
) -> dict[str, Any]:
    """Mark exact source/page/evidence hits and retain the complete top-k trace."""
    gold_items = _gold_items(question)
    hit_flags = [
        any(_hit_matches_gold(hit, gold) for gold in gold_items) for hit in hits
    ]
    gold_summary = [
        {
            "source_id": item.get("source_id"),
            "page": item.get("page"),
            "evidence_quotes": item.get("evidence_quotes", []),
        }
        for item in gold_items
    ]
    return {
        "id": question.get("id"),
        "split": question.get("split"),
        "type": question.get("type", "unspecified"),
        "question": question.get("question"),
        "expected_answer": question.get("expected_answer"),
        "filter": question.get("filter", {}),
        "gold": gold_summary,
        "hits": hits,
        "hit_flags": hit_flags,
        "hit_at_1": bool(hit_flags and hit_flags[0]),
        "evidence_hit_at_3": any(hit_flags[:3]),
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Hit@1 and Evidence Hit@3 by split, retaining numerator/denominator."""
    summary: dict[str, Any] = {}
    for split in ("dev", "test"):
        subset = [trace for trace in traces if trace.get("split") == split]
        total = len(subset)
        hit1 = sum(bool(trace.get("hit_at_1")) for trace in subset)
        hit3 = sum(bool(trace.get("evidence_hit_at_3")) for trace in subset)
        summary[split] = {
            "questions": total,
            "hit_at_1": {
                "numerator": hit1,
                "denominator": total,
                "rate": hit1 / total if total else None,
            },
            "evidence_hit_at_3": {
                "numerator": hit3,
                "denominator": total,
                "rate": hit3 / total if total else None,
            },
        }
    return summary
