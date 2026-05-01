"""Heading-aware Markdown chunking for Home Wiki indexing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from homewiki.schemas import DocumentMetadata, IndexChunk


DEFAULT_MIN_CHARS = 80
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass
class _Section:
    title: str
    body: str


def split_markdown_document(
    markdown_path: Path,
    metadata: DocumentMetadata,
) -> list[IndexChunk]:
    """Split a Markdown document into indexed chunks with shared metadata."""

    markdown_path = markdown_path.expanduser().resolve()
    raw_markdown = markdown_path.read_text(encoding="utf-8")
    markdown = strip_frontmatter(raw_markdown).strip()
    if not markdown:
        return []

    content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    modified_at = markdown_path.stat().st_mtime
    sections = _merge_short_sections(_parse_sections(markdown), DEFAULT_MIN_CHARS)

    chunks: list[IndexChunk] = []
    for index, section in enumerate(sections):
        text = _chunk_text(section)
        if not text:
            continue
        chunks.append(
            IndexChunk(
                text=text,
                asset_id=metadata.asset_id,
                source_type=metadata.source_type,
                brand=metadata.brand,
                model=metadata.model,
                normalized_model=metadata.normalized_model,
                device_type=metadata.device_type,
                room=metadata.room,
                source_path=metadata.source_path,
                markdown_path=metadata.markdown_path,
                section_title=section.title,
                chunk_index=index,
                content_hash=content_hash,
                modified_at=modified_at,
                tags=metadata.tags,
            )
        )
    return chunks


def strip_frontmatter(markdown: str) -> str:
    """Remove leading YAML frontmatter if present."""

    if not markdown.startswith("---\n"):
        return markdown
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return markdown
    return markdown[end + len("\n---\n") :]


def extract_frontmatter(markdown: str) -> dict[str, str]:
    """Extract the simple scalar frontmatter written by conversion."""

    if not markdown.startswith("---\n"):
        return {}
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return {}

    fields: dict[str, str] = {}
    for raw_line in markdown[4:end].splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        key, separator, value = raw_line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    return fields


def _parse_sections(markdown: str) -> list[_Section]:
    sections: list[_Section] = []
    headings: list[str] = []
    current_title = "Introduction"
    current_lines: list[str] = []

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append(_Section(title=current_title, body=body))

    for line in markdown.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            current_lines = []
            level = len(heading.group(1))
            title = _clean_heading_title(heading.group(2))
            headings = headings[: level - 1]
            headings.append(title)
            current_title = " > ".join(headings) if headings else "Introduction"
            continue
        current_lines.append(line)

    flush()
    return sections


def _merge_short_sections(sections: list[_Section], minimum_chars: int) -> list[_Section]:
    if minimum_chars <= 0 or len(sections) < 2:
        return sections

    merged: list[_Section] = []
    index = 0
    while index < len(sections):
        section = sections[index]
        if section.title == "Introduction" or len(section.body) >= minimum_chars:
            merged.append(section)
            index += 1
            continue

        if merged and merged[-1].title != "Introduction":
            previous = merged[-1]
            merged[-1] = _Section(
                title=previous.title,
                body=f"{previous.body}\n\n## {section.title}\n\n{section.body}",
            )
            index += 1
            continue

        if index + 1 < len(sections):
            next_section = sections[index + 1]
            merged.append(
                _Section(
                    title=next_section.title,
                    body=f"## {section.title}\n\n{section.body}\n\n{next_section.body}",
                )
            )
            index += 2
            continue

        merged.append(section)
        index += 1

    return merged


def _chunk_text(section: _Section) -> str:
    body = section.body.strip()
    if not body:
        return ""
    return f"Section: {section.title}\n\n{body}"


def _clean_heading_title(title: str) -> str:
    return title.strip().strip("#").strip()


__all__ = [
    "DEFAULT_MIN_CHARS",
    "extract_frontmatter",
    "split_markdown_document",
    "strip_frontmatter",
]
