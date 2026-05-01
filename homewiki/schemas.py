"""Shared JSON-serializable contracts for Home Wiki packages.

The models in this module are intentionally implementation-neutral. They do
not import LanceDB, model clients, web frameworks, or filesystem services.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ASSET_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


class SourceType(str, Enum):
    PROFILE = "profile"
    MANUAL = "manual"
    NOTE = "note"
    RECEIPT = "receipt"
    PHOTO_OCR = "photo_ocr"
    OTHER = "other"


class ResolutionStatus(str, Enum):
    EXACT = "exact"
    AMBIGUOUS = "ambiguous"
    NONE = "none"


class SearchScope(str, Enum):
    DEVICE = "device"
    FILTERED = "filtered"
    GLOBAL = "global"
    NONE = "none"


class AgentAction(str, Enum):
    SEARCH = "search"
    ASK = "ask"
    MANUAL_FIND = "manual_find"
    MANUAL_DOWNLOAD = "manual_download"
    INGEST = "ingest"
    ADD_DEVICE = "add_device"
    LIST_DEVICES = "list_devices"
    INCIDENT = "incident"


class AgentStepStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class EmbeddingProvider(str, Enum):
    LOCAL_GGUF = "local_gguf"
    OPENAI_COMPATIBLE = "openai_compatible"
    FAKE = "fake"


class ChatProvider(str, Enum):
    CODEX_CLI = "codex_cli"
    OPENAI_COMPATIBLE = "openai_compatible"
    LM_STUDIO_OPENAI = "lmstudio_openai"
    DISABLED = "disabled"


class ConversionStatus(str, Enum):
    CONVERTED = "converted"
    COPIED = "copied"
    SKIPPED = "skipped"
    FAILED = "failed"


class ContractModel(BaseModel):
    """Base model with strict fields and JSON-friendly dumping."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class DeviceProfile(ContractModel):
    asset_id: str = Field(min_length=1)
    device_type: str = Field(min_length=1)
    brand: str = Field(min_length=1)
    model: str = Field(min_length=1)
    normalized_model: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    room: str | None = None
    serial_number: str | None = None
    purchase_date: date | None = None
    warranty_until: date | None = None
    support_url: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id(cls, value: str) -> str:
        if not is_safe_asset_id(value):
            raise ValueError(
                "asset_id must use lowercase letters, numbers, and hyphens"
            )
        return value

    @field_validator(
        "room",
        "serial_number",
        "support_url",
        "notes",
        mode="before",
    )
    @classmethod
    def blank_optional_string_to_none(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

    @field_validator("aliases", "tags")
    @classmethod
    def reject_blank_list_items(cls, values: list[str]) -> list[str]:
        if any(not item for item in values):
            raise ValueError("list items must be non-empty strings")
        return values

    @model_validator(mode="after")
    def validate_normalized_model(self) -> "DeviceProfile":
        expected = normalize_model_identifier(self.model)
        if self.normalized_model != expected:
            raise ValueError(
                f"normalized_model must be {expected!r} for model {self.model!r}"
            )
        return self


class DeviceDocument(ContractModel):
    source_type: SourceType
    name: str = Field(min_length=1)
    source_path: str | None = None
    markdown_path: str | None = None
    available_as_markdown: bool = False
    size_bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_document_has_path(self) -> "DeviceDocument":
        if self.source_path is None and self.markdown_path is None:
            raise ValueError("device document requires source_path or markdown_path")
        return self


class DeviceInformationResponse(ContractModel):
    device: DeviceProfile
    documents: list[DeviceDocument] = Field(default_factory=list)


class SearchFilters(ContractModel):
    asset_id: str | None = None
    normalized_model: str | None = None
    device_type: str | None = None
    room: str | None = None
    source_type: SourceType | None = None

    @field_validator("asset_id")
    @classmethod
    def validate_optional_asset_id(cls, value: str | None) -> str | None:
        if value is not None and not is_safe_asset_id(value):
            raise ValueError(
                "asset_id must use lowercase letters, numbers, and hyphens"
            )
        return value

    def is_empty(self) -> bool:
        return all(value is None for value in self.model_dump().values())


class DeviceCandidate(ContractModel):
    asset_id: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    matched_on: list[str] = Field(default_factory=list)
    device_type: str | None = None
    brand: str | None = None
    model: str | None = None
    normalized_model: str | None = None
    aliases: list[str] = Field(default_factory=list)
    room: str | None = None

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id(cls, value: str) -> str:
        if not is_safe_asset_id(value):
            raise ValueError(
                "asset_id must use lowercase letters, numbers, and hyphens"
            )
        return value


class DeviceResolution(ContractModel):
    status: ResolutionStatus
    asset_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    matched_on: list[str] = Field(default_factory=list)
    candidates: list[DeviceCandidate] = Field(default_factory=list)
    filters: SearchFilters = Field(default_factory=SearchFilters)

    @field_validator("asset_id")
    @classmethod
    def validate_optional_asset_id(cls, value: str | None) -> str | None:
        if value is not None and not is_safe_asset_id(value):
            raise ValueError(
                "asset_id must use lowercase letters, numbers, and hyphens"
            )
        return value

    @model_validator(mode="after")
    def validate_status_shape(self) -> "DeviceResolution":
        if self.status == ResolutionStatus.EXACT and self.asset_id is None:
            raise ValueError("exact device resolution requires asset_id")
        if self.status != ResolutionStatus.EXACT and self.asset_id is not None:
            raise ValueError("only exact device resolution may include asset_id")
        return self


class DocumentMetadata(ContractModel):
    asset_id: str | None = None
    source_type: SourceType
    brand: str | None = None
    model: str | None = None
    normalized_model: str | None = None
    device_type: str | None = None
    room: str | None = None
    source_path: str
    markdown_path: str
    tags: list[str] = Field(default_factory=list)


class IndexChunk(ContractModel):
    text: str = Field(min_length=1)
    asset_id: str | None = None
    source_type: SourceType
    brand: str | None = None
    model: str | None = None
    normalized_model: str | None = None
    device_type: str | None = None
    room: str | None = None
    source_path: str = Field(min_length=1)
    markdown_path: str = Field(min_length=1)
    section_title: str
    chunk_index: int = Field(ge=0)
    content_hash: str = Field(min_length=1)
    modified_at: datetime | float
    tags: list[str] = Field(default_factory=list)


class SearchResult(ContractModel):
    text: str = Field(min_length=1)
    score: float | None = None
    asset_id: str | None = None
    source_type: SourceType
    brand: str | None = None
    model: str | None = None
    normalized_model: str | None = None
    device_type: str | None = None
    room: str | None = None
    source_path: str = Field(min_length=1)
    markdown_path: str = Field(min_length=1)
    section_title: str
    chunk_index: int | None = Field(default=None, ge=0)
    content_hash: str | None = None
    modified_at: datetime | float | None = None
    tags: list[str] = Field(default_factory=list)


class SearchRequest(ContractModel):
    query: str = Field(min_length=1)
    asset_id: str | None = None
    filters: SearchFilters | None = None
    limit: int = Field(default=8, ge=1, le=50)
    allow_global_fallback: bool = True

    @field_validator("asset_id")
    @classmethod
    def validate_optional_asset_id(cls, value: str | None) -> str | None:
        if value is not None and not is_safe_asset_id(value):
            raise ValueError(
                "asset_id must use lowercase letters, numbers, and hyphens"
            )
        return value


class SearchResponse(ContractModel):
    query: str
    resolution: DeviceResolution
    scope: SearchScope
    results: list[SearchResult] = Field(default_factory=list)


class AskRequest(ContractModel):
    question: str = Field(min_length=1)
    asset_id: str | None = None
    limit: int = Field(default=8, ge=1, le=50)
    allow_global_fallback: bool = False

    @field_validator("asset_id")
    @classmethod
    def validate_optional_asset_id(cls, value: str | None) -> str | None:
        if value is not None and not is_safe_asset_id(value):
            raise ValueError(
                "asset_id must use lowercase letters, numbers, and hyphens"
            )
        return value


class AskResponse(ContractModel):
    answer: str
    resolution: DeviceResolution
    sources: list[str] = Field(default_factory=list)
    evidence: list[SearchResult] = Field(default_factory=list)
    confidence: int = Field(ge=0, le=10)
    generated: bool
    missing_information: list[str] = Field(default_factory=list)


class ManualFindRequest(ContractModel):
    asset_id: str | None = None
    query: str | None = None
    limit: int = Field(default=5, ge=1, le=20)

    @field_validator("asset_id")
    @classmethod
    def validate_optional_asset_id(cls, value: str | None) -> str | None:
        if value is not None and not is_safe_asset_id(value):
            raise ValueError("asset_id must use lowercase letters, numbers, and hyphens")
        return value

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None

    @model_validator(mode="after")
    def require_scope(self) -> "ManualFindRequest":
        if not self.asset_id and not self.query:
            raise ValueError("manual find requires asset_id or query")
        return self


class ManualDownloadRequest(ContractModel):
    asset_id: str
    url: str = Field(min_length=1)

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id(cls, value: str) -> str:
        if not is_safe_asset_id(value):
            raise ValueError(
                "asset_id must use lowercase letters, numbers, and hyphens"
            )
        return value


class DeviceCreateResponse(ContractModel):
    device: DeviceProfile


class ManualCandidate(ContractModel):
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    source_host: str | None = None
    is_pdf: bool
    rank: int = Field(ge=1)


class ManualSearchResult(ContractModel):
    query: str
    candidates: list[ManualCandidate] = Field(default_factory=list)


class ManualDownloadResult(ContractModel):
    asset_id: str
    url: str
    saved_path: str | None = None
    sidecar_path: str | None = None
    downloaded: bool
    error: str | None = None


class ErrorResponse(ContractModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, Any] | None = None


class AgentExecuteRequest(ContractModel):
    input: str = Field(min_length=1)


class IncidentRequest(ContractModel):
    asset_id: str
    fault_code: str = Field(min_length=1)
    symptom: str | None = None

    @field_validator("asset_id")
    @classmethod
    def validate_asset_id(cls, value: str) -> str:
        if not is_safe_asset_id(value):
            raise ValueError(
                "asset_id must use lowercase letters, numbers, and hyphens"
            )
        return value


class AgentToolCall(ContractModel):
    action: AgentAction
    inputs: dict[str, Any] = Field(default_factory=dict)


class AgentPlanStep(ContractModel):
    order: int = Field(ge=1)
    intent: str = Field(min_length=1)
    tool_call: AgentToolCall


class AgentExecutionStep(ContractModel):
    order: int = Field(ge=1)
    intent: str = Field(min_length=1)
    tool_call: AgentToolCall
    status: AgentStepStatus
    result: dict[str, Any] | None = None
    error: ErrorResponse | None = None


class AgentExecuteResponse(ContractModel):
    input: str
    plan: list[AgentPlanStep] = Field(default_factory=list)
    steps: list[AgentExecutionStep] = Field(default_factory=list)
    result: dict[str, Any] | None = None


class FileConversionResult(ContractModel):
    source_path: str
    markdown_path: str | None = None
    status: ConversionStatus
    error: str | None = None


class ConversionReport(ContractModel):
    converted: int = Field(default=0, ge=0)
    copied: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    files: list[FileConversionResult] = Field(default_factory=list)


class IndexResult(ContractModel):
    indexed: int = Field(default=0, ge=0)
    deleted: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    errors: list["ErrorResponse"] = Field(default_factory=list)


class IngestReport(ContractModel):
    converted: int = Field(default=0, ge=0)
    indexed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    removed: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    errors: list["ErrorResponse"] = Field(default_factory=list)


class RegistrySyncResult(ContractModel):
    loaded: int = Field(default=0, ge=0)
    updated: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    errors: list["ErrorResponse"] = Field(default_factory=list)


class ProviderSettings(ContractModel):
    embedding_provider: EmbeddingProvider
    embedding_api_base: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    gguf_model_repo: str = ""
    gguf_model_file: str = ""
    gguf_n_ctx: int = Field(default=8192, ge=1)
    gguf_n_threads: int = Field(default=4, ge=1)
    chat_provider: ChatProvider = ChatProvider.DISABLED
    chat_api_base: str = ""
    chat_api_key: str = ""
    chat_model: str = ""


def normalize_model_identifier(value: str) -> str:
    """Normalize model strings for comparison and retrieval filters."""

    return "".join(char.lower() for char in value if char.isalnum())


def is_safe_asset_id(value: str) -> bool:
    """Return true when a value is safe for URLs and folder names."""

    return bool(ASSET_ID_PATTERN.fullmatch(value))


__all__ = [
    "AgentAction",
    "AgentExecuteRequest",
    "AgentExecuteResponse",
    "AgentExecutionStep",
    "AgentPlanStep",
    "AgentStepStatus",
    "AgentToolCall",
    "DeviceCreateResponse",
    "AskRequest",
    "AskResponse",
    "ChatProvider",
    "ContractModel",
    "ConversionReport",
    "ConversionStatus",
    "DeviceCandidate",
    "DeviceDocument",
    "DeviceInformationResponse",
    "DeviceProfile",
    "DeviceResolution",
    "DocumentMetadata",
    "EmbeddingProvider",
    "ErrorResponse",
    "FileConversionResult",
    "IncidentRequest",
    "IndexChunk",
    "IndexResult",
    "IngestReport",
    "ManualCandidate",
    "ManualDownloadRequest",
    "ManualDownloadResult",
    "ManualFindRequest",
    "ManualSearchResult",
    "ProviderSettings",
    "RegistrySyncResult",
    "ResolutionStatus",
    "SearchFilters",
    "SearchRequest",
    "SearchResponse",
    "SearchResult",
    "SearchScope",
    "SourceType",
    "is_safe_asset_id",
    "normalize_model_identifier",
]
