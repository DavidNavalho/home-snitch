from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from homewiki.resolver import load_device_profiles, resolve_device
from homewiki.schemas import ResolutionStatus


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DOCS = ROOT / "fixtures" / "source_docs"


def fixture_devices():
    return load_device_profiles(SOURCE_DOCS)


def test_loads_fixture_device_profiles() -> None:
    devices = fixture_devices()

    assert {device.asset_id for device in devices} == {
        "dishwasher-bosch-sms6zcw00g",
        "dishwasher-siemens-sn23ec14cg",
        "router-asus-rt-ax88u",
    }


def test_loader_skips_invalid_profiles_with_warning(tmp_path: Path) -> None:
    valid_dir = tmp_path / "devices" / "router-asus-rt-ax88u"
    invalid_dir = tmp_path / "devices" / "dishwasher-invalid-model"
    valid_dir.mkdir(parents=True)
    invalid_dir.mkdir(parents=True)
    valid_dir.joinpath("profile.yaml").write_text(
        dedent(
            """
            asset_id: router-asus-rt-ax88u
            device_type: router
            brand: ASUS
            model: RT-AX88U
            normalized_model: rtax88u
            aliases:
              - router
            room: office
            serial_number:
            purchase_date:
            warranty_until:
            support_url:
            notes:
            tags:
              - network
            created_at:
            updated_at:
            """
        ).strip(),
        encoding="utf-8",
    )
    invalid_dir.joinpath("profile.yaml").write_text(
        dedent(
            """
            asset_id: dishwasher-invalid-model
            device_type: dishwasher
            brand: Bosch
            model: SMS6ZCW00G
            normalized_model: wrong
            aliases:
              - dishwasher
            room: kitchen
            serial_number:
            purchase_date:
            warranty_until:
            support_url:
            notes:
            tags:
              - appliance
            created_at:
            updated_at:
            """
        ).strip(),
        encoding="utf-8",
    )

    with pytest.warns(RuntimeWarning, match="Skipping invalid device profile"):
        devices = load_device_profiles(tmp_path)

    assert [device.asset_id for device in devices] == ["router-asus-rt-ax88u"]


def test_exact_model_match() -> None:
    resolution = resolve_device(
        "What does E15 mean on SMS6ZCW00G?",
        devices=fixture_devices(),
    )

    assert resolution.status == ResolutionStatus.EXACT
    assert resolution.asset_id == "dishwasher-bosch-sms6zcw00g"
    assert "model" in resolution.matched_on
    assert resolution.confidence >= 0.9
    assert resolution.filters.asset_id == "dishwasher-bosch-sms6zcw00g"


def test_model_match_with_punctuation_and_spacing_variation() -> None:
    resolution = resolve_device(
        "What does E15 mean on SMS 6ZCW-00G?",
        devices=fixture_devices(),
    )

    assert resolution.status == ResolutionStatus.EXACT
    assert resolution.asset_id == "dishwasher-bosch-sms6zcw00g"


def test_explicit_asset_id_wins() -> None:
    resolution = resolve_device(
        "E15",
        asset_id="dishwasher-bosch-sms6zcw00g",
        devices=fixture_devices(),
    )

    assert resolution.status == ResolutionStatus.EXACT
    assert resolution.asset_id == "dishwasher-bosch-sms6zcw00g"
    assert resolution.confidence == 1.0
    assert resolution.matched_on == ["asset_id"]
    assert resolution.filters.asset_id == "dishwasher-bosch-sms6zcw00g"


def test_unknown_explicit_asset_id_returns_none() -> None:
    resolution = resolve_device(
        "E15",
        asset_id="dishwasher-missing-model",
        devices=fixture_devices(),
    )

    assert resolution.status == ResolutionStatus.NONE
    assert resolution.asset_id is None
    assert resolution.filters.is_empty()


def test_unique_alias_plus_device_type_resolves_exact() -> None:
    resolution = resolve_device(
        "wifi router admin password",
        devices=fixture_devices(),
    )

    assert resolution.status == ResolutionStatus.EXACT
    assert resolution.asset_id == "router-asus-rt-ax88u"
    assert "alias" in resolution.matched_on
    assert "device_type" in resolution.matched_on


def test_ambiguous_dishwasher_alias_is_not_guessed() -> None:
    resolution = resolve_device(
        "dishwasher error code",
        devices=fixture_devices(),
    )

    assert resolution.status == ResolutionStatus.AMBIGUOUS
    assert resolution.asset_id is None
    assert resolution.filters.is_empty()
    assert {
        "dishwasher-bosch-sms6zcw00g",
        "dishwasher-siemens-sn23ec14cg",
    }.issubset({candidate.asset_id for candidate in resolution.candidates})


def test_no_match_query_returns_none() -> None:
    resolution = resolve_device(
        "where is the stopcock?",
        devices=fixture_devices(),
    )

    assert resolution.status == ResolutionStatus.NONE
    assert resolution.asset_id is None
    assert resolution.candidates == []


def test_brand_only_query_does_not_over_resolve() -> None:
    resolution = resolve_device("Bosch", devices=fixture_devices())

    assert resolution.status == ResolutionStatus.NONE
    assert resolution.asset_id is None
    assert resolution.filters.is_empty()


def test_cli_outputs_resolution_json() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/device_resolve.py",
            "--source-docs",
            str(SOURCE_DOCS),
            "--asset-id",
            "dishwasher-bosch-sms6zcw00g",
            "E15",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["status"] == "exact"
    assert payload["asset_id"] == "dishwasher-bosch-sms6zcw00g"
    assert payload["confidence"] == 1.0
