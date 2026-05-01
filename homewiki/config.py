"""Environment-driven project settings.

This module intentionally stays free of implementation imports. It reads a
provided environment mapping, resolves path settings, and returns immutable
dataclasses. Importing it does not create directories or connect to services.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


DEFAULT_ENV: dict[str, str] = {
    "HOME_WIKI_SOURCE_DOCS": "source_docs",
    "HOME_WIKI_MARKDOWN_DOCS": "markdown_docs",
    "HOME_WIKI_LANCEDB_DIR": "lancedb_data",
    "HOME_WIKI_TABLE": "home_wiki_chunks",
    "HOME_WIKI_DEVICE_REGISTRY": "data/devices.sqlite",
    "HOME_WIKI_INGEST_MANIFEST": "data/ingest_manifest.sqlite",
    "EMBEDDING_PROVIDER": "fake",
    "EMBEDDING_API_BASE": "http://localhost:1234/v1",
    "EMBEDDING_API_KEY": "",
    "EMBEDDING_MODEL": "",
    "GGUF_MODEL_REPO": "",
    "GGUF_MODEL_FILE": "",
    "GGUF_N_CTX": "8192",
    "GGUF_N_THREADS": "4",
    "CHAT_PROVIDER": "disabled",
    "CHAT_API_BASE": "",
    "CHAT_API_KEY": "",
    "CHAT_MODEL": "",
    "CHAT_TIMEOUT_SECONDS": "60",
    "CODEX_CMD": "codex",
    "CODEX_MODEL": "",
    "CODEX_TIMEOUT_SECONDS": "120",
    "CODEX_WORKDIR": "",
    "CODEX_OUTPUT_SCHEMA": "docs/schemas/home_wiki_answer.schema.json",
    "LMSTUDIO_API_BASE": "http://localhost:1234/v1",
    "LMSTUDIO_API_KEY": "lm-studio",
    "LMSTUDIO_CHAT_MODEL": "",
    "LMSTUDIO_TIMEOUT_SECONDS": "90",
    "API_HOST": "127.0.0.1",
    "API_PORT": "8000",
    "UI_API_BASE": "http://127.0.0.1:8000",
}

VALID_EMBEDDING_PROVIDERS = frozenset(
    {"local_gguf", "openai_compatible", "fake"}
)
VALID_CHAT_PROVIDERS = frozenset(
    {"codex_cli", "disabled", "lmstudio_openai", "openai_compatible"}
)

FOLDER_CONTRACT = (
    "source_docs/devices/<asset_id>/profile.yaml",
    "source_docs/devices/<asset_id>/profile.md",
    "source_docs/devices/<asset_id>/manuals/",
    "source_docs/devices/<asset_id>/notes/",
    "source_docs/devices/<asset_id>/receipts/",
    "source_docs/devices/<asset_id>/photos/",
    "markdown_docs/devices/<asset_id>/profile.md",
    "markdown_docs/devices/<asset_id>/manuals/<source_filename>.md",
    "markdown_docs/devices/<asset_id>/notes/",
    "markdown_docs/devices/<asset_id>/receipts/",
    "lancedb_data/",
    "data/",
)


@dataclass(frozen=True)
class PathSettings:
    project_root: Path
    source_docs: Path
    markdown_docs: Path
    lancedb_dir: Path
    device_registry: Path
    ingest_manifest: Path


@dataclass(frozen=True)
class EmbeddingSettings:
    provider: str
    api_base: str
    api_key: str
    model: str
    gguf_model_repo: str
    gguf_model_file: str
    gguf_n_ctx: int
    gguf_n_threads: int


@dataclass(frozen=True)
class ChatSettings:
    provider: str
    api_base: str
    api_key: str
    model: str
    chat_timeout_seconds: int
    codex_cmd: str
    codex_model: str
    codex_timeout_seconds: int
    codex_workdir: str
    codex_output_schema: str
    lmstudio_api_base: str
    lmstudio_api_key: str
    lmstudio_model: str
    lmstudio_timeout_seconds: int


@dataclass(frozen=True)
class ApiSettings:
    host: str
    port: int
    ui_api_base: str


@dataclass(frozen=True)
class Settings:
    paths: PathSettings
    table: str
    embedding: EmbeddingSettings
    chat: ChatSettings
    api: ApiSettings


def find_project_root(start: Path | None = None) -> Path:
    """Find the repo root without relying on the caller's current directory."""

    current = (start or Path(__file__)).resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists() or (candidate / ".git").exists():
            return candidate

    return Path.cwd().resolve()


def resolve_path_value(value: str, project_root: Path) -> Path:
    """Resolve an absolute path as-is or a relative path under project_root."""

    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return project_root / path


