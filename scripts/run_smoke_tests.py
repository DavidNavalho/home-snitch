#!/usr/bin/env python3
"""Offline fixture smoke tests for Phase 0 package K.

This script intentionally avoids project imports and third-party packages. It is
an executable contract for the fixture set while production modules are still
being built.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
SOURCE_DOCS = FIXTURES / "source_docs"
MARKDOWN_DOCS = FIXTURES / "markdown_docs"
WEB_FIXTURES = FIXTURES / "web"
API_FIXTURES = FIXTURES / "api"
EXPECTED_FIXTURES = FIXTURES / "expected"

REQUIRED_PROFILE_FIELDS = {
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
}

WORK_PACKAGES = set("ABCDEFGHIJKLM")


class SmokeSkip(Exception):
    """A check is intentionally skipped because optional dependencies are absent."""


class FixtureLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._current_href: str | None = None
        self._current_text: list[str] = []
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {key: value for key, value in attrs}
        href = attr_map.get("href")
        if href:
            self._current_href = href
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._current_href is None:
            return
        title = " ".join(" ".join(self._current_text).split())
        self.links.append({"title": title, "url": self._current_href})
        self._current_href = None
        self._current_text = []


@dataclass(frozen=True)
class Check:
    name: str
    func: Any


def normalize_model(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(read_text(path))


def parse_fixture_yaml(path: Path) -> dict[str, Any]:
    """Parse the tiny YAML subset used by fixture profiles."""
    data: dict[str, Any] = {}
    current_key: str | None = None

    for raw_line in read_text(path).splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        if raw_line.startswith("  - "):
            assert_true(current_key is not None, f"{path}: list item without key")
            if data.get(current_key) is None:
                data[current_key] = []
            assert_true(isinstance(data[current_key], list), f"{path}: {current_key} is not a list")
            data[current_key].append(raw_line[4:].strip())
            continue

        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):(.*)$", raw_line)
        assert_true(match is not None, f"{path}: unsupported YAML line {raw_line!r}")
        key, value = match.group(1), match.group(2).strip()
        current_key = key
        if value in {"", "null", "None"}:
            data[key] = None
        else:
            data[key] = value.strip('"').strip("'")

    return data


def load_profiles() -> list[dict[str, Any]]:
    profile_paths = sorted((SOURCE_DOCS / "devices").glob("*/profile.yaml"))
    return [parse_fixture_yaml(path) | {"_path": path} for path in profile_paths]


def infer_source_type(path: Path) -> str:
    parts = path.parts
    if path.name == "profile.md":
        return "profile"
    if "manuals" in parts:
        return "manual"
    if "notes" in parts:
        return "note"
    if "receipts" in parts:
        return "receipt"
    return "other"


def split_markdown_sections(path: Path) -> list[dict[str, Any]]:
    lines = read_text(path).splitlines()
    sections: list[dict[str, Any]] = []
    headings: list[str] = []
    current_title = "Introduction"
    current_lines: list[str] = []
    in_frontmatter = bool(lines and lines[0] == "---")

    def flush() -> None:
        text = "\n".join(line for line in current_lines).strip()
        if text:
            sections.append(
                {
                    "markdown_path": str(path.relative_to(ROOT)),
                    "asset_id": path.relative_to(MARKDOWN_DOCS).parts[1],
                    "source_type": infer_source_type(path),
                    "section_title": current_title,
                    "text": text,
                }
            )

    for line in lines:
        if in_frontmatter:
            if line == "---" and current_lines:
                in_frontmatter = False
                current_lines = []
            else:
                current_lines.append(line)
            continue

        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            flush()
            current_lines = []
            level = len(match.group(1))
            title = match.group(2)
            headings = headings[: level - 1]
            headings.append(title)
            current_title = " > ".join(headings) if headings else "Introduction"
            continue
        current_lines.append(line)

    flush()
    return sections


def load_chunks() -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for path in sorted(MARKDOWN_DOCS.glob("devices/**/*.md")):
        chunks.extend(split_markdown_sections(path))
    return chunks


def profile_by_asset_id() -> dict[str, dict[str, Any]]:
    return {profile["asset_id"]: profile for profile in load_profiles()}


def fixture_resolve_device(query: str, asset_id: str | None = None) -> dict[str, Any]:
    profiles = load_profiles()
    profile_by_id = {profile["asset_id"]: profile for profile in profiles}

    if asset_id:
        profile = profile_by_id.get(asset_id)
        if not profile:
            return resolution("none", None, 0.0, [], [])
        return resolution("exact", asset_id, 1.0, ["asset_id"], [])

    normalized_query = normalize_model(query)
    lower_query = query.lower()
    candidates: list[dict[str, Any]] = []

    for profile in profiles:
        matched_on: list[str] = []
        confidence = 0.0

        if profile["normalized_model"] in normalized_query:
            matched_on.append("model")
            confidence = max(confidence, 0.95)

        aliases = profile.get("aliases") or []
        if any(alias.lower() in lower_query for alias in aliases):
            matched_on.append("alias")
            confidence = max(confidence, 0.75)

        if profile["device_type"].lower() in lower_query:
            matched_on.append("device_type")
            confidence = max(confidence, 0.65)

        if profile["brand"].lower() in lower_query:
            matched_on.append("brand")
            confidence = max(confidence, 0.4)

        if matched_on:
            candidates.append(candidate(profile, confidence, matched_on))

    if not candidates:
        return resolution("none", None, 0.0, [], [])

    candidates.sort(key=lambda item: item["confidence"], reverse=True)
    top = candidates[0]
    second_confidence = candidates[1]["confidence"] if len(candidates) > 1 else 0.0

    if top["confidence"] >= 0.85 and top["confidence"] - second_confidence >= 0.15:
        return resolution("exact", top["asset_id"], top["confidence"], top["matched_on"], [])

    return resolution("ambiguous", None, top["confidence"], top["matched_on"], candidates)


def candidate(profile: dict[str, Any], confidence: float, matched_on: list[str]) -> dict[str, Any]:
    return {
        "asset_id": profile["asset_id"],
        "brand": profile["brand"],
        "model": profile["model"],
        "device_type": profile["device_type"],
        "room": profile["room"],
        "confidence": confidence,
        "matched_on": sorted(set(matched_on)),
    }


def resolution(
    status: str,
    asset_id: str | None,
    confidence: float,
    matched_on: list[str],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": status,
        "asset_id": asset_id,
        "confidence": confidence,
        "matched_on": sorted(set(matched_on)),
        "candidates": candidates,
        "filters": {
            "asset_id": asset_id if status == "exact" else None,
            "normalized_model": None,
            "device_type": None,
            "room": None,
            "source_type": None,
        },
    }


def fixture_search(query: str, asset_id: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
    query_lower = query.lower()
    results: list[dict[str, Any]] = []
    for chunk in load_chunks():
        if asset_id and chunk["asset_id"] != asset_id:
            continue
        text_lower = chunk["text"].lower()
        section_lower = chunk["section_title"].lower()
        if query_lower not in text_lower and query_lower not in section_lower:
            continue
        score = 1.0 if query_lower in section_lower else 0.9
        score += text_lower.count(query_lower) * 0.1
        results.append(chunk | {"score": score})

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]


def parse_manual_candidates(path: Path) -> list[dict[str, Any]]:
    parser = FixtureLinkParser()
    parser.feed(read_text(path))
    candidates: list[dict[str, Any]] = []

    for rank, link in enumerate(parser.links, start=1):
        url = link["url"]
        title = link["title"]
        parsed = urlparse(url)
        is_pdf = parsed.path.lower().endswith(".pdf")
        candidates.append(
            {
                "title": title,
                "url": url,
                "source_host": parsed.netloc or None,
                "is_pdf": is_pdf,
                "rank": rank,
            }
        )

    candidates.sort(key=lambda item: (not item["is_pdf"], item["rank"]))
    for rank, candidate_item in enumerate(candidates, start=1):
        candidate_item["rank"] = rank
    return candidates


def check_fixture_layout() -> None:
    required_paths = [
        SOURCE_DOCS / "devices/dishwasher-bosch-sms6zcw00g/profile.yaml",
        SOURCE_DOCS / "devices/dishwasher-bosch-sms6zcw00g/profile.md",
        SOURCE_DOCS / "devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md",
        SOURCE_DOCS / "devices/dishwasher-siemens-sn23ec14cg/profile.yaml",
        SOURCE_DOCS / "devices/dishwasher-siemens-sn23ec14cg/profile.md",
        SOURCE_DOCS / "devices/dishwasher-siemens-sn23ec14cg/manuals/quick-manual.md",
        SOURCE_DOCS / "devices/router-asus-rt-ax88u/profile.yaml",
        SOURCE_DOCS / "devices/router-asus-rt-ax88u/profile.md",
        SOURCE_DOCS / "devices/router-asus-rt-ax88u/notes/admin-notes.md",
        WEB_FIXTURES / "duckduckgo-manual-search.html",
        WEB_FIXTURES / "manual.pdf",
        EXPECTED_FIXTURES / "scenarios.json",
    ]
    for path in required_paths:
        assert_true(path.exists(), f"missing required fixture: {path.relative_to(ROOT)}")


def check_profile_schema_fixtures() -> None:
    profiles = load_profiles()
    assert_true(len(profiles) == 3, "expected exactly three fixture device profiles")

    for profile in profiles:
        path = profile["_path"]
        missing = REQUIRED_PROFILE_FIELDS - set(profile)
        assert_true(not missing, f"{path}: missing fields {sorted(missing)}")
        assert_true(
            re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", profile["asset_id"]) is not None,
            f"{path}: asset_id is not file-safe",
        )
        assert_true(path.parent.name == profile["asset_id"], f"{path}: asset_id does not match folder")
        assert_true(
            profile["normalized_model"] == normalize_model(profile["model"]),
            f"{path}: normalized_model does not match model",
        )
        assert_true(isinstance(profile["aliases"], list) and profile["aliases"], f"{path}: aliases missing")
        assert_true(isinstance(profile["tags"], list), f"{path}: tags must be a list")


def check_shared_a_schema_contracts() -> None:
    try:
        from homewiki.config import load_settings
        from homewiki.schemas import (
            AskResponse,
            DeviceProfile,
            DeviceResolution,
            DocumentMetadata,
            ErrorResponse,
            IndexChunk,
            ManualCandidate,
            ManualSearchResult,
            SearchResponse,
            SourceType,
        )
    except ModuleNotFoundError as exc:
        if exc.name in {"homewiki", "pydantic"}:
            raise SmokeSkip(
                "shared A schemas are unavailable; install project test dependencies"
            ) from exc
        raise

    settings = load_settings(environ={}, project_root=ROOT)
    assert_true(settings.embedding.provider == "fake", "A defaults must use fake embeddings")
    assert_true(settings.chat.provider == "disabled", "A defaults must disable chat")

    profiles = profile_by_asset_id()
    for profile in profiles.values():
        data = {key: value for key, value in profile.items() if not key.startswith("_")}
        DeviceProfile.model_validate(data)

    for resolution_payload in (
        fixture_resolve_device("What does E15 mean on SMS6ZCW00G?"),
        fixture_resolve_device("dishwasher error code"),
        fixture_resolve_device("where is the stopcock?"),
    ):
        DeviceResolution.model_validate(resolution_payload)

    for path in sorted(MARKDOWN_DOCS.glob("devices/**/*.md")):
        asset_id = path.relative_to(MARKDOWN_DOCS).parts[1]
        profile = profiles[asset_id]
        source_type = SourceType(infer_source_type(path))
        metadata = DocumentMetadata(
            asset_id=asset_id,
            source_type=source_type,
            brand=profile["brand"],
            model=profile["model"],
            normalized_model=profile["normalized_model"],
            device_type=profile["device_type"],
            room=profile["room"],
            source_path=str(path.relative_to(ROOT)).replace("fixtures/markdown_docs", "fixtures/source_docs"),
            markdown_path=str(path.relative_to(ROOT)),
            tags=profile["tags"],
        )

        for chunk_index, chunk in enumerate(split_markdown_sections(path)):
            IndexChunk(
                text=chunk["text"],
                asset_id=metadata.asset_id,
                source_type=metadata.source_type,
                brand=metadata.brand,
                model=metadata.model,
                normalized_model=metadata.normalized_model,
                device_type=metadata.device_type,
                room=metadata.room,
                source_path=metadata.source_path,
                markdown_path=metadata.markdown_path,
                section_title=chunk["section_title"],
                chunk_index=chunk_index,
                content_hash=sha256(chunk["text"].encode("utf-8")).hexdigest(),
                modified_at=0.0,
                tags=metadata.tags,
            )

    SearchResponse.model_validate(load_json(API_FIXTURES / "search-ambiguous-dishwasher.json"))
    SearchResponse.model_validate(load_json(API_FIXTURES / "search-scoped-bosch-e15.json"))
    AskResponse.model_validate(load_json(API_FIXTURES / "ask-evidence-only-bosch-e15.json"))
    ErrorResponse.model_validate(load_json(API_FIXTURES / "api-error.json")["error"])

    manual_candidates = [
        ManualCandidate.model_validate(candidate_item)
        for candidate_item in parse_manual_candidates(WEB_FIXTURES / "duckduckgo-manual-search.html")
    ]
    ManualSearchResult(query="Bosch SMS6ZCW00G dishwasher manual pdf", candidates=manual_candidates)


def check_manual_content_contracts() -> None:
    bosch = read_text(SOURCE_DOCS / "devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md")
    assert_true("## Troubleshooting" in bosch, "Bosch manual missing Troubleshooting heading")
    assert_true("### Error Codes" in bosch, "Bosch manual missing Error Codes heading")
    assert_true("#### E15" in bosch, "Bosch manual missing E15 heading")
    assert_true("water protection system" in bosch, "Bosch E15 meaning missing water protection")
    assert_true("base area" in bosch, "Bosch E15 meaning missing base area")
    assert_true("turn off the water supply" in bosch, "Bosch safe guidance missing water shutoff")
    assert_true("contact Bosch service" in bosch, "Bosch safe guidance missing service contact")
    for unsupported in ["remove the base", "tilt the dishwasher", "replace the pump"]:
        assert_true(unsupported not in bosch.lower(), f"Bosch fixture contains unsupported step: {unsupported}")

    siemens = read_text(SOURCE_DOCS / "devices/dishwasher-siemens-sn23ec14cg/manuals/quick-manual.md")
    assert_true("#### E24" in siemens, "Siemens manual missing different error code E24")
    assert_true("#### E15" not in siemens, "Siemens manual should not define E15")

    router = read_text(SOURCE_DOCS / "devices/router-asus-rt-ax88u/notes/admin-notes.md")
    assert_true("http://router.asus.com" in router, "Router notes missing admin URL")
    assert_true("Factory reset can erase" in router, "Router notes missing reset caution")


def check_markdown_conversion_contracts() -> None:
    converted = MARKDOWN_DOCS / "devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md"
    text = read_text(converted)
    assert_true(text.startswith("---\n"), "Converted Bosch manual fixture missing frontmatter")
    assert_true("source_type: manual" in text, "Converted Bosch manual fixture missing source_type")
    assert_true("asset_id: dishwasher-bosch-sms6zcw00g" in text, "Converted fixture missing asset_id")
    assert_true("E15 means" in text, "Converted fixture did not preserve E15 content")


def check_chunking_contracts() -> None:
    chunks = load_chunks()
    e15_chunks = [
        chunk
        for chunk in chunks
        if chunk["asset_id"] == "dishwasher-bosch-sms6zcw00g" and "E15 means" in chunk["text"]
    ]
    assert_true(e15_chunks, "No Bosch E15 chunk found")
    assert_true(
        any("Troubleshooting > Error Codes" in chunk["section_title"] for chunk in e15_chunks),
        "Bosch E15 chunk missing Troubleshooting > Error Codes breadcrumb",
    )
    assert_true(all(chunk["source_type"] == "manual" for chunk in e15_chunks), "E15 chunks must be manual chunks")


def check_resolver_scenarios() -> None:
    exact = fixture_resolve_device("What does E15 mean on SMS6ZCW00G?")
    assert_true(exact["status"] == "exact", f"K1 expected exact, got {exact['status']}")
    assert_true(exact["asset_id"] == "dishwasher-bosch-sms6zcw00g", "K1 resolved wrong asset")
    assert_true("model" in exact["matched_on"], "K1 did not match on model")
    assert_true(exact["confidence"] >= 0.9, "K1 confidence below 0.9")

    spaced = fixture_resolve_device("What does E15 mean on SMS 6ZCW-00G?")
    assert_true(spaced["status"] == "exact", "F1 spaced model query did not resolve exactly")
    assert_true(spaced["asset_id"] == "dishwasher-bosch-sms6zcw00g", "F1 resolved wrong asset")

    explicit = fixture_resolve_device("E15", asset_id="dishwasher-bosch-sms6zcw00g")
    assert_true(explicit["status"] == "exact", "Explicit asset resolution did not return exact")
    assert_true(explicit["confidence"] == 1.0, "Explicit asset confidence must be 1.0")

    ambiguous = fixture_resolve_device("dishwasher error code")
    candidate_ids = {item["asset_id"] for item in ambiguous["candidates"]}
    assert_true(ambiguous["status"] == "ambiguous", f"K2 expected ambiguous, got {ambiguous['status']}")
    assert_true(
        {"dishwasher-bosch-sms6zcw00g", "dishwasher-siemens-sn23ec14cg"}.issubset(candidate_ids),
        "K2 missing Bosch or Siemens dishwasher candidate",
    )
    assert_true(ambiguous["filters"]["asset_id"] is None, "Ambiguous resolver must not return asset filter")


def check_search_and_ask_contracts() -> None:
    results = fixture_search("E15", asset_id="dishwasher-bosch-sms6zcw00g")
    assert_true(results, "K3 scoped search returned no results")
    assert_true(
        all(result["asset_id"] == "dishwasher-bosch-sms6zcw00g" for result in results),
        "K3 scoped search returned another asset",
    )
    top = results[0]
    assert_true("Troubleshooting" in top["section_title"], "K3 top result missing Troubleshooting section")
    assert_true("E15" in top["text"] or "E15" in top["section_title"], "K3 top result missing E15")

    evidence = fixture_search("E15", asset_id="dishwasher-bosch-sms6zcw00g", limit=1)
    answer = "Chat is disabled. Retrieved evidence says E15 means the water protection system has been activated or water has been detected in the base area."
    assert_true(evidence, "K4 evidence-only ask has no evidence")
    assert_true("water protection system" in answer, "K4 evidence answer missing expected meaning")
    for unsupported in ["remove the base", "tilt", "replace the pump"]:
        assert_true(unsupported not in answer.lower(), f"K4 answer contains unsupported step: {unsupported}")


def check_manual_parser_contracts() -> None:
    candidates = parse_manual_candidates(WEB_FIXTURES / "duckduckgo-manual-search.html")
    assert_true(candidates, "K5 manual parser found no candidates")
    top = candidates[0]
    assert_true(top["is_pdf"] is True, "K5 top manual candidate is not a direct PDF")
    assert_true(top["url"].endswith(".pdf"), "K5 top manual candidate URL is not a PDF URL")
    title_lower = top["title"].lower()
    for term in ["bosch", "sms6zcw00g", "manual"]:
        assert_true(term in title_lower, f"K5 top candidate title missing {term}")

    pdf_bytes = (WEB_FIXTURES / "manual.pdf").read_bytes()
    assert_true(pdf_bytes.startswith(b"%PDF"), "Fixture PDF does not start with %PDF")


def check_api_mock_contracts() -> None:
    devices = load_json(API_FIXTURES / "devices-list.json")["devices"]
    assert_true(len(devices) == 3, "Device list mock should include three devices")

    ambiguous = load_json(API_FIXTURES / "search-ambiguous-dishwasher.json")
    assert_true(ambiguous["resolution"]["status"] == "ambiguous", "Ambiguous search mock status mismatch")
    assert_true(ambiguous["results"] == [], "Ambiguous search mock must not include results")
    candidate_ids = {item["asset_id"] for item in ambiguous["resolution"]["candidates"]}
    assert_true("dishwasher-bosch-sms6zcw00g" in candidate_ids, "Ambiguous mock missing Bosch")
    assert_true("dishwasher-siemens-sn23ec14cg" in candidate_ids, "Ambiguous mock missing Siemens")

    scoped = load_json(API_FIXTURES / "search-scoped-bosch-e15.json")
    assert_true(scoped["scope"] == "device", "Scoped search mock must have device scope")
    assert_true(scoped["results"], "Scoped search mock missing results")
    assert_true(
        all(item["asset_id"] == "dishwasher-bosch-sms6zcw00g" for item in scoped["results"]),
        "Scoped search mock contains wrong asset",
    )

    ask = load_json(API_FIXTURES / "ask-evidence-only-bosch-e15.json")
    assert_true(ask["generated"] is False, "Ask evidence-only mock must not be generated")
    assert_true(ask["evidence"], "Ask evidence-only mock missing evidence")
    assert_true(ask["sources"], "Ask evidence-only mock missing sources")

    error = load_json(API_FIXTURES / "api-error.json")
    assert_true({"code", "message"}.issubset(error["error"]), "API error mock missing code/message")


def check_expected_scenarios_contract() -> None:
    scenarios = load_json(EXPECTED_FIXTURES / "scenarios.json")
    assert_true(
        scenarios["optional_test_flags"] == {
            "model": "RUN_MODEL_TESTS",
            "web": "RUN_WEB_TESTS",
            "network": "RUN_NETWORK_TESTS",
        },
        "Optional test flags contract changed unexpectedly",
    )

    package_ids = set(scenarios["work_packages"])
    assert_true(WORK_PACKAGES.issubset(package_ids), f"Missing work package scenarios: {sorted(WORK_PACKAGES - package_ids)}")

    k_ids = {scenario["id"] for scenario in scenarios["work_packages"]["K"]}
    assert_true({"K1", "K2", "K3", "K4", "K5"}.issubset(k_ids), "K scenarios incomplete")

    for package, package_scenarios in scenarios["work_packages"].items():
        assert_true(package_scenarios, f"Package {package} has no scenarios")
        for scenario in package_scenarios:
            for fixture in scenario.get("fixtures", []):
                path = ROOT / fixture
                assert_true(path.exists(), f"{scenario['id']}: fixture path does not exist: {fixture}")


CHECKS: tuple[Check, ...] = (
    Check("fixture layout", check_fixture_layout),
    Check("profile schema fixtures", check_profile_schema_fixtures),
    Check("shared A schema contracts", check_shared_a_schema_contracts),
    Check("manual content contracts", check_manual_content_contracts),
    Check("markdown conversion contracts", check_markdown_conversion_contracts),
    Check("chunking contracts", check_chunking_contracts),
    Check("resolver scenarios", check_resolver_scenarios),
    Check("search and ask contracts", check_search_and_ask_contracts),
    Check("manual parser contracts", check_manual_parser_contracts),
    Check("API mock contracts", check_api_mock_contracts),
    Check("expected scenario contract", check_expected_scenarios_contract),
)


def run_all() -> None:
    for check in CHECKS:
        try:
            check.func()
        except SmokeSkip:
            continue


def main() -> int:
    failures: list[str] = []
    for check in CHECKS:
        try:
            check.func()
        except SmokeSkip as exc:
            print(f"SKIP {check.name}: {exc}")
        except Exception as exc:  # noqa: BLE001 - this is a CLI smoke runner.
            failures.append(f"FAIL {check.name}: {exc}")
            print(failures[-1])
        else:
            print(f"PASS {check.name}")

    if os.environ.get("RUN_MODEL_TESTS") != "1":
        print("SKIP optional model tests; set RUN_MODEL_TESTS=1 to enable future model checks")
    if os.environ.get("RUN_WEB_TESTS") != "1":
        print("SKIP optional web tests; set RUN_WEB_TESTS=1 to enable future live web checks")
    if os.environ.get("RUN_NETWORK_TESTS") != "1":
        print("SKIP optional network tests; set RUN_NETWORK_TESTS=1 to enable future live network checks")

    if failures:
        print(f"{len(failures)} smoke check(s) failed")
        return 1

    print(f"{len(CHECKS)} smoke checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
