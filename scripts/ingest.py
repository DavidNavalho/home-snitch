#!/usr/bin/env python3
"""Convert source docs and refresh the Home Wiki chunk index."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from homewiki.config import load_settings
from homewiki.ingest import ingest_all
from homewiki.lancedb_store import open_store


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert source documents and build the Home Wiki index."
    )
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--markdown", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--force-convert", action="store_true")
    parser.add_argument("--force-index", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = dict(os.environ)
    if args.db is not None:
        env["HOME_WIKI_LANCEDB_DIR"] = str(args.db)
    settings = load_settings(environ=env)

    source_root = args.source or settings.paths.source_docs
    markdown_root = args.markdown or settings.paths.markdown_docs
    store = open_store(settings)
    report = ingest_all(
        source_root=source_root,
        markdown_root=markdown_root,
        store=store,
        force_convert=args.force_convert,
        force_index=args.force_index,
    )
    _print_report(report, as_json=args.json)
    return 1 if report.failed else 0


def _print_report(report, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report.to_json_dict(), indent=2, sort_keys=True))
        return

    print(
        "Ingest complete: "
        f"converted={report.converted} "
        f"indexed={report.indexed} "
        f"skipped={report.skipped} "
        f"failed={report.failed} "
        f"removed={report.removed}"
    )
    for warning in report.warnings:
        print(f"warning: {warning}")
    for error in report.errors:
        print(f"error: {error.message}")


if __name__ == "__main__":
    raise SystemExit(main())
