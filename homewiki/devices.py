"""File-backed device profile storage and local registry helpers."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from homewiki.config import Settings, load_settings
from homewiki.schemas import (
    DeviceProfile,
    ErrorResponse,
    RegistrySyncResult,
    normalize_model_identifier,
)


PROFILE_FIELD_ORDER: tuple[str, ...] = (
    "asset_id",
    "device_type",
    "brand",
    "model",
    "normalized_model",
    "aliases",
    "room",
    "serial_number",
    "purchase_date",
    "warranty_until",
    "support_url",
    "notes",
    "tags",
    "created_at",
    "updated_at",
)

_PROFILE_FIELD_SET = set(PROFILE_FIELD_ORDER)
_SLUG_RUN_RE = re.compile(r"[^a-z0-9]+")


class DeviceStoreError(RuntimeError):
    """Base exception for device profile store failures."""


class DeviceProfileParseError(DeviceStoreError):
    """Raised when a profile YAML file cannot be parsed or validated."""


class DeviceRegistryError(DeviceStoreError):
    """Raised when the SQLite registry cannot be updated or read."""


def generate_asset_id(device_type: str, brand: str, model: str) -> str:
    """Generate the stable asset ID for a device profile."""

    parts = (
        _slugify_part(device_type, "device_type"),
        _slugify_part(brand, "brand"),
        normalize_model_identifier(model),
    )
    if not parts[2]:
        raise ValueError("model must contain at least one letter or digit")
    return "-".join(parts)


def upsert_device(
    profile: DeviceProfile, *, settings: Settings | None = None
) -> DeviceProfile:
    """Create or update profile files and the local registry."""

    resolved_settings = settings or load_settings()
    profile_dir = _profile_dir(resolved_settings, profile.asset_id)
    profile_path = profile_dir / "profile.yaml"
    markdown_path = profile_dir / "profile.md"
    profile_dir.mkdir(parents=True, exist_ok=True)

    extras: dict[str, Any] = {}
    if profile_path.exists():
        try:
            _, extras = _load_profile_mapping(profile_path)
        except DeviceProfileParseError:
            extras = {}

    _atomic_write_text(profile_path, _dump_profile_yaml(profile, extras))
    _atomic_write_text(markdown_path, render_profile_markdown(profile))

    try:
        _upsert_registry(resolved_settings, profile, profile_path, markdown_path)
    except Exception as exc:  # pragma: no cover - sqlite error shapes vary
        raise DeviceRegistryError(
            "failed to update device registry after writing profile files "
            f"{profile_path} and {markdown_path}: {exc}"
        ) from exc

    return profile


def get_device(
    asset_id: str, *, settings: Settings | None = None
) -> DeviceProfile | None:
    """Return a device profile from the registry, if present."""

    resolved_settings = settings or load_settings()
    if not resolved_settings.paths.device_registry.exists():
        return None

    try:
        with _connect_registry(resolved_settings) as connection:
            row = connection.execute(
                "SELECT * FROM devices WHERE asset_id = ?", (asset_id,)
            ).fetchone()
    except sqlite3.Error as exc:
        raise DeviceRegistryError(f"failed to read device registry: {exc}") from exc

    if row is None:
        return None
    return _profile_from_registry_row(row)


def list_devices(*, settings: Settings | None = None) -> list[DeviceProfile]:
    """List device profiles currently present in the registry."""

    resolved_settings = settings or load_settings()
    if not resolved_settings.paths.device_registry.exists():
        return []

    try:
        with _connect_registry(resolved_settings) as connection:
            rows = connection.execute(
                "SELECT * FROM devices ORDER BY asset_id"
            ).fetchall()
    except sqlite3.Error as exc:
        raise DeviceRegistryError(f"failed to read device registry: {exc}") from exc

    return [_profile_from_registry_row(row) for row in rows]


def load_profile(profile_path: Path) -> DeviceProfile:
    """Load and validate a profile YAML file."""

    data, _ = _load_profile_mapping(profile_path)
    return _validate_profile_mapping(data, profile_path)


def render_profile_markdown(profile: DeviceProfile) -> str:
    """Render deterministic Markdown suitable for indexing."""

    title = f"{profile.brand} {profile.model} {profile.device_type}".strip()
    lines = [
        f"# {title}",
        "",
        f"Asset ID: {profile.asset_id}",
        "",
        f"Device type: {profile.device_type}",
        "",
        f"Brand: {profile.brand}",
        "",
        f"Model: {profile.model}",
        "",
        f"Normalized model: {profile.normalized_model}",
        "",
        f"Room: {profile.room or 'Not specified'}",
        "",
        f"Serial number: {profile.serial_number or 'Not specified'}",
        "",
        f"Purchase date: {_markdown_value(profile.purchase_date)}",
        "",
        f"Warranty until: {_markdown_value(profile.warranty_until)}",
        "",
        f"Support URL: {profile.support_url or 'Not specified'}",
        "",
        "## Aliases",
        "",
    ]

    lines.extend(_markdown_list(profile.aliases))
    lines.extend(["", "## Tags", ""])
    lines.extend(_markdown_list(profile.tags))
    lines.extend(["", "## Notes", "", profile.notes or "Not specified", ""])
    return "\n".join(lines)


def sync_registry_from_files(
    *, settings: Settings | None = None
) -> RegistrySyncResult:
    """Rebuild or update registry rows from profile YAML files."""

    resolved_settings = settings or load_settings()
    devices_dir = resolved_settings.paths.source_docs / "devices"
    profile_paths = sorted(devices_dir.glob("*/profile.yaml"))

    loaded = 0
    updated = 0
    failed = 0
    errors: list[ErrorResponse] = []
    loaded_profiles: list[DeviceProfile] = []

    _ensure_registry(resolved_settings)

    for profile_path in profile_paths:
        try:
            profile = load_profile(profile_path)
            markdown_path = profile_path.with_name("profile.md")
            _upsert_registry(resolved_settings, profile, profile_path, markdown_path)
        except (DeviceStoreError, ValidationError, OSError, sqlite3.Error) as exc:
            failed += 1
            errors.append(
                ErrorResponse(
                    code="invalid_profile",
                    message=f"failed to sync {profile_path}: {exc}",
                    details={"path": str(profile_path)},
                )
            )
            continue

        loaded += 1
        updated += 1
        loaded_profiles.append(profile)

    errors.extend(_duplicate_model_errors(loaded_profiles))
    return RegistrySyncResult(
        loaded=loaded,
        updated=updated,
        skipped=0,
        failed=failed,
        errors=errors,
    )


def _slugify_part(value: str, field_name: str) -> str:
    slug = _SLUG_RUN_RE.sub("-", value.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise ValueError(f"{field_name} must contain at least one letter or digit")
    return slug


def _profile_dir(settings: Settings, asset_id: str) -> Path:
    return settings.paths.source_docs / "devices" / asset_id


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(content)
        os.replace(temp_name, path)
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def _dump_profile_yaml(profile: DeviceProfile, extras: dict[str, Any]) -> str:
    profile_data = profile.to_json_dict()
    lines: list[str] = []

    for field_name in PROFILE_FIELD_ORDER:
        value = profile_data[field_name]
        lines.extend(_dump_yaml_field(field_name, value))

    for key in sorted(extras):
        if key in _PROFILE_FIELD_SET:
            continue
        lines.extend(_dump_yaml_field(key, extras[key]))

    return "\n".join(lines) + "\n"


def _dump_yaml_field(key: str, value: Any) -> list[str]:
    if isinstance(value, list):
        if not value:
            return [f"{key}:"]
        return [f"{key}:"] + [f"  - {_format_scalar(item)}" for item in value]
    if value is None:
        return [f"{key}:"]
    return [f"{key}: {_format_scalar(value)}"]


def _format_scalar(value: Any) -> str:
    text = str(value)
    if (
        text == ""
        or text != text.strip()
        or "\n" in text
        or "#" in text
        or text.lower() in {"null", "none", "true", "false"}
        or ": " in text
    ):
        return json.dumps(text)
    return text


def _load_profile_mapping(profile_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_data = _parse_yaml_subset(profile_path)
    profile_data = {
        key: value for key, value in raw_data.items() if key in _PROFILE_FIELD_SET
    }
    extras = {
        key: value for key, value in raw_data.items() if key not in _PROFILE_FIELD_SET
    }
    return profile_data, extras


def _parse_yaml_subset(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_key: str | None = None

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DeviceProfileParseError(f"failed to read {path}: {exc}") from exc

    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        if raw_line.startswith("  - "):
            if current_key is None:
                raise DeviceProfileParseError(
                    f"{path}:{line_number}: list item without a key"
                )
            current = data.get(current_key)
            if current is None:
                current = []
                data[current_key] = current
            if not isinstance(current, list):
                raise DeviceProfileParseError(
                    f"{path}:{line_number}: {current_key} is not a list"
                )
            current.append(_parse_scalar(raw_line[4:].strip()))
            continue

        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*):(.*)", raw_line)
        if match is None:
            raise DeviceProfileParseError(
                f"{path}:{line_number}: unsupported YAML line {raw_line!r}"
            )

        key = match.group(1)
        value_text = match.group(2).strip()
        current_key = key
        data[key] = None if value_text == "" else _parse_scalar(value_text)

    return data


def _parse_scalar(value: str) -> Any:
    if value in {"", "null", "Null", "NULL", "None", "~"}:
        return None
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except JSONDecodeError as exc:
            raise DeviceProfileParseError(f"invalid quoted YAML value {value!r}") from exc
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def _validate_profile_mapping(data: dict[str, Any], profile_path: Path) -> DeviceProfile:
    for list_field in ("aliases", "tags"):
        if data.get(list_field) is None:
            data[list_field] = []

    try:
        return DeviceProfile.model_validate(data)
    except ValidationError as exc:
        raise DeviceProfileParseError(f"{profile_path}: {exc}") from exc


def _ensure_registry(settings: Settings) -> None:
    settings.paths.device_registry.parent.mkdir(parents=True, exist_ok=True)
    with _connect_registry(settings) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                asset_id TEXT PRIMARY KEY,
                device_type TEXT NOT NULL,
                brand TEXT NOT NULL,
                model TEXT NOT NULL,
                normalized_model TEXT NOT NULL,
                aliases_json TEXT NOT NULL,
                room TEXT,
                serial_number TEXT,
                purchase_date TEXT,
                warranty_until TEXT,
                support_url TEXT,
                notes TEXT,
                tags_json TEXT NOT NULL,
                created_at TEXT,
                updated_at TEXT,
                profile_path TEXT NOT NULL,
                markdown_path TEXT NOT NULL,
                registry_updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_devices_normalized_model
            ON devices(normalized_model)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_devices_room
            ON devices(room)
            """
        )
        connection.commit()