def load_settings(
    environ: Mapping[str, str] | None = None,
    project_root: Path | None = None,
) -> Settings:
    """Load immutable settings from environment variables and defaults."""

    import os

    env = os.environ if environ is None else environ
    root = Path(project_root or find_project_root()).expanduser()
    if not root.is_absolute():
        root = root.absolute()

    embedding_provider = _choice(
        _get(env, "EMBEDDING_PROVIDER"), VALID_EMBEDDING_PROVIDERS, "EMBEDDING_PROVIDER"
    )
    chat_provider = _choice(
        _get(env, "CHAT_PROVIDER"), VALID_CHAT_PROVIDERS, "CHAT_PROVIDER"
    )

    return Settings(
        paths=PathSettings(
            project_root=root,
            source_docs=resolve_path_value(_get(env, "HOME_WIKI_SOURCE_DOCS"), root),
            markdown_docs=resolve_path_value(_get(env, "HOME_WIKI_MARKDOWN_DOCS"), root),
            lancedb_dir=resolve_path_value(_get(env, "HOME_WIKI_LANCEDB_DIR"), root),
            device_registry=resolve_path_value(
                _get(env, "HOME_WIKI_DEVICE_REGISTRY"), root
            ),
            ingest_manifest=resolve_path_value(
                _get(env, "HOME_WIKI_INGEST_MANIFEST"), root
            ),
        ),
        table=_get(env, "HOME_WIKI_TABLE"),
        embedding=EmbeddingSettings(
            provider=embedding_provider,
            api_base=_get(env, "EMBEDDING_API_BASE"),
            api_key=_get(env, "EMBEDDING_API_KEY"),
            model=_get(env, "EMBEDDING_MODEL"),
            gguf_model_repo=_get(env, "GGUF_MODEL_REPO"),
            gguf_model_file=_get(env, "GGUF_MODEL_FILE"),
            gguf_n_ctx=_integer(_get(env, "GGUF_N_CTX"), "GGUF_N_CTX", minimum=1),
            gguf_n_threads=_integer(
                _get(env, "GGUF_N_THREADS"), "GGUF_N_THREADS", minimum=1
            ),
        ),
        chat=ChatSettings(
            provider=chat_provider,
            api_base=_get(env, "CHAT_API_BASE"),
            api_key=_get(env, "CHAT_API_KEY"),
            model=_get(env, "CHAT_MODEL"),
            chat_timeout_seconds=_integer(
                _get(env, "CHAT_TIMEOUT_SECONDS"),
                "CHAT_TIMEOUT_SECONDS",
                minimum=1,
            ),
            codex_cmd=_get(env, "CODEX_CMD"),
            codex_model=_get(env, "CODEX_MODEL"),
            codex_timeout_seconds=_integer(
                _get(env, "CODEX_TIMEOUT_SECONDS"),
                "CODEX_TIMEOUT_SECONDS",
                minimum=1,
            ),
            codex_workdir=_get(env, "CODEX_WORKDIR"),
            codex_output_schema=str(
                resolve_path_value(_get(env, "CODEX_OUTPUT_SCHEMA"), root)
            )
            if _get(env, "CODEX_OUTPUT_SCHEMA")
            else "",
            lmstudio_api_base=_get(env, "LMSTUDIO_API_BASE"),
            lmstudio_api_key=_get(env, "LMSTUDIO_API_KEY"),
            lmstudio_model=_get(env, "LMSTUDIO_CHAT_MODEL"),
            lmstudio_timeout_seconds=_integer(
                _get(env, "LMSTUDIO_TIMEOUT_SECONDS"),
                "LMSTUDIO_TIMEOUT_SECONDS",
                minimum=1,
            ),
        ),
        api=ApiSettings(
            host=_get(env, "API_HOST"),
            port=_integer(_get(env, "API_PORT"), "API_PORT", minimum=1, maximum=65535),
            ui_api_base=_get(env, "UI_API_BASE"),
        ),
    )


def _get(environ: Mapping[str, str], key: str) -> str:
    return environ.get(key, DEFAULT_ENV[key])


def _integer(
    value: str,
    variable_name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{variable_name} must be an integer") from exc

    if minimum is not None and parsed < minimum:
        raise ValueError(f"{variable_name} must be >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{variable_name} must be <= {maximum}")
    return parsed


def _choice(value: str, valid: frozenset[str], variable_name: str) -> str:
    if value not in valid:
        allowed = ", ".join(sorted(valid))
        raise ValueError(f"{variable_name} must be one of: {allowed}")
    return value


__all__ = [
    "ApiSettings",
    "ChatSettings",
    "DEFAULT_ENV",
    "EmbeddingSettings",
    "FOLDER_CONTRACT",
    "PathSettings",
    "Settings",
    "VALID_CHAT_PROVIDERS",
    "VALID_EMBEDDING_PROVIDERS",
    "find_project_root",
    "load_settings",
    "resolve_path_value",
]
