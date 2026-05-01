"""Deterministic device resolution for query scoping.

This module intentionally stays offline and dependency-light. Payload shapes
come from ``homewiki.schemas`` and environment/path discovery comes from
``homewiki.config`` so downstream packages can share one contract.

The production integration point is ``resolve_device(..., devices=profiles)``:
the registry from work package B can pass its listed ``DeviceProfile`` records
directly. When no device list is injected, the temporary file loader reads
``source_docs/devices/*/profile.yaml`` and falls back to fixture profiles for
offline CLI/tests.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any, Iterable

from homewiki.config import find_project_root, load_settings
from homewiki.schemas import (
    DeviceCandidate,
    DeviceProfile,
    DeviceResolution,
    ResolutionStatus,
    SearchFilters,
    normalize_model_identifier,
)


EXACT_THRESHOLD = 0.85
EXACT_GAP = 0.15
MIN_CANDIDATE_CONFIDENCE = 0.50

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_WORD_RE = re.compile(r"[a-z0-9]+")
_MATCH_ORDER = ("asset_id", "model", "brand", "alias", "device_type", "room")


def resolve_device(
    query: str,
    asset_id: str | None = None,
    devices: list[DeviceProfile] | None = None,
) -> DeviceResolution:
    """Resolve the intended device for a query.

    Explicit ``asset_id`` always wins when it exists in the provided device
    list. Inferred matches are scored conservatively so generic device phrases
    surface ambiguity instead of guessing.
    """

    available_devices = devices if devices is not None else load_device_profiles()
    device_by_id = {device.asset_id: device for device in available_devices}

    if asset_id:
        device = device_by_id.get(asset_id)
        if device is None:
            return _none()
        return DeviceResolution(
            status=ResolutionStatus.EXACT,
            asset_id=device.asset_id,
            confidence=1.0,
            matched_on=["asset_id"],
            filters=SearchFilters(asset_id=device.asset_id),
        )

    normalized_query_text = _normalized_text(query)
    if not normalized_query_text:
        return _none()

    alias_counts = _alias_counts(available_devices)
    model_tokens = extract_model_tokens(query)
    normalized_query_identifier = normalize_model_identifier(query)

    candidates: list[DeviceCandidate] = []
    for device in available_devices:
        candidate = _score_device(
            device=device,
            normalized_query_text=normalized_query_text,
            normalized_query_identifier=normalized_query_identifier,
            model_tokens=model_tokens,
            alias_counts=alias_counts,
        )
        if candidate is not None:
            candidates.append(candidate)

    if not candidates:
        return _none()

    candidates.sort(key=lambda item: (-item.confidence, item.asset_id))
    top = candidates[0]
    if top.confidence < MIN_CANDIDATE_CONFIDENCE:
        return _none()

    kept_candidates = [
        candidate
        for candidate in candidates
        if candidate.confidence >= MIN_CANDIDATE_CONFIDENCE
    ]
    second_confidence = (
        kept_candidates[1].confidence if len(kept_candidates) > 1 else 0.0
    )

    if (
        top.confidence >= EXACT_THRESHOLD
        and top.confidence - second_confidence >= EXACT_GAP
    ):
        return DeviceResolution(
            status=ResolutionStatus.EXACT,
            asset_id=top.asset_id,
            confidence=top.confidence,
            matched_on=top.matched_on,
            filters=SearchFilters(asset_id=top.asset_id),
        )

    return DeviceResolution(
        status=ResolutionStatus.AMBIGUOUS,
        confidence=top.confidence,
        matched_on=top.matched_on,
        candidates=kept_candidates,
        filters=SearchFilters(),
    )


def extract_model_tokens(query: str) -> set[str]:
    """Extract normalized model-like tokens and short adjacent token windows."""

    raw_tokens = _TOKEN_RE.findall(query)
    model_tokens: set[str] = set()

    for token in raw_tokens:
        if _is_model_like(token):
            normalized = normalize_model_identifier(token)
            if normalized:
                model_tokens.add(normalized)

    for window_size in range(2, min(5, len(raw_tokens) + 1)):
        for start in range(0, len(raw_tokens) - window_size + 1):
            window = raw_tokens[start : start + window_size]
            if not any(any(char.isdigit() for char in token) for token in window):
                continue
            normalized = normalize_model_identifier("".join(window))
            if normalized:
                model_tokens.add(normalized)

    return model_tokens


def load_device_profiles(source_docs: str | Path | None = None) -> list[DeviceProfile]:
    """Load valid profile YAML files from a ``source_docs`` tree.

    Invalid profile files are skipped with a warning so one bad entry does not
    prevent resolution against the rest of the registry.
    """

    root = _source_docs_root(source_docs)
    profiles: list[DeviceProfile] = []
    for path in sorted((root / "devices").glob("*/profile.yaml")):
        try:
            profiles.append(load_profile(path))
        except Exception as exc:  # noqa: BLE001 - skip bad file-backed profiles.
            warnings.warn(
                f"Skipping invalid device profile {path}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
    return profiles


def load_profile(path: str | Path) -> DeviceProfile:
    """Load a single file-backed ``DeviceProfile``."""

    return DeviceProfile.model_validate(_parse_profile_yaml(Path(path)))


def _score_device(
    *,
    device: DeviceProfile,
    normalized_query_text: str,
    normalized_query_identifier: str,
    model_tokens: set[str],
    alias_counts: dict[str, int],
) -> DeviceCandidate | None:
    matched_on: set[str] = set()
    confidence = 0.0

    brand_match = _contains_phrase(normalized_query_text, device.brand)
    device_type_match = _contains_phrase(normalized_query_text, device.device_type)
    room_match = (
        _contains_phrase(normalized_query_text, device.room)
        if device.room is not None
        else False
    )
    model_match = (
        device.normalized_model in model_tokens
        or device.normalized_model in normalized_query_identifier
    )

    if model_match:
        matched_on.add("model")
        confidence = max(confidence, 0.98 if brand_match else 0.95)
        if brand_match:
            matched_on.add("brand")

    matched_aliases = [
        alias
        for alias in device.aliases
        if _contains_phrase(normalized_query_text, alias)
    ]
    if matched_aliases:
        matched_on.add("alias")
        unique_alias_match = any(
            alias_counts.get(_normalized_text(alias), 0) == 1
            for alias in matched_aliases
        )
        if unique_alias_match and device_type_match:
            confidence = max(confidence, 0.85)
        elif unique_alias_match:
            confidence = max(confidence, 0.75)
        elif device_type_match:
            confidence = max(confidence, 0.65)
        else:
            confidence = max(confidence, 0.55)

    if device_type_match:
        matched_on.add("device_type")
        if room_match:
            confidence = max(confidence, 0.65)
        else:
            confidence = max(confidence, 0.55)

    if room_match:
        matched_on.add("room")
        confidence = max(confidence, 0.35)

    if brand_match:
        matched_on.add("brand")
        if device_type_match:
            confidence = max(confidence, 0.80)
        else:
            confidence = max(confidence, 0.40)

    if not matched_on:
        return None

    return DeviceCandidate(
        asset_id=device.asset_id,
        confidence=confidence,
        matched_on=_ordered_matches(matched_on),
        device_type=device.device_type,
        brand=device.brand,
        model=device.model,
        normalized_model=device.normalized_model,
        aliases=device.aliases,
        room=device.room,
    )


def _none() -> DeviceResolution:
    return DeviceResolution(
        status=ResolutionStatus.NONE,
        confidence=0.0,
        matched_on=[],
        candidates=[],
        filters=SearchFilters(),
    )


def _alias_counts(devices: Iterable[DeviceProfile]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for device in devices:
        for alias in device.aliases:
            normalized = _normalized_text(alias)
            counts[normalized] = counts.get(normalized, 0) + 1
    return counts


def _contains_phrase(normalized_text: str, phrase: str | None) -> bool:
    normalized_phrase = _normalized_text(phrase or "")
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {normalized_text} "


def _normalized_text(value: str) -> str:
    return " ".join(_WORD_RE.findall(value.lower()))


def _ordered_matches(values: Iterable[str]) -> list[str]:
    value_set = set(values)
    ordered = [value for value in _MATCH_ORDER if value in value_set]
    ordered.extend(sorted(value_set - set(_MATCH_ORDER)))
    return ordered


def _is_model_like(token: str) -> bool:
    return any(char.isdigit() for char in token) or any(
        separator in token for separator in "-_/."
    )


def _source_docs_root(source_docs: str | Path | None) -> Path:
    if source_docs is not None:
        return Path(source_docs).expanduser().resolve()

    settings = load_settings()
    configured = settings.paths.source_docs
    if (configured / "devices").exists():
        return configured

    fixture_source_docs = find_project_root() / "fixtures" / "source_docs"
    if (fixture_source_docs / "devices").exists():
        return fixture_source_docs

    return configured


def _parse_profile_yaml(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_key: str | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        if raw_line.startswith("  - "):
            if current_key is None:
                raise ValueError("list item without a preceding key")
            if data.get(current_key) is None:
                data[current_key] = []
            value = data[current_key]
            if not isinstance(value, list):
                raise ValueError(f"{current_key} is not a list")
            value.append(_parse_scalar(raw_line[4:].strip()))
            continue

        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):(.*)$", raw_line)
        if match is None:
            raise ValueError(f"unsupported YAML line: {raw_line!r}")

        key, raw_value = match.group(1), match.group(2).strip()
        current_key = key
        data[key] = [] if raw_value == "[]" else _parse_scalar(raw_value)

    return data


def _parse_scalar(value: str) -> Any:
    if value in {"", "null", "Null", "NULL", "~", "None"}:
        return None
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {'"', "'"}
    ):
        return value[1:-1]
    return value


__all__ = [
    "EXACT_GAP",
    "EXACT_THRESHOLD",
    "MIN_CANDIDATE_CONFIDENCE",
    "extract_model_tokens",
    "load_device_profiles",
    "load_profile",
    "resolve_device",
]
