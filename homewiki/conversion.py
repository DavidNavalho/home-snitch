"""Document conversion into inspectable Markdown.

This module preserves the source tree shape under a Markdown output root and
keeps conversion independent from retrieval, embeddings, and chat providers.
"""

from __future__ import annotations

import csv
import html
import json
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from homewiki.schemas import (
    ConversionReport,
    ConversionStatus,
    FileConversionResult,
    SourceType,
)


SUPPORTED_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".htm",
    ".html",
    ".json",
    ".md",
    ".pdf",
    ".ppt",
    ".pptx",
    ".txt",
    ".xls",
    ".xlsx",
    ".xml",
}

MARKDOWN_EXTENSIONS = {".md"}
TEXT_EXTENSIONS = {".txt"}
CSV_EXTENSIONS = {".csv"}
HTML_EXTENSIONS = {".html", ".htm"}
JSON_EXTENSIONS = {".json"}
PDF_EXTENSIONS = {".pdf"}
EXCEL_EXTENSIONS = {".xls", ".xlsx"}
OFFICE_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx"}
XML_EXTENSIONS = {".xml"}


class ConversionError(RuntimeError):
    """Raised when one source file cannot be converted."""


class _HTMLTextExtractor(HTMLParser):
    BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }

    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized in {"head", "script", "style", "title"}:
            self._skip_depth += 1
            return
        if normalized in self.HEADING_TAGS:
            self._append_break()
            self.parts.append("#" * int(normalized[1]) + " ")
            return
        if normalized == "li":
            self._append_break()
            self.parts.append("- ")
            return
        if normalized in self.BLOCK_TAGS:
            self._append_break()

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"head", "script", "style", "title"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if normalized in self.HEADING_TAGS:
            self._append_break()
            return
        if normalized in self.BLOCK_TAGS:
            self._append_break()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        if (
            self.parts
            and self.parts[-1] not in {"", "\n", " ", "- "}
            and not self.parts[-1].endswith(" ")
        ):
            self.parts.append(" ")
        self.parts.append(text)

    def text(self) -> str:
        rendered = "".join(self.parts)
        rendered = re.sub(r"[ \t]+\n", "\n", rendered)
        rendered = re.sub(r"\n{3,}", "\n\n", rendered)
        return rendered.strip()

    def _append_break(self) -> None:
        if not self.parts:
            return
        current = "".join(self.parts)
        if current.endswith("\n\n"):
            return
        if current.endswith("\n"):
            self.parts.append("\n")
        else:
            self.parts.append("\n\n")


