"""LanceDB-backed chunk index and hybrid search foundation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from homewiki.config import Settings, load_settings
from homewiki.embeddings import (
    EmbeddingClient,
    EmbeddingProviderError,
    create_embedding_client,
)
from homewiki.schemas import (
    IndexChunk,
    IndexResult,
    SearchFilters,
    SearchResult,
    SourceType,
)


IndexMode = Literal["append", "overwrite", "upsert"]

TABLE_COLUMNS = (
    "text",
    "asset_id",
    "source_type",
    "brand",
    "model",
    "normalized_model",
    "device_type",
    "room",
    "source_path",
    "markdown_path",
    "section_title",
    "chunk_index",
    "content_hash",
    "modified_at",
    "tags",
)
SCALAR_INDEX_COLUMNS = (
    "asset_id",
    "normalized_model",
    "device_type",
    "room",
    "source_type",
    "section_title",
)


class LanceStoreError(RuntimeError):
    """Raised when LanceDB storage or search cannot complete."""


@dataclass
class LanceStore:
    """Provider-aware LanceDB store for Home Wiki chunks."""

    settings: Settings
    embedding: EmbeddingClient = field(init=False)
    table_name: str = field(init=False)
    db_path: Path = field(init=False)
    _db: Any = field(default=None, init=False, repr=False)
    _table: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.embedding = create_embedding_client(self.settings)
        self.table_name = self.settings.table
        self.db_path = self.settings.paths.lancedb_dir

    def index_chunks(
        self,
        chunks: list[IndexChunk],
        mode: IndexMode = "append",
    ) -> IndexResult:
        """Embed and write chunks into the LanceDB table."""

        if mode not in {"append", "overwrite", "upsert"}:
            raise ValueError("mode must be one of: append, overwrite, upsert")
        if not chunks:
            return IndexResult()

        vectors = self.embedding.embed_texts([chunk.text for chunk in chunks])
        dimension = _validate_vectors(vectors, expected_count=len(chunks))
        rows = [
            _row_from_chunk(chunk, vector)
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]

        db = self._get_db()
        table_exists = self._table_exists()
        deleted = 0

        try:
            if mode == "overwrite":
                if table_exists:
                    deleted = self._open_table().count_rows()
                table = db.create_table(
                    self.table_name,
                    schema=_make_schema(dimension),
                    mode="overwrite",
                )
                table.add(rows)
            elif not table_exists:
                table = db.create_table(
                    self.table_name,
                    schema=_make_schema(dimension),
                    mode="create",
                )
                table.add(rows)
            elif mode == "upsert":
                table = self._open_table()
                _validate_table_dimension(table, dimension)
                (
                    table.merge_insert(["markdown_path", "chunk_index"])
                    .when_matched_update_all()
                    .when_not_matched_insert_all()
                    .execute(rows)
                )
            else:
                table = self._open_table()
                _validate_table_dimension(table, dimension)
                table.add(rows)

            self._table = table
            self._ensure_indexes(table)
        except Exception as exc:
            if isinstance(exc, LanceStoreError):
                raise
            raise LanceStoreError(
                f"LanceDB indexing failed for table {self.table_name!r}: {exc}"
            ) from exc

        return IndexResult(indexed=len(rows), deleted=deleted)

    def delete_chunks_for_markdown_path(self, markdown_path: str) -> int:
        """Delete all chunks sourced from a markdown document."""

        if not self._table_exists():
            return 0

        table = self._open_table()
        where = f"markdown_path = {_sql_string(markdown_path)}"
        try:
            result = table.delete(where)
            deleted = int(getattr(result, "num_deleted_rows", 0))
            if table.count_rows() > 0:
                self._ensure_indexes(table)
            return deleted
        except Exception as exc:
            raise LanceStoreError(
                "LanceDB delete failed for "
                f"markdown_path {markdown_path!r}: {exc}"
            ) from exc

    def hybrid_search(
        self,
        query: str,
        filters: SearchFilters | None = None,
        limit: int = 8,
    ) -> list[SearchResult]:
        """Run filtered LanceDB hybrid search and return API-safe results."""

        if limit < 1:
            raise ValueError("limit must be >= 1")
        query = query.strip()
        if not query:
            return []

        table = self._open_table()
        try:
            query_vector = self.embedding.embed_texts([query])[0]
        except EmbeddingProviderError:
            raise
        except Exception as exc:
            raise EmbeddingProviderError(
                f"{self.embedding.provider} query embedding failed: {exc}"
            ) from exc

        where = _filter_expression(filters)
        try:
            rows = self._execute_hybrid_search(
                table,
                query=query,
                query_vector=query_vector,
                where=where,
                limit=limit,
            )
        except Exception:
            self._ensure_indexes(table)
            try:
                rows = self._execute_hybrid_search(
                    table,
                    query=query,
                    query_vector=query_vector,
                    where=where,
                    limit=limit,
                )
            except Exception as exc:
                raise LanceStoreError(
                    "LanceDB hybrid search failed for table "
                    f"{self.table_name!r}: {exc}"
                ) from exc

        return [_search_result_from_row(row) for row in rows]

    def status(self) -> dict[str, Any]:
        """Return table, provider, row count, and storage path health."""

        base = {
            "table": self.table_name,
            "table_name": self.table_name,
            "embedding_provider": self.embedding.provider,
            "db_path": str(self.db_path),
        }
        try:
            if not self._table_exists():
                return {
                    **base,
                    "status": "missing_table",
                    "row_count": 0,
                    "error": (
                        f"LanceDB table {self.table_name!r} does not exist at "
                        f"{self.db_path}"
                    ),
                }
            table = self._open_table()
            return {**base, "status": "ok", "row_count": table.count_rows()}
        except Exception as exc:
            return {**base, "status": "error", "row_count": 0, "error": str(exc)}

    def _get_db(self) -> Any:
        if self._db is not None:
            return self._db

        try:
            import lancedb
        except ImportError as exc:
            raise LanceStoreError(
                "lancedb is required for homewiki.lancedb_store. "
                "Install the project search dependencies first."
            ) from exc

        self.db_path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self.db_path))
        return self._db

    def _table_names(self) -> set[str]:
        db = self._get_db()
        if hasattr(db, "list_tables"):
            tables = db.list_tables()
            return set(tables.tables if hasattr(tables, "tables") else tables)
        return set(db.table_names())

    def _table_exists(self) -> bool:
        return self.table_name in self._table_names()

    def _open_table(self) -> Any:
        if self._table is not None:
            return self._table
        if not self._table_exists():
            raise LanceStoreError(
                f"LanceDB table {self.table_name!r} is not available at "
                f"{self.db_path}. Index chunks before searching."
            )
        self._table = self._get_db().open_table(self.table_name)
        return self._table

    def _ensure_indexes(self, table: Any) -> None:
        if table.count_rows() == 0:
            return

        table.create_fts_index("text", replace=True, with_position=True)
        for column in SCALAR_INDEX_COLUMNS:
            table.create_scalar_index(column, replace=True)

    def _execute_hybrid_search(
        self,
        table: Any,
        *,
        query: str,
        query_vector: list[float],
        where: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        from lancedb.rerankers import RRFReranker

        builder = (
            table.search(
                query_type="hybrid",
                vector_column_name="vector",
                fts_columns="text",
            )
            .vector(query_vector)
            .text(query)
            .rerank(RRFReranker())
            .select(list(TABLE_COLUMNS))
            .limit(limit)
        )
        if where:
            builder = builder.where(where, prefilter=True)
        return builder.to_list()


_active_store: LanceStore | None = None


def open_store(settings: Settings) -> LanceStore:
    """Create a LanceStore and make it the module-level active store."""

    global _active_store
    _active_store = LanceStore(settings)
    return _active_store


def index_chunks(
    chunks: list[IndexChunk],
    mode: IndexMode = "append",
) -> IndexResult:
    """Index chunks using the active store or environment-loaded settings."""

    return _get_active_store().index_chunks(chunks, mode=mode)


def delete_chunks_for_markdown_path(markdown_path: str) -> int:
    """Delete chunks by markdown path using the active store."""

    return _get_active_store().delete_chunks_for_markdown_path(markdown_path)


def hybrid_search(
    query: str,
    filters: SearchFilters | None = None,
    limit: int = 8,
) -> list[SearchResult]:
    """Search using the active store or environment-loaded settings."""

    return _get_active_store().hybrid_search(query, filters=filters, limit=limit)


def get_status(settings: Settings | None = None) -> dict[str, Any]:
    """Return store status for explicit settings or the active store."""

    if settings is not None:
        return LanceStore(settings).status()
    return _get_active_store().status()


def _get_active_store() -> LanceStore:
    global _active_store
    if _active_store is None:
        _active_store = LanceStore(load_settings())
    return _active_store


def _make_schema(dimension: int) -> Any:
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("text", pa.string(), nullable=False),
            pa.field("vector", pa.list_(pa.float32(), dimension), nullable=False),
            pa.field("asset_id", pa.string()),
            pa.field("source_type", pa.string(), nullable=False),
            pa.field("brand", pa.string()),
            pa.field("model", pa.string()),
            pa.field("normalized_model", pa.string()),
            pa.field("device_type", pa.string()),
            pa.field("room", pa.string()),
            pa.field("source_path", pa.string(), nullable=False),
            pa.field("markdown_path", pa.string(), nullable=False),
            pa.field("section_title", pa.string(), nullable=False),
            pa.field("chunk_index", pa.int64(), nullable=False),
            pa.field("content_hash", pa.string(), nullable=False),
            pa.field("modified_at", pa.float64()),
            pa.field("tags", pa.list_(pa.string())),
        ]
    )


def _validate_vectors(vectors: list[list[float]], *, expected_count: int) -> int:
    if len(vectors) != expected_count:
        raise EmbeddingProviderError(
            f"Embedding provider returned {len(vectors)} vectors for "
            f"{expected_count} chunks"
        )
    if not vectors:
        raise EmbeddingProviderError("Embedding provider returned no vectors")

    dimension = len(vectors[0])
    if dimension == 0:
        raise EmbeddingProviderError("Embedding provider returned empty vectors")

    for vector in vectors:
        if len(vector) != dimension:
            raise EmbeddingProviderError(
                "Embedding provider returned vectors with inconsistent dimensions"
            )
    return dimension


def _validate_table_dimension(table: Any, dimension: int) -> None:
    vector_field = table.schema.field("vector")
    list_size = getattr(vector_field.type, "list_size", None)
    if list_size is not None and int(list_size) != dimension:
        raise LanceStoreError(
            "Embedding dimension does not match existing LanceDB table "
            f"(table={list_size}, provider={dimension})"
        )


def _row_from_chunk(chunk: IndexChunk, vector: list[float]) -> dict[str, Any]:
    source_type = (
        chunk.source_type.value
        if isinstance(chunk.source_type, SourceType)
        else str(chunk.source_type)
    )
    return {
        "text": chunk.text,
        "vector": [float(value) for value in vector],
        "asset_id": chunk.asset_id,
        "source_type": source_type,
        "brand": chunk.brand,
        "model": chunk.model,
        "normalized_model": chunk.normalized_model,
        "device_type": chunk.device_type,
        "room": chunk.room,
        "source_path": chunk.source_path,
        "markdown_path": chunk.markdown_path,
        "section_title": chunk.section_title,
        "chunk_index": chunk.chunk_index,
        "content_hash": chunk.content_hash,
        "modified_at": _modified_at_value(chunk.modified_at),
        "tags": list(chunk.tags),
    }


def _modified_at_value(value: datetime | float) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    return float(value)


def _filter_expression(filters: SearchFilters | None) -> str | None:
    if filters is None or filters.is_empty():
        return None

    clauses: list[str] = []
    values = filters.model_dump(mode="json")
    for field_name in (
        "asset_id",
        "normalized_model",
        "device_type",
        "room",
        "source_type",
    ):
        value = values.get(field_name)
        if value is not None:
            clauses.append(f"{field_name} = {_sql_string(str(value))}")

    if not clauses:
        return None
    return " AND ".join(clauses)


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _search_result_from_row(row: dict[str, Any]) -> SearchResult:
    score = row.get("_relevance_score")
    if score is None:
        score = row.get("_score")
    if score is None and row.get("_distance") is not None:
        score = 1.0 / (1.0 + float(row["_distance"]))

    return SearchResult(
        text=row["text"],
        score=float(score) if score is not None else None,
        asset_id=row.get("asset_id"),
        source_type=row["source_type"],
        brand=row.get("brand"),
        model=row.get("model"),
        normalized_model=row.get("normalized_model"),
        device_type=row.get("device_type"),
        room=row.get("room"),
        source_path=row["source_path"],
        markdown_path=row["markdown_path"],
        section_title=row["section_title"],
        chunk_index=row.get("chunk_index"),
        content_hash=row.get("content_hash"),
        modified_at=row.get("modified_at"),
        tags=list(row.get("tags") or []),
    )


__all__ = [
    "IndexMode",
    "LanceStore",
    "LanceStoreError",
    "delete_chunks_for_markdown_path",
    "get_status",
    "hybrid_search",
    "index_chunks",
    "open_store",
]
