"""Markdown indexing orchestration and incremental ingest manifest handling."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from homewiki.chunking import extract_frontmatter, split_markdown_document
from homewiki.conversion import convert_tree
from homewiki.devices import load_profile
from homewiki.schemas import (
    ConversionStatus,
    DocumentMetadata,
    ErrorResponse,
    IndexChunk,
    IngestReport,
    SourceType,
)


class IngestError(RuntimeError):
    """Raised when indexing cannot proceed."""


def build_index(
    markdown_root: Path,
    source_root: Path,
    store: Any,
    force: bool = False,
) -> IngestReport:
    """Build or refresh the chunk index from converted Markdown documents."""

    markdown_root = markdown_root.expanduser().resolve()
    source_root = source_root.expanduser().resolve()
    manifest_path = manifest_path_for(source_root, markdown_root)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    if not markdown_root.exists():
        return IngestReport(
            failed=1,
            errors=[
                ErrorResponse(
                    code="missing_markdown_root",
                    message=f"markdown root does not exist: {markdown_root}",
                    details={"markdown_root": str(markdown_root)},
                )
            ],
        )

    indexed = 0
    skipped = 0
    failed = 0
    removed = 0
    warnings: list[str] = []
    errors: list[ErrorResponse] = []

    markdown_paths = sorted(markdown_root.rglob("*.md"))
    current_manifest_paths = {
        portable_markdown_path(markdown_root, path) for path in markdown_paths
    }

    with closing(_connect_manifest(manifest_path)) as connection:
        _ensure_manifest(connection)
        removed += _remove_stale_documents(
            connection=connection,
            store=store,
            current_manifest_paths=current_manifest_paths,
            errors=errors,
            warnings=warnings,
        )

        for markdown_path in markdown_paths:
            markdown_display_path = portable_markdown_path(markdown_root, markdown_path)
            try:
                content = markdown_path.read_text(encoding="utf-8")
                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                manifest_row = _manifest_row(connection, markdown_display_path)

                if (
                    not force
                    and manifest_row is not None
                    and manifest_row["content_hash"] == content_hash
                ):
                    skipped += 1
                    continue

                metadata = document_metadata_for(
                    markdown_path=markdown_path,
                    markdown_root=markdown_root,
                    source_root=source_root,
                )
                chunks = split_markdown_document(markdown_path, metadata)
                if not chunks:
                    removed += store.delete_chunks_for_markdown_path(markdown_display_path)
                    _delete_manifest(connection, markdown_display_path)
                    skipped += 1
                    warning = f"skipping empty Markdown document: {markdown_display_path}"
                    warnings.append(warning)
                    continue

                store.delete_chunks_for_markdown_path(markdown_display_path)
                result = store.index_chunks(chunks, mode="append")
                indexed_count = int(getattr(result, "indexed", len(chunks)))
                indexed += indexed_count
                _upsert_manifest(
                    connection=connection,
                    markdown_path=markdown_display_path,
                    content_hash=content_hash,
                    chunk_count=len(chunks),
                )
            except IngestError as exc:
                removed += store.delete_chunks_for_markdown_path(markdown_display_path)
                _delete_manifest(connection, markdown_display_path)
                failed += 1
                errors.append(
                    ErrorResponse(
                        code="metadata_failed",
                        message=f"failed to index {markdown_display_path}: {exc}",
                        details={"markdown_path": markdown_display_path},
                    )
                )
                continue
            except Exception as exc:  # noqa: BLE001 - report and continue.
                failed += 1
                errors.append(
                    ErrorResponse(
                        code="index_failed",
                        message=f"failed to index {markdown_display_path}: {exc}",
                        details={"markdown_path": markdown_display_path},
                    )
                )
                continue

    return IngestReport(
        indexed=indexed,
        skipped=skipped,
        failed=failed,
        removed=removed,
        warnings=warnings,
        errors=errors,
    )


def ingest_all(
    source_root: Path,
    markdown_root: Path,
    store: Any,
    force_convert: bool = False,
    force_index: bool = False,
) -> IngestReport:
    """Convert source docs and then refresh the Markdown chunk index."""

    conversion_report = convert_tree(
        source_root=source_root,
        markdown_root=markdown_root,
        force=force_convert,
    )
    index_report = build_index(
        markdown_root=markdown_root,
        source_root=source_root,
        store=store,
        force=force_index,
    )

    conversion_errors = [
        ErrorResponse(
            code="conversion_failed",
            message=f"failed to convert {result.source_path}: {result.error}",
            details={
                "source_path": result.source_path,
                "markdown_path": result.markdown_path,
            },
        )
        for result in conversion_report.files
        if result.status == ConversionStatus.FAILED
    ]

    return IngestReport(
        converted=conversion_report.converted + conversion_report.copied,
        indexed=index_report.indexed,
        skipped=conversion_report.skipped + index_report.skipped,
        failed=conversion_report.failed + index_report.failed,
        removed=index_report.removed,
        warnings=index_report.warnings,
        errors=[*conversion_errors, *index_report.errors],
    )


def document_metadata_for(
    markdown_path: Path,
    markdown_root: Path,
    source_root: Path,
) -> DocumentMetadata:
    """Attach device profile metadata to one Markdown document."""

    raw_markdown = markdown_path.read_text(encoding="utf-8")
    frontmatter = extract_frontmatter(raw_markdown)
    relative_path = markdown_path.relative_to(markdown_root)
    asset_id = frontmatter.get("asset_id") or _asset_id_from_relative_path(relative_path)
    source_type = _source_type_for(relative_path, frontmatter)
    markdown_display_path = portable_markdown_path(markdown_root, markdown_path)
    source_display_path = frontmatter.get("source_path") or portable_source_path(
        source_root=source_root,
        relative_markdown_path=relative_path,
    )

    profile = None
    if asset_id is not None:
        profile_path = source_root / "devices" / asset_id / "profile.yaml"
        if not profile_path.exists():
            raise IngestError(
                f"missing profile for device document {markdown_display_path}: "
                f"{profile_path}"
            )
        profile = load_profile(profile_path)

    return DocumentMetadata(
        asset_id=asset_id,
        source_type=source_type,
        brand=profile.brand if profile else None,
        model=profile.model if profile else None,
        normalized_model=profile.normalized_model if profile else None,
        device_type=profile.device_type if profile else None,
        room=profile.room if profile else None,
        source_path=source_display_path,
        markdown_path=markdown_display_path,
        tags=profile.tags if profile else [],
    )


def infer_source_type(relative_path: Path) -> SourceType:
    """Infer source type from a Markdown path relative to markdown_root."""

    return _source_type_for(relative_path, {})


def manifest_path_for(source_root: Path, markdown_root: Path) -> Path:
    """Return the default manifest path for a source/markdown root pair."""

    if source_root.name == "source_docs":
        return source_root.parent / "data" / "ingest_manifest.sqlite"
    if markdown_root.name == "markdown_docs":
        return markdown_root.parent / "data" / "ingest_manifest.sqlite"
    return markdown_root.parent / "data" / "ingest_manifest.sqlite"


def portable_markdown_path(markdown_root: Path, markdown_path: Path) -> str:
    return str(Path(markdown_root.name) / markdown_path.relative_to(markdown_root))


def portable_source_path(source_root: Path, relative_markdown_path: Path) -> str:
    source_relative = relative_markdown_path
    if (
        source_relative.suffix == ".md"
        and source_relative.name != "profile.md"
        and Path(source_relative.stem).suffix
    ):
        source_relative = source_relative.with_name(source_relative.name[:-3])
    return str(Path(source_root.name) / source_relative)


def _asset_id_from_relative_path(relative_path: Path) -> str | None:
    parts = relative_path.parts
    if len(parts) >= 3 and parts[0] == "devices":
        return parts[1]
    return None


def _source_type_for(relative_path: Path, frontmatter: dict[str, str]) -> SourceType:
    frontmatter_source_type = frontmatter.get("source_type")
    if frontmatter_source_type:
        return SourceType(frontmatter_source_type)

    parts = relative_path.parts
    if relative_path.name == "profile.md":
        return SourceType.PROFILE
    if "manuals" in parts:
        return SourceType.MANUAL
    if "notes" in parts:
        return SourceType.NOTE
    if "receipts" in parts:
        return SourceType.RECEIPT
    return SourceType.OTHER


def _connect_manifest(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_manifest(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS indexed_documents (
            markdown_path TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            chunk_count INTEGER NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    connection.commit()


def _manifest_row(
    connection: sqlite3.Connection,
    markdown_path: str,
) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM indexed_documents WHERE markdown_path = ?",
        (markdown_path,),
    ).fetchone()


def _upsert_manifest(
    *,
    connection: sqlite3.Connection,
    markdown_path: str,
    content_hash: str,
    chunk_count: int,
) -> None:
    connection.execute(
        """
        INSERT INTO indexed_documents (
            markdown_path,
            content_hash,
            chunk_count,
            updated_at
        ) VALUES (?, ?, ?, ?)
        ON CONFLICT(markdown_path) DO UPDATE SET
            content_hash = excluded.content_hash,
            chunk_count = excluded.chunk_count,
            updated_at = excluded.updated_at
        """,
        (markdown_path, content_hash, chunk_count, time.time()),
    )
    connection.commit()


def _delete_manifest(connection: sqlite3.Connection, markdown_path: str) -> None:
    connection.execute(
        "DELETE FROM indexed_documents WHERE markdown_path = ?",
        (markdown_path,),
    )
    connection.commit()


def _remove_stale_documents(
    *,
    connection: sqlite3.Connection,
    store: Any,
    current_manifest_paths: set[str],
    errors: list[ErrorResponse],
    warnings: list[str],
) -> int:
    removed = 0
    rows = connection.execute("SELECT markdown_path FROM indexed_documents").fetchall()
    for row in rows:
        markdown_path = str(row["markdown_path"])
        if markdown_path in current_manifest_paths:
            continue
        try:
            deleted = int(store.delete_chunks_for_markdown_path(markdown_path))
            removed += deleted
            connection.execute(
                "DELETE FROM indexed_documents WHERE markdown_path = ?",
                (markdown_path,),
            )
            connection.commit()
        except Exception as exc:  # noqa: BLE001 - preserve other stale cleanup.
            message = f"failed to remove stale chunks for {markdown_path}: {exc}"
            warnings.append(message)
            errors.append(
                ErrorResponse(
                    code="stale_delete_failed",
                    message=message,
                    details={"markdown_path": markdown_path},
                )
            )
    return removed


__all__ = [
    "IngestError",
    "build_index",
    "document_metadata_for",
    "infer_source_type",
    "ingest_all",
    "manifest_path_for",
    "portable_markdown_path",
    "portable_source_path",
]
