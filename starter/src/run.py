"""Orchestrate the Day 06 ingestion, three retrieval strategies and benchmark."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import MyEmbedder
from .evaluation import evaluate_query, summarize
from .ingestion import load_pdf, match_key

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"
DOCUMENT_ID = "wb-idr-2026"
FILTER_FIELDS = {
    "chapter",
    "section",
    "section_type",
    "printed_page",
    "document_type",
    "year",
    "language",
}


def _load_inputs() -> tuple[Path, list[dict[str, Any]], list[Any]]:
    pdf_candidates = sorted(path for path in DATA_DIR.glob("*.pdf") if path.is_file())
    if len(pdf_candidates) != 1:
        raise RuntimeError(
            f"Expected exactly one PDF in {DATA_DIR}, found {len(pdf_candidates)}. "
            "Keep one corpus PDF in starter/data or adapt run.py for multiple sources."
        )
    pdf_path = pdf_candidates[0]
    benchmark_path = DATA_DIR / "benchmark.json"
    if not benchmark_path.exists():
        raise FileNotFoundError(f"Benchmark file not found: {benchmark_path}")
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    questions = benchmark.get("questions")
    if not isinstance(questions, list):
        raise ValueError("benchmark.json must contain a 'questions' array")
    source = pdf_path.relative_to(ROOT).as_posix()
    pages = load_pdf(pdf_path, DOCUMENT_ID, source)
    return pdf_path, questions, pages


def _validate_benchmark(
    questions: list[dict[str, Any]], pages: list[Any]
) -> dict[str, Any]:
    if len(questions) < 20:
        raise ValueError(
            f"Benchmark needs at least 20 questions; found {len(questions)}"
        )
    ids = [q.get("id") for q in questions]
    if len(ids) != len(set(ids)) or any(not qid for qid in ids):
        raise ValueError("Every benchmark question must have a unique, non-empty id")
    split_counts = Counter(q.get("split") for q in questions)
    if split_counts.get("dev", 0) < 15 or split_counts.get("test", 0) < 5:
        raise ValueError("Benchmark must contain at least 15 dev and 5 test questions")

    page_lookup = {(page.document_id, page.page): page for page in pages}
    filter_questions = 0
    for question in questions:
        required = (
            "id",
            "split",
            "question",
            "expected_answer",
            "gold_source_id",
            "gold_page",
            "evidence_quote",
        )
        missing = [field for field in required if question.get(field) in (None, "")]
        if missing:
            raise ValueError(
                f"Question {question.get('id')} is missing: {', '.join(missing)}"
            )
        if question["split"] not in {"dev", "test"}:
            raise ValueError(
                f"Question {question['id']} has unsupported split {question['split']!r}"
            )

        page = page_lookup.get((question["gold_source_id"], int(question["gold_page"])))
        if page is None:
            raise ValueError(
                f"Question {question['id']} points to unknown page "
                f"{question['gold_source_id']}:{question['gold_page']}"
            )
        quote_key = match_key(question["evidence_quote"])
        if not quote_key or quote_key not in match_key(page.text):
            raise ValueError(
                f"Evidence for {question['id']} was not found on physical PDF page {page.page}. "
                "Review the quote against the source page before benchmarking."
            )

        filters = question.get("filter") or {}
        if not isinstance(filters, dict):
            raise ValueError(f"Question {question['id']} filter must be a JSON object")
        if filters:
            filter_questions += 1
        for key, value in filters.items():
            if key not in FILTER_FIELDS:
                raise ValueError(
                    f"Question {question['id']} uses unsupported filter field {key!r}"
                )
            actual = page.metadata.get(key)
            if actual in (None, "") or str(actual) != str(value):
                raise ValueError(
                    f"Question {question['id']} filter {key}={value!r} does not match "
                    f"gold-page metadata {actual!r}"
                )

    test_filter_count = sum(
        1 for q in questions if q.get("split") == "test" and q.get("filter")
    )
    if filter_questions < 3 or test_filter_count < 1:
        raise ValueError(
            "Need at least 3 metadata-filter questions, including at least 1 test question"
        )
    return {
        "total": len(questions),
        "splits": dict(split_counts),
        "filter_questions": filter_questions,
    }


def _chunk_stats(chunks: list[Any]) -> dict[str, Any]:
    lengths = [len(chunk.text) for chunk in chunks]
    return {
        "chunks": len(chunks),
        "total_characters": sum(lengths),
        "min_characters": min(lengths) if lengths else 0,
        "max_characters": max(lengths) if lengths else 0,
        "mean_characters": round(statistics.mean(lengths), 2) if lengths else 0,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _prepare_manual_review(
    pages: list[Any],
    strategies: dict[str, list[Any]],
    traces_by_strategy: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    content_pages = [
        page for page in pages if page.metadata.get("counted_as_content") and page.text
    ]
    if content_pages:
        count = min(10, len(content_pages))
        indices = sorted(
            {
                round(i * (len(content_pages) - 1) / max(count - 1, 1))
                for i in range(count)
            }
        )
        selected_pages = [content_pages[index] for index in indices]
    else:
        selected_pages = []

    coherence: list[dict[str, Any]] = []
    for page in selected_pages:
        page_chunks = {
            name: [
                chunk
                for chunk in chunks
                if chunk.document_id == page.document_id and chunk.page == page.page
            ]
            for name, chunks in strategies.items()
        }
        midpoint = len(page.text) // 2
        anchor_width = min(60, max(12, len(page.text) // 4))
        candidate_positions = list(
            range(0, max(1, len(page.text) - anchor_width + 1), 5)
        )
        candidate_positions.sort(
            key=lambda value: abs((value + anchor_width // 2) - midpoint)
        )
        position = midpoint
        matching_by_strategy: dict[str, Any] = {}
        for candidate in candidate_positions:
            anchor = page.text[candidate : candidate + anchor_width]
            anchor_key = match_key(anchor)
            candidate_matches = {
                name: next(
                    (
                        chunk
                        for chunk in chunks
                        if anchor_key and anchor_key in match_key(chunk.text)
                    ),
                    None,
                )
                for name, chunks in page_chunks.items()
            }
            if candidate_matches and all(candidate_matches.values()):
                position = candidate + len(anchor) // 2
                matching_by_strategy = candidate_matches
                break
        if not matching_by_strategy:
            anchor = page.text[
                max(0, midpoint - anchor_width // 2) : midpoint + anchor_width // 2
            ]
            anchor_key = match_key(anchor)
            matching_by_strategy = {
                name: next(
                    (
                        chunk
                        for chunk in chunks
                        if anchor_key and anchor_key in match_key(chunk.text)
                    ),
                    None,
                )
                for name, chunks in page_chunks.items()
            }

        by_strategy: dict[str, Any] = {}
        for name in strategies:
            chosen = matching_by_strategy.get(name)
            by_strategy[name] = (
                {
                    "chunk_id": chosen.chunk_id,
                    "text": chosen.text,
                    "human_score_0_1_2": None,
                    "reviewer_reason": "",
                }
                if chosen
                else None
            )
        coherence.append(
            {
                "document_id": page.document_id,
                "source": page.source,
                "physical_page": page.page,
                "printed_page": page.metadata.get("printed_page"),
                "source_position_character": position,
                "source_excerpt": page.text[max(0, position - 150) : position + 150],
                "strategies": by_strategy,
            }
        )

    grounding: dict[str, list[dict[str, Any]]] = {}
    for name, traces in traces_by_strategy.items():
        grounding[name] = []
        for trace in traces:
            if trace.get("split") != "test":
                continue
            grounding[name].append(
                {
                    "question_id": trace.get("id"),
                    "question": trace.get("question"),
                    "top3": trace.get("hits", []),
                    "human_grounding_score_0_1_2": None,
                    "reviewer_reason": "",
                }
            )
    return {
        "instructions": "Fill human_score_0_1_2 / human_grounding_score_0_1_2 and reviewer_reason after inspecting the evidence. Do not treat automatic quote match as a human quality score.",
        "chunk_coherence": coherence,
        "grounding_quality": grounding,
    }


def _metadata_filter_summary(traces: list[dict[str, Any]]) -> dict[str, Any]:
    filtered = [trace for trace in traces if trace.get("filter")]
    compliant_queries = 0
    hit_records = 0
    compliant_records = 0
    for trace in filtered:
        filters = trace.get("filter") or {}
        hits = trace.get("hits", [])
        if hits and all(
            all(
                str(hit.get("metadata", {}).get(key, "")) == str(value)
                for key, value in filters.items()
            )
            for hit in hits
        ):
            compliant_queries += 1
        for hit in hits:
            hit_records += 1
            if all(
                str(hit.get("metadata", {}).get(key, "")) == str(value)
                for key, value in filters.items()
            ):
                compliant_records += 1
    return {
        "filtered_questions": len(filtered),
        "fully_compliant_top3_questions": compliant_queries,
        "question_compliance_rate": (
            compliant_queries / len(filtered) if filtered else None
        ),
        "compliant_hit_records": compliant_records,
        "hit_records_checked": hit_records,
        "hit_record_compliance_rate": (
            compliant_records / hit_records if hit_records else None
        ),
    }


def _metadata_audit(
    pages: list[Any], traces_by_strategy: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    page_lookup = {(page.document_id, page.page): page for page in pages}
    required_metadata = (
        "chapter",
        "section_type",
        "printed_page",
        "document_type",
        "year",
        "language",
    )
    audits: dict[str, list[dict[str, Any]]] = {}
    for strategy, traces in traces_by_strategy.items():
        audits[strategy] = []
        for trace in traces:
            if trace.get("split") != "test":
                continue
            for rank, hit in enumerate(trace.get("hits", []), start=1):
                source_page = page_lookup.get((hit.get("document_id"), hit.get("page")))
                metadata = hit.get("metadata") or {}
                expected_metadata = source_page.metadata if source_page else {}
                compared_fields = {
                    "document_id": (
                        hit.get("document_id"),
                        source_page.document_id if source_page else None,
                    ),
                    "source": (
                        hit.get("source"),
                        source_page.source if source_page else None,
                    ),
                    "page": (
                        hit.get("page"),
                        source_page.page if source_page else None,
                    ),
                }
                compared_fields.update(
                    {
                        key: (metadata.get(key), expected_metadata.get(key))
                        for key in required_metadata
                    }
                )
                missing_fields = [
                    key
                    for key, (actual, _expected) in compared_fields.items()
                    if actual in (None, "")
                ]
                mismatched_fields = [
                    key
                    for key, (actual, expected) in compared_fields.items()
                    if expected is not None and str(actual) != str(expected)
                ]
                audits[strategy].append(
                    {
                        "question_id": trace.get("id"),
                        "rank": rank,
                        "chunk_id": hit.get("chunk_id"),
                        "checked_fields": {
                            key: {"actual": actual, "source_page": expected}
                            for key, (actual, expected) in compared_fields.items()
                        },
                        "missing_fields": missing_fields,
                        "mismatched_fields": mismatched_fields,
                        "automatic_metadata_complete_and_consistent": not missing_fields
                        and not mismatched_fields,
                        "human_checked": False,
                        "reviewer_reason": "",
                    }
                )
    return audits


def _run(check_only: bool = False) -> None:
    run_started = time.perf_counter()
    load_dotenv(ROOT / ".env")
    extraction_started = time.perf_counter()
    pdf_path, questions, pages = _load_inputs()
    pdf_extraction_seconds = round(time.perf_counter() - extraction_started, 3)
    benchmark_stats = _validate_benchmark(questions, pages)
    counted_pages = [page for page in pages if page.metadata.get("counted_as_content")]
    indexed_pages = [
        page for page in pages if page.metadata.get("indexed") and page.text
    ]
    if len(counted_pages) < 30:
        raise RuntimeError(
            f"Corpus has only {len(counted_pages)} counted content pages; lab requires at least 30."
        )

    status_counts = Counter(page.metadata.get("extraction_status") for page in pages)
    page_log = [
        {
            "document_id": page.document_id,
            "source": page.source,
            "physical_page": page.page,
            "printed_page": page.metadata.get("printed_page"),
            "section_type": page.metadata.get("section_type"),
            "chapter": page.metadata.get("chapter"),
            "char_count": page.metadata.get("char_count"),
            "extraction_status": page.metadata.get("extraction_status"),
            "extraction_error": page.metadata.get("extraction_error"),
            "counted_as_content": page.metadata.get("counted_as_content"),
            "indexed": page.metadata.get("indexed"),
        }
        for page in pages
    ]
    source_manifest = {
        "source_id": DOCUMENT_ID,
        "title": "International Debt Report 2026",
        "author": "The World Bank Group",
        "source_path_or_url": pdf_path.relative_to(ROOT).as_posix(),
        "license_or_permission": "Not independently verified by this script. Check the copyright/licence notice in the PDF and applicable World Bank reuse terms before redistributing the file.",
        "accessed_at": datetime.now(timezone.utc).isoformat(),
        "physical_page_count": len(pages),
        "counted_content_page_count": len(counted_pages),
        "counted_content_physical_pages": [page.page for page in counted_pages],
        "indexed_page_count": len(indexed_pages),
        "page_numbering": "gold_page and page metadata use 1-based physical PDF page numbers; printed_page is stored separately.",
        "extraction_status_counts": dict(status_counts),
    }

    print(
        f"PDF: {pdf_path.name} | pages={len(pages)} | counted content={len(counted_pages)} | indexed={len(indexed_pages)}"
    )
    print(f"Benchmark: {benchmark_stats}")
    _write_json(RESULTS_DIR / "source_manifest.json", source_manifest)
    _write_json(RESULTS_DIR / "page_extraction_log.json", page_log)

    if check_only:
        print(
            "CHECK ONLY: PDF extraction, benchmark evidence, split counts and filters are valid."
        )
        return

    chunking_started = time.perf_counter()
    chunks_a = [
        chunk
        for page in indexed_pages
        for chunk in fixed_size(page, size=500, overlap=80)
    ]
    chunks_b = [
        chunk for page in indexed_pages for chunk in by_paragraph(page, max_size=900)
    ]
    chunking_seconds = round(time.perf_counter() - chunking_started, 3)
    chunks_c = chunks_b  # Strategy C changes retrieval filtering only, not chunking.
    strategies = {"A": chunks_a, "B": chunks_b, "C": chunks_c}

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is missing. Configure starter/.env and start PostgreSQL + pgvector."
        )
    from .store import PgVectorStore

    embedder = MyEmbedder()
    store = PgVectorStore(database_url, embedder.dimensions)
    schema_started = time.perf_counter()
    store.create_schema()
    schema_setup_seconds = round(time.perf_counter() - schema_started, 3)

    timings: dict[str, Any] = {
        "pdf_extraction_seconds": pdf_extraction_seconds,
        "chunking_seconds": chunking_seconds,
        "database_schema_setup_seconds": schema_setup_seconds,
        "embedding_seconds": {},
        "upsert_seconds": {},
    }
    embedded: dict[str, list[list[float]]] = {}
    for strategy_name in ("A", "B"):
        chunks = strategies[strategy_name]
        print(
            f"Embedding strategy {strategy_name}: {len(chunks)} chunks with {embedder.model_name} ..."
        )
        started = time.perf_counter()
        vectors = embedder.embed_documents([chunk.text for chunk in chunks])
        timings["embedding_seconds"][strategy_name] = round(
            time.perf_counter() - started, 3
        )
        embedded[strategy_name] = vectors
        started = time.perf_counter()
        store.upsert(strategy_name, chunks, vectors)
        timings["upsert_seconds"][strategy_name] = round(
            time.perf_counter() - started, 3
        )

    # C is intentionally identical to B at the data/index level; only queries
    # carrying a validated filter are narrowed at retrieval time.
    started = time.perf_counter()
    store.upsert("C", chunks_c, embedded["B"])
    timings["upsert_seconds"]["C"] = round(time.perf_counter() - started, 3)
    embedded["C"] = embedded["B"]

    print(f"Embedding {len(questions)} benchmark queries ...")
    query_embedding_started = time.perf_counter()
    query_texts = [question["question"] for question in questions]
    if hasattr(embedder, "embed_queries"):
        query_vectors = embedder.embed_queries(query_texts)
    else:
        query_vectors = [embedder.embed_query(question) for question in query_texts]
    timings["query_embedding_seconds"] = round(
        time.perf_counter() - query_embedding_started, 3
    )
    query_vector_by_id = {
        question["id"]: vector for question, vector in zip(questions, query_vectors)
    }

    traces_by_strategy: dict[str, list[dict[str, Any]]] = {}
    summaries: dict[str, Any] = {}
    for strategy_name in ("A", "B", "C"):
        traces: list[dict[str, Any]] = []
        for question in questions:
            filters = (question.get("filter") or {}) if strategy_name == "C" else None
            hits = store.search(
                strategy_name,
                query_vector_by_id[question["id"]],
                top_k=3,
                filters=filters,
            )
            trace = evaluate_query(question, hits)
            trace["strategy"] = strategy_name
            trace["query_filter_applied"] = filters or {}
            traces.append(trace)
        traces_by_strategy[strategy_name] = traces
        summaries[strategy_name] = summarize(traces)
        _write_json(RESULTS_DIR / f"traces_{strategy_name}.json", traces)
        print(f"Strategy {strategy_name} complete: {summaries[strategy_name]}")

    timings["total_pipeline_seconds"] = round(time.perf_counter() - run_started, 3)
    run_summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "document_id": DOCUMENT_ID,
        "source": pdf_path.relative_to(ROOT).as_posix(),
        "embedding_provider": embedder.provider,
        "embedding_model": embedder.model_name,
        "embedding_dimensions": embedder.dimensions,
        "vector_store": "PostgreSQL + pgvector",
        "distance_metric": "cosine distance (exact search; no approximate vector index created)",
        "benchmark": benchmark_stats,
        "strategies": {
            "A": {
                "chunking": "fixed-size",
                "size_characters": 500,
                "overlap_characters": 80,
                **_chunk_stats(chunks_a),
            },
            "B": {
                "chunking": "paragraph-aware",
                "max_size_characters": 900,
                **_chunk_stats(chunks_b),
            },
            "C": {
                "chunking": "same as B",
                "retrieval_filter": "apply question.filter when present",
                **_chunk_stats(chunks_c),
            },
        },
        "timings_seconds": timings,
        "metrics": summaries,
        "metadata_filter_compliance": {
            name: (
                _metadata_filter_summary(traces)
                if name == "C"
                else {
                    "applied": False,
                    "note": "Baseline strategy; filters are intentionally not applied.",
                }
            )
            for name, traces in traces_by_strategy.items()
        },
        "embedding_usage": {
            "api_requests": embedder.request_count,
            "prompt_tokens": embedder.prompt_tokens,
            "total_tokens": embedder.total_tokens,
            "cost_usd": None,
            "cost_note": "No authoritative cost was returned in the embedding response; check provider billing dashboard.",
        },
        "notes": [
            "Automatic Evidence Hit@3 requires exact normalized evidence text in a gold source/page chunk.",
            "A and B do not apply question metadata filters; C applies them only when the benchmark question supplies a filter.",
            "Chunk coherence and grounding quality require manual labels in manual_review.json.",
            "No model answer generation is evaluated; grounding measures retrieved evidence only.",
        ],
    }
    _write_json(RESULTS_DIR / "run_summary.json", run_summary)
    manual_review = _prepare_manual_review(pages, strategies, traces_by_strategy)
    manual_review["metadata_audit_top3_test"] = _metadata_audit(
        pages, traces_by_strategy
    )
    _write_json(RESULTS_DIR / "manual_review.json", manual_review)
    print(f"Done. Results saved under: {RESULTS_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Day 06 data ingestion and retrieval benchmark"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Extract PDF pages and validate the benchmark without calling an embedding API or database.",
    )
    args = parser.parse_args()
    try:
        _run(check_only=args.check_only)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