def _connect_registry(settings: Settings) -> sqlite3.Connection:
    connection = sqlite3.connect(settings.paths.device_registry)
    connection.row_factory = sqlite3.Row
    return connection


def _upsert_registry(
    settings: Settings,
    profile: DeviceProfile,
    profile_path: Path,
    markdown_path: Path,
) -> None:
    _ensure_registry(settings)
    data = profile.to_json_dict()
    row = {
        "asset_id": data["asset_id"],
        "device_type": data["device_type"],
        "brand": data["brand"],
        "model": data["model"],
        "normalized_model": data["normalized_model"],
        "aliases_json": json.dumps(data["aliases"], sort_keys=True),
        "room": data["room"],
        "serial_number": data["serial_number"],
        "purchase_date": data["purchase_date"],
        "warranty_until": data["warranty_until"],
        "support_url": data["support_url"],
        "notes": data["notes"],
        "tags_json": json.dumps(data["tags"], sort_keys=True),
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "profile_path": _portable_path(settings, profile_path),
        "markdown_path": _portable_path(settings, markdown_path),
        "registry_updated_at": datetime.now(timezone.utc).isoformat(),
    }

    with _connect_registry(settings) as connection:
        connection.execute(
            """
            INSERT INTO devices (
                asset_id,
                device_type,
                brand,
                model,
                normalized_model,
                aliases_json,
                room,
                serial_number,
                purchase_date,
                warranty_until,
                support_url,
                notes,
                tags_json,
                created_at,
                updated_at,
                profile_path,
                markdown_path,
                registry_updated_at
            ) VALUES (
                :asset_id,
                :device_type,
                :brand,
                :model,
                :normalized_model,
                :aliases_json,
                :room,
                :serial_number,
                :purchase_date,
                :warranty_until,
                :support_url,
                :notes,
                :tags_json,
                :created_at,
                :updated_at,
                :profile_path,
                :markdown_path,
                :registry_updated_at
            )
            ON CONFLICT(asset_id) DO UPDATE SET
                device_type = excluded.device_type,
                brand = excluded.brand,
                model = excluded.model,
                normalized_model = excluded.normalized_model,
                aliases_json = excluded.aliases_json,
                room = excluded.room,
                serial_number = excluded.serial_number,
                purchase_date = excluded.purchase_date,
                warranty_until = excluded.warranty_until,
                support_url = excluded.support_url,
                notes = excluded.notes,
                tags_json = excluded.tags_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                profile_path = excluded.profile_path,
                markdown_path = excluded.markdown_path,
                registry_updated_at = excluded.registry_updated_at
            """,
            row,
        )
        connection.commit()


