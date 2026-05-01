#!/usr/bin/env python3
"""Find likely manual PDF candidates for a device.

Outputs a ``homewiki.schemas.ManualSearchResult`` JSON payload. Use
``--fixture-html fixtures/web/duckduckgo-manual-search.html`` for deterministic
offline runs; without it the command performs a live DuckDuckGo HTML search.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from homewiki.manuals import find_manual_candidates  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brand", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--device-type")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--fixture-html",
        type=Path,
        help="Parse stored search-result HTML instead of performing a live search.",
    )
    args = parser.parse_args(argv)

    search_html = None
    if args.fixture_html is not None:
        search_html = args.fixture_html.read_text(encoding="utf-8")

    result = find_manual_candidates(
        brand=args.brand,
        model=args.model,
        device_type=args.device_type,
        limit=args.limit,
        search_html=search_html,
    )
    print(json.dumps(result.to_json_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
