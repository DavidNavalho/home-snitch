#!/usr/bin/env python3
"""Resolve a user query to a known home device."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from homewiki.resolver import load_device_profiles, resolve_device  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="User query to resolve")
    parser.add_argument(
        "--asset-id",
        default=None,
        help="Explicit asset ID selected by the caller",
    )
    parser.add_argument(
        "--source-docs",
        default=None,
        help="Path to source_docs containing devices/*/profile.yaml",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    devices = load_device_profiles(args.source_docs)
    resolution = resolve_device(args.query, asset_id=args.asset_id, devices=devices)
    print(json.dumps(resolution.to_json_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