def _profile_from_registry_row(row: sqlite3.Row) -> DeviceProfile:
    return DeviceProfile.model_validate(
        {
            "asset_id": row["asset_id"],
            "device_type": row["device_type"],
            "brand": row["brand"],
            "model": row["model"],
            "normalized_model": row["normalized_model"],
            "aliases": json.loads(row["aliases_json"]),
            "room": row["room"],
            "serial_number": row["serial_number"],
            "purchase_date": row["purchase_date"],
            "warranty_until": row["warranty_until"],
            "support_url": row["support_url"],
            "notes": row["notes"],
            "tags": json.loads(row["tags_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )


def _portable_path(settings: Settings, path: Path) -> str:
    try:
        return str(path.relative_to(settings.paths.project_root))
    except ValueError:
        return str(path)


def _markdown_value(value: Any) -> str:
    if value is None:
        return "Not specified"
    return str(value)


def _markdown_list(values: list[str]) -> list[str]:
    if not values:
        return ["Not specified"]
    return [f"- {value}" for value in values]


def _duplicate_model_errors(profiles: list[DeviceProfile]) -> list[ErrorResponse]:
    by_model: dict[str, list[str]] = defaultdict(list)
    for profile in profiles:
        by_model[profile.normalized_model].append(profile.asset_id)

    errors: list[ErrorResponse] = []
    for normalized_model, asset_ids in sorted(by_model.items()):
        unique_asset_ids = sorted(set(asset_ids))
        if len(unique_asset_ids) < 2:
            continue
        errors.append(
            ErrorResponse(
                code="duplicate_normalized_model",
                message=(
                    f"normalized model {normalized_model!r} appears in multiple "
                    "device profiles"
                ),
                details={
                    "normalized_model": normalized_model,
                    "asset_ids": unique_asset_ids,
                },
            )
        )
    return errors


__all__ = [
    "DeviceProfileParseError",
    "DeviceRegistryError",
    "DeviceStoreError",
    "generate_asset_id",
    "get_device",
    "list_devices",
    "load_profile",
    "render_profile_markdown",
    "sync_registry_from_files",
    "upsert_device",
]
