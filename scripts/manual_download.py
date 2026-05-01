#!/usr/bin/env python3
"""Download a manual PDF into the Home Wiki source_docs tree.

Outputs a ``homewiki.schemas.ManualDownloadResult`` JSON payload. The default
destination comes from ``homewiki.config.load_settings().paths.source_docs``;
tests and one-off imports can override it with ``--source-root``. ``--first``
uses the same candidate finder as ``scripts/manual_find.py`` and can read the
stored fixture HTML with ``--fixture-html``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from homewiki.config import load_settings  # noqa: E402
from homewiki.manuals import (  # noqa: E402
    build_manual_search_query,
    download_manual,
    find_manual_candidates,
)
from homewiki.schemas import ManualDownloadResult  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--url")
    parser.add_argument("--brand")
    parser.add_argument("--model")
    parser.add_argument("--device-type")
    parser.add_argument("--first", action="store_true")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--title")
    parser.add_argument("--search-query")
    parser.add_argument(
        "--source-root",
        type=Path,
        default=load_settings().paths.source_docs,
        help="source_docs root. Defaults to HOME_WIKI_SOURCE_DOCS or source_docs.",
    )
    parser.add_argument(
        "--fixture-html",
        type=Path,
        help="Parse stored search-result HTML instead of performing a live search.",
    )
    args = parser.parse_args(argv)

    url = args.url
    title = args.title
    search_query = args.search_query

    if url is None:
        if not args.first:
            parser.error("either --url or --first must be supplied")
        if not args.brand or not args.model:
            parser.error("--first requires --brand and --model")

        fixture_html = None
        if args.fixture_html is not None:
            fixture_html = args.fixture_html.read_text(encoding="utf-8")

        result = find_manual_candidates(
            brand=args.brand,
            model=args.model,
            device_type=args.device_type,
            limit=args.limit,
            search_html=fixture_html,
        )
        if not result.candidates:
            failure = ManualDownloadResult(
                asset_id=args.asset_id,
                url="",
                downloaded=False,
                error="No manual candidates found",
            )
            print(json.dumps(failure.to_json_dict(), indent=2))
            return 1

        candidate = result.candidates[0]
        url = candidate.url
        title = title or candidate.title
        search_query = search_query or result.query
    elif search_query is None and (args.brand or args.model or args.device_type):
        search_query = build_manual_search_query(
            args.brand or "",
            args.model or "",
            args.device_type,
        )

    result = download_manual(
        asset_id=args.asset_id,
        url=url,
        source_root=args.source_root,
        title=title,
        search_query=search_query,
    )
    print(json.dumps(result.to_json_dict(), indent=2))
    return 0 if result.downloaded else 1


if __name__ == "__main__":
    raise SystemExit(main())
