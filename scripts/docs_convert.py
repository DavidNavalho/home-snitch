#!/usr/bin/env python3
"""Convert source documents into Markdown."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from homewiki.config import load_settings
from homewiki.conversion import convert_tree


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert Home Wiki source documents into Markdown."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Source document root. Defaults to HOME_WIKI_SOURCE_DOCS.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Markdown output root. Defaults to HOME_WIKI_MARKDOWN_DOCS.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reconvert files even when the Markdown output is newer.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first failed conversion.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the conversion report as JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings()
    source_root = args.source or settings.paths.source_docs
    markdown_root = args.output or settings.paths.markdown_docs

    report = convert_tree(
        source_root=source_root,
        markdown_root=markdown_root,
        force=args.force,
        fail_fast=args.fail_fast,
    )

    if args.json:
        print(json.dumps(report.to_json_dict(), indent=2, sort_keys=True))
    else:
        print(
            "Conversion complete: "
            f"converted={report.converted} "
            f"copied={report.copied} "
            f"skipped={report.skipped} "
            f"failed={report.failed}"
        )
        for result in report.files:
            suffix = f" ({result.error})" if result.error else ""
            print(f"{result.status.value}: {result.source_path} -> {result.markdown_path}{suffix}")

    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
