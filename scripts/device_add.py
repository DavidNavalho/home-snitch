#!/usr/bin/env python3
"""Create or update a Home Wiki device profile."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic import ValidationError

from homewiki.config import load_settings
from homewiki.devices import generate_asset_id, load_profile, upsert_device
from homewiki.schemas import DeviceProfile, normalize_model_identifier


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    settings = load_settings()

    try:
        profile = _profile_from_args(args, settings)
        saved = upsert_device(profile, settings=settings)
    except (ValidationError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(saved.to_json_dict(), indent=2, sort_keys=True))
    else:
        print(saved.asset_id)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-type", required=True)
    parser.add_argument("--brand", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--room")
    parser.add_argument("--alias", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--serial-number")
    parser.add_argument("--purchase-date")
    parser.add_argument("--warranty-until")
    parser.add_argument("--support-url")
    parser.add_argument("--notes")
    parser.add_argument("--json", action="store_true")
    return parser


def _profile_from_args(args: argparse.Namespace, settings: Any) -> DeviceProfile:
    asset_id = generate_asset_id(args.device_type, args.brand, args.model)
    profile_path = settings.paths.source_docs / "devices" / asset_id / "profile.yaml"
    existing = load_profile(profile_path) if profile_path.exists() else None
    now = datetime.now(timezone.utc)

    data = existing.model_dump() if existing is not None else {}
    data.update(
        {
            "asset_id": asset_id,
            "device_type": args.device_type,
            "brand": args.brand,
            "model": args.model,
            "normalized_model": normalize_model_identifier(args.model),
            "aliases": _merge_unique(
                existing.aliases if existing is not None else [], args.alias
            ),
            "tags": _merge_unique(
                existing.tags if existing is not None else [], args.tag
            ),
            "created_at": existing.created_at if existing is not None else now,
            "updated_at": now,
        }
    )

    _update_if_present(data, "room", args.room)
    _update_if_present(data, "serial_number", args.serial_number)
    _update_if_present(data, "purchase_date", args.purchase_date)
    _update_if_present(data, "warranty_until", args.warranty_until)
    _update_if_present(data, "support_url", args.support_url)
    _update_if_present(data, "notes", args.notes)

    for field_name in (
        "room",
        "serial_number",
        "purchase_date",
        "warranty_until",
        "support_url",
        "notes",
    ):
        data.setdefault(field_name, None)

    return DeviceProfile.model_validate(data)


def _update_if_present(data: dict[str, Any], field_name: str, value: Any) -> None:
    if value is not None:
        data[field_name] = value


def _merge_unique(existing: list[str], additions: list[str]) -> list[str]:
    merged: list[str] = []
    for value in [*existing, *additions]:
        if value not in merged:
            merged.append(value)
    return merged


if __name__ == "__main__":
    raise SystemExit(main())