def discover_files(source_root: Path) -> list[Path]:
    """Return supported source files in deterministic order."""

    return sorted(
        path
        for path in source_root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def output_path_for(source_root: Path, markdown_root: Path, source_path: Path) -> Path:
    """Map a source path to its Markdown output path."""

    relative_path = source_path.relative_to(source_root)
    if source_path.suffix.lower() in MARKDOWN_EXTENSIONS:
        return markdown_root / relative_path
    return markdown_root / relative_path.parent / f"{relative_path.name}.md"


def convert_tree(
    source_root: Path,
    markdown_root: Path,
    force: bool = False,
    fail_fast: bool = False,
) -> ConversionReport:
    """Convert supported files from source_root into markdown_root."""

    source_root = source_root.expanduser().resolve()
    markdown_root = markdown_root.expanduser().resolve()

    if not source_root.exists():
        raise FileNotFoundError(f"source root does not exist: {source_root}")
    if not source_root.is_dir():
        raise NotADirectoryError(f"source root is not a directory: {source_root}")

    results: list[FileConversionResult] = []
    counts = {
        ConversionStatus.CONVERTED: 0,
        ConversionStatus.COPIED: 0,
        ConversionStatus.SKIPPED: 0,
        ConversionStatus.FAILED: 0,
    }

    for source_path in discover_files(source_root):
        markdown_path = output_path_for(source_root, markdown_root, source_path)
        source_display = _display_path(source_path, source_root)
        markdown_display = _display_path(markdown_path, markdown_root)

        if not force and _is_unchanged(source_path, markdown_path):
            counts[ConversionStatus.SKIPPED] += 1
            results.append(
                FileConversionResult(
                    source_path=source_display,
                    markdown_path=markdown_display,
                    status=ConversionStatus.SKIPPED,
                )
            )
            continue

        try:
            status = convert_file(source_root, markdown_root, source_path, markdown_path)
        except Exception as exc:  # noqa: BLE001 - report and optionally continue.
            counts[ConversionStatus.FAILED] += 1
            results.append(
                FileConversionResult(
                    source_path=source_display,
                    markdown_path=markdown_display,
                    status=ConversionStatus.FAILED,
                    error=str(exc),
                )
            )
            if fail_fast:
                break
            continue

        counts[status] += 1
        results.append(
            FileConversionResult(
                source_path=source_display,
                markdown_path=markdown_display,
                status=status,
            )
        )

    return ConversionReport(
        converted=counts[ConversionStatus.CONVERTED],
        copied=counts[ConversionStatus.COPIED],
        skipped=counts[ConversionStatus.SKIPPED],
        failed=counts[ConversionStatus.FAILED],
        files=results,
    )


def convert_file(
    source_root: Path,
    markdown_root: Path,
    source_path: Path,
    markdown_path: Path,
) -> ConversionStatus:
    """Convert one source file and return the conversion status."""

    suffix = source_path.suffix.lower()
    markdown_path.parent.mkdir(parents=True, exist_ok=True)

    metadata = infer_document_metadata(
        source_root=source_root,
        markdown_root=markdown_root,
        source_path=source_path,
        markdown_path=markdown_path,
    )

    if suffix in MARKDOWN_EXTENSIONS:
        markdown = convert_markdown_file(source_path)
        status = ConversionStatus.COPIED
    elif suffix in TEXT_EXTENSIONS:
        markdown = convert_text_file(source_path)
        status = ConversionStatus.CONVERTED
    elif suffix in CSV_EXTENSIONS:
        markdown = convert_csv_file(source_path)
        status = ConversionStatus.CONVERTED
    elif suffix in JSON_EXTENSIONS:
        markdown = convert_json_file(source_path)
        status = ConversionStatus.CONVERTED
    elif suffix in HTML_EXTENSIONS:
        markdown = convert_html_file(source_path)
        status = ConversionStatus.CONVERTED
    elif suffix in PDF_EXTENSIONS:
        markdown = convert_pdf_file(source_path)
        status = ConversionStatus.CONVERTED
    elif suffix in XML_EXTENSIONS:
        markdown = convert_xml_file(source_path)
        status = ConversionStatus.CONVERTED
    elif suffix in EXCEL_EXTENSIONS:
        markdown = convert_excel_file(source_path)
        status = ConversionStatus.CONVERTED
    elif suffix in OFFICE_EXTENSIONS:
        markdown = convert_with_markitdown(source_path)
        status = ConversionStatus.CONVERTED
    else:
        raise ConversionError(f"unsupported file type: {source_path.suffix}")

    markdown = normalize_markdown(markdown)
    if not markdown:
        raise ConversionError("conversion produced empty Markdown")

    output = add_frontmatter(markdown, metadata)
    markdown_path.write_text(output, encoding="utf-8")
    return status


def infer_document_metadata(
    source_root: Path,
    markdown_root: Path,
    source_path: Path,
    markdown_path: Path,
) -> dict[str, str]:
    relative_source = source_path.relative_to(source_root)
    relative_markdown = markdown_path.relative_to(markdown_root)
    metadata = {
        "source_path": str(Path(source_root.name) / relative_source),
        "source_type": infer_source_type(relative_source).value,
        "markdown_path": str(Path(markdown_root.name) / relative_markdown),
    }

    parts = relative_source.parts
    if len(parts) >= 3 and parts[0] == "devices":
        metadata["asset_id"] = parts[1]

    return metadata


def infer_source_type(relative_source: Path) -> SourceType:
    parts = relative_source.parts
    if relative_source.name == "profile.md":
        return SourceType.PROFILE
    if "manuals" in parts:
        return SourceType.MANUAL
    if "notes" in parts:
        return SourceType.NOTE
    if "receipts" in parts:
        return SourceType.RECEIPT
    return SourceType.OTHER


def convert_markdown_file(source_path: Path) -> str:
    return strip_frontmatter(source_path.read_text(encoding="utf-8"))


def convert_text_file(source_path: Path) -> str:
    text = source_path.read_text(encoding="utf-8")
    title = source_path.stem.replace("-", " ").replace("_", " ").strip().title()
    return f"# {title}\n\n{text.strip()}\n"


def convert_csv_file(source_path: Path) -> str:
    with source_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    title = source_path.stem.replace("-", " ").replace("_", " ").strip().title()
    if not rows:
        return f"# {title}\n\n_No rows found._\n"

    width = max(len(row) for row in rows)
    padded_rows = [row + [""] * (width - len(row)) for row in rows]
    header = [_markdown_escape(cell or f"Column {index + 1}") for index, cell in enumerate(padded_rows[0])]
    lines = [
        f"# {title}",
        "",
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in padded_rows[1:]:
        lines.append("| " + " | ".join(_markdown_escape(cell) for cell in row) + " |")
    return "\n".join(lines) + "\n"


def convert_json_file(source_path: Path) -> str:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    title = source_path.stem.replace("-", " ").replace("_", " ").strip().title()
    formatted = json.dumps(payload, indent=2, sort_keys=True)
    return f"# {title}\n\n```json\n{formatted}\n```\n"


def convert_html_file(source_path: Path) -> str:
    raw = source_path.read_text(encoding="utf-8")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.IGNORECASE | re.DOTALL)
    title = (
        html.unescape(" ".join(title_match.group(1).split()))
        if title_match
        else source_path.stem.replace("-", " ").replace("_", " ").strip().title()
    )

    extractor = _HTMLTextExtractor()
    extractor.feed(raw)
    body = extractor.text()
    if not body:
        raise ConversionError("HTML conversion produced no body text")
    if body.lstrip().startswith("# "):
        return body + "\n"
    return f"# {title}\n\n{body}\n"


def convert_xml_file(source_path: Path) -> str:
    title = source_path.stem.replace("-", " ").replace("_", " ").strip().title()
    text = source_path.read_text(encoding="utf-8").strip()
    return f"# {title}\n\n```xml\n{text}\n```\n"


def convert_pdf_file(source_path: Path) -> str:
    fitz_markdown = _convert_pdf_with_pymupdf(source_path)
    if fitz_markdown:
        return fitz_markdown

    extracted = _extract_pdf_text_fallback(source_path)
    if extracted:
        title = source_path.stem.replace("-", " ").replace("_", " ").strip().title()
        return f"# {title}\n\n{extracted}\n"

    markitdown = _convert_with_markitdown_if_available(source_path)
    if markitdown:
        return markitdown

    raise ConversionError("PDF conversion failed; install PyMuPDF or markitdown for this file")


def _convert_pdf_with_pymupdf(source_path: Path) -> str | None:
    try:
        import fitz  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return None

    try:
        document = fitz.open(source_path)
    except Exception:
        return None

    try:
        pages: list[str] = []
        for page in document:
            text = cleanup_extracted_text(page.get_text("text"))
            if text:
                pages.append(text)
        if not pages:
            return None
        title = source_path.stem.replace("-", " ").replace("_", " ").strip().title()
        return f"# {title}\n\n" + "\n\n".join(pages) + "\n"
    finally:
        document.close()


def _extract_pdf_text_fallback(source_path: Path) -> str | None:
    raw = source_path.read_bytes().decode("latin-1", errors="ignore")
    streams = re.findall(r"stream\s*(.*?)\s*endstream", raw, flags=re.DOTALL)
    if streams:
        extracted_parts: list[str] = []
        for stream in streams:
            parenthesized = _extract_parenthesized_pdf_strings(stream)
            extracted_parts.append("\n".join(parenthesized) if parenthesized else stream)
        text = "\n\n".join(extracted_parts)
    else:
        text = raw

    text = re.sub(r"<<.*?>>|\b\d+\s+\d+\s+obj\b|endobj|xref|trailer|%%EOF", " ", text, flags=re.DOTALL)
    return cleanup_extracted_text(text)


def _extract_parenthesized_pdf_strings(stream: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(r"\((?:\\.|[^\\)])*\)", stream, flags=re.DOTALL):
        value = match.group(0)[1:-1]
        value = (
            value.replace(r"\(", "(")
            .replace(r"\)", ")")
            .replace(r"\\", "\\")
            .replace(r"\n", "\n")
            .replace(r"\r", "\r")
            .replace(r"\t", "\t")
        )
        if value.strip():
            values.append(value.strip())
    return values


def convert_excel_file(source_path: Path) -> str:
    pandas_markdown = _convert_excel_with_pandas(source_path)
    if pandas_markdown:
        return pandas_markdown

    markitdown = _convert_with_markitdown_if_available(source_path)
    if markitdown:
        return markitdown

    raise ConversionError(
        f"{source_path.suffix} conversion requires pandas Excel support or markitdown"
    )


def _convert_excel_with_pandas(source_path: Path) -> str | None:
    try:
        import pandas as pd  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return None

    engine = "openpyxl" if source_path.suffix.lower() == ".xlsx" else "xlrd"
    try:
        workbook = pd.read_excel(
            source_path,
            sheet_name=None,
            dtype=object,
            engine=engine,
        )
    except ImportError:
        return None
    except Exception as exc:
        raise ConversionError(f"Excel conversion failed: {exc}") from exc

    title = source_path.stem.replace("-", " ").replace("_", " ").strip().title()
    if not workbook:
        return f"# Workbook: {title}\n\n_No sheets found._\n"

    sections = [f"# Workbook: {title}"]
    for sheet_name, dataframe in workbook.items():
        sections.append(_sheet_to_markdown(str(sheet_name), dataframe))
    return "\n\n".join(sections) + "\n"


def _sheet_to_markdown(sheet_name: str, dataframe: Any) -> str:
    header = f"## Sheet: {sheet_name}\n"
    if dataframe.empty:
        return f"{header}\n_No data rows found._"

    rendered = dataframe.fillna("")
    columns = [
        _markdown_escape(_stringify_tabular_value(column)) or f"Column {index + 1}"
        for index, column in enumerate(rendered.columns)
    ]
    lines = [
        header,
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in rendered.itertuples(index=False, name=None):
        lines.append(
            "| "
            + " | ".join(_markdown_escape(_stringify_tabular_value(cell)) for cell in row)
            + " |"
        )
    return "\n".join(lines)


def _stringify_tabular_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def convert_with_markitdown(source_path: Path) -> str:
    markdown = _convert_with_markitdown_if_available(source_path)
    if markdown is None:
        raise ConversionError(
            f"{source_path.suffix} conversion requires the markitdown CLI"
        )
    return markdown


def _convert_with_markitdown_if_available(source_path: Path) -> str | None:
    executable = shutil.which("markitdown")
    if executable is None:
        return None

    with tempfile.TemporaryDirectory() as tmp:
        output_path = Path(tmp) / "converted.md"
        completed = subprocess.run(
            [executable, str(source_path), "-o", str(output_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            stdout = completed.stdout.strip()
            detail = stderr or stdout or "markitdown exited with a non-zero status"
            raise ConversionError(detail)
        if output_path.exists():
            return output_path.read_text(encoding="utf-8")
        return completed.stdout


def strip_frontmatter(markdown: str) -> str:
    if not markdown.startswith("---\n"):
        return markdown
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return markdown
    return markdown[end + len("\n---\n") :]


def add_frontmatter(markdown: str, metadata: dict[str, str]) -> str:
    lines = ["---"]
    for key in ("source_path", "source_type", "asset_id", "markdown_path"):
        value = metadata.get(key)
        if value:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + markdown.strip() + "\n"


def normalize_markdown(markdown: str) -> str:
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    markdown = markdown.replace("\x0c", "\n").replace("\u00ad", "")
    markdown = re.sub(r"[ \t]+\n", "\n", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown.strip()


def cleanup_extracted_text(text: str) -> str:
    text = html.unescape(text)
    text = text.replace("\x00", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line and not re.fullmatch(r"\d+", line)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _markdown_escape(value: Any) -> str:
    return str(value).replace("|", r"\|").replace("\n", "<br>").strip()


def _is_unchanged(source_path: Path, markdown_path: Path) -> bool:
    if not markdown_path.exists():
        return False
    return markdown_path.stat().st_mtime >= source_path.stat().st_mtime


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(Path(root.name) / path.relative_to(root))
    except ValueError:
        return str(path)


__all__ = [
    "ConversionError",
    "SUPPORTED_EXTENSIONS",
    "convert_file",
    "convert_tree",
    "discover_files",
    "infer_source_type",
    "output_path_for",
]
