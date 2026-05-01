#!/usr/bin/env python3
"""List Home Wiki device profiles from the local registry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from homewiki.config import load_settings
from homewiki.devices import list_devices, sync_registry_from_files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    settings = load_settings()

    try:
        sync_result = sync_registry_from_files(settings=settings)
        profiles = list_devices(settings=settings)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for error in sync_result.errors:
        print(f"warning: {error.message}", file=sys.stderr)

    if args.json:
        payload = [profile.to_json_dict() for profile in profiles]
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    for profile in profiles:
        room = profile.room or "-"
        print(
            f"{profile.asset_id}\t{profile.device_type}\t"
            f"{profile.brand} {profile.model}\t{room}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
