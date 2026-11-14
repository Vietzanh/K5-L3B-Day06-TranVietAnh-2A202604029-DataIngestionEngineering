"""Persistent PostgreSQL + pgvector store with parameterized metadata filters."""

from __future__ import annotations

import json
import math
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .models import Chunk

_ALLOWED_FILTERS = {
    "chapter",
    "section",
    "section_type",
    "printed_page",
    "document_type",
    "year",
    "language",
}


def _vector_literal(vector: list[float], expected_dimensions: int) -> str:
    if len(vector) != expected_dimensions:
        raise ValueError(
            f"Expected {expected_dimensions} vector dimensions, received {len(vector)}"
        )
    values = [float(value) for value in vector]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Vector contains NaN or infinity")
    return "[" + ",".join(format(value, ".9g") for value in values) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is empty")
        if not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError("dimensions must be a positive integer")
        self.database_url = database_url
        self.dimensions = dimensions
        self.table_name = "day06_chunks"

    def create_schema(self) -> None:
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        strategy TEXT NOT NULL,
                        chunk_id TEXT NOT NULL,
                        document_id TEXT NOT NULL,
                        source TEXT NOT NULL,
                        page INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        embedding VECTOR({self.dimensions}) NOT NULL,
                        PRIMARY KEY (strategy, chunk_id)
                    )
                    """)
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_metadata "
                    f"ON {self.table_name} USING GIN (metadata)"
                )
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_document "
                    f"ON {self.table_name} (strategy, document_id)"
                )
                # CREATE TABLE IF NOT EXISTS does not migrate an existing vector
                # column. Fail clearly rather than allowing a later opaque error.
                cursor.execute(
                    """SELECT format_type(a.atttypid, a.atttypmod)
                       FROM pg_attribute a
                       JOIN pg_class c ON c.oid = a.attrelid
                       WHERE c.relname = %s AND a.attname = 'embedding' AND NOT a.attisdropped""",
                    (self.table_name,),
                )
                row = cursor.fetchone()
                expected_type = f"vector({self.dimensions})"
                if row and row[0] != expected_type:
                    raise RuntimeError(
                        f"Database column is {row[0]}, but this model expects {expected_type}. "
                        "Use a fresh lab database/table or keep the same embedding dimensions."
                    )

    def upsert(
        self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]
    ) -> None:
        if strategy not in {"A", "B", "C"}:
            raise ValueError("strategy must be A, B or C")
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        if not chunks:
            return
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError(f"Duplicate chunk_id found in strategy {strategy}")

        rows = []
        for chunk, vector in zip(chunks, vectors):
            rows.append(
                (
                    strategy,
                    chunk.chunk_id,
                    chunk.document_id,
                    chunk.source,
                    int(chunk.page),
                    chunk.text,
                    Jsonb(chunk.metadata),
                    _vector_literal(vector, self.dimensions),
                )
            )

        document_ids = sorted({chunk.document_id for chunk in chunks})
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                # Replace this strategy's rows for the supplied documents. This
                # both prevents duplicate ingestion and removes obsolete chunks.
                cursor.execute(
                    f"DELETE FROM {self.table_name} WHERE strategy = %s AND document_id = ANY(%s)",
                    (strategy, document_ids),
                )
                cursor.executemany(
                    f"""INSERT INTO {self.table_name}
                        (strategy, chunk_id, document_id, source, page, content, metadata, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)""",
                    rows,
                )

    def search(
        self,
        strategy: str,
        query_vector: list[float],
        top_k: int = 3,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if strategy not in {"A", "B", "C"}:
            raise ValueError("strategy must be A, B or C")
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero")
        vector = _vector_literal(query_vector, self.dimensions)

        where = ["strategy = %s"]
        for key, value in (filters or {}).items():
            if key not in _ALLOWED_FILTERS:
                raise ValueError(f"Unsupported metadata filter field: {key}")
            if value is None or isinstance(value, (dict, list, tuple)):
                raise ValueError(f"Filter value for {key} must be a scalar")
            where.append("metadata ->> %s = %s")

        sql = f"""SELECT chunk_id, document_id, source, page, content, metadata,
                           1 - (embedding <=> %s::vector) AS score
                    FROM {self.table_name}
                    WHERE {' AND '.join(where)}
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s"""
        # The score expression occurs before WHERE in SQL placeholder order.
        # The vector is also needed for ORDER BY; keep both values parameterized.
        ordered_params = [vector, strategy]
        for key, value in (filters or {}).items():
            if key not in _ALLOWED_FILTERS:
                raise ValueError(f"Unsupported metadata filter field: {key}")
            ordered_params.extend([key, str(value)])
        ordered_params.extend([vector, top_k])

        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, ordered_params)
                rows = cursor.fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            metadata = row[5]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            results.append(
                {
                    "chunk_id": row[0],
                    "document_id": row[1],
                    "source": row[2],
                    "page": row[3],
                    "text": row[4],
                    "metadata": metadata,
                    "score": float(row[6]),
                }
            )
        return results
