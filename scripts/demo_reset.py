#!/usr/bin/env python3
"""Clear generated Home Wiki demo runtime data."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from homewiki.config import find_project_root  # noqa: E402


DEMO_SUBDIRS = ("source_docs", "markdown_docs", "lancedb_data", "data", "api", "web")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Demo workspace to clear. Defaults to <project>/.demo.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow clearing a custom workspace path that is not demo-named.",
    )
    parser.add_argument("--json", action="store_true", help="Print a JSON report.")
    args = parser.parse_args(argv)

    project_root = find_project_root(ROOT)
    workspace = resolve_demo_workspace(args.workspace, project_root)
    if not args.force and not is_safe_demo_workspace(workspace, project_root):
        message = (
            f"Refusing to clear non-demo workspace: {workspace}. "
            "Use --force only for an intentionally disposable demo path."
        )
        return emit({"status": "error", "workspace": str(workspace), "error": message}, args.json)

    existed = workspace.exists()
    if existed:
        shutil.rmtree(workspace)

    workspace.mkdir(parents=True, exist_ok=True)
    for name in DEMO_SUBDIRS:
        (workspace / name).mkdir(parents=True, exist_ok=True)

    return emit(
        {
            "status": "ok",
            "workspace": str(workspace),
            "removed_existing": existed,
            "created": [str(workspace / name) for name in DEMO_SUBDIRS],
        },
        args.json,
    )


def resolve_demo_workspace(value: Path | None, project_root: Path) -> Path:
    workspace = value or project_root / ".demo"
    if not workspace.is_absolute():
        workspace = project_root / workspace
    return workspace.expanduser().resolve()


def is_safe_demo_workspace(workspace: Path, project_root: Path) -> bool:
    if workspace in {project_root, project_root.parent, Path.home().resolve()}:
        return False
    if workspace.name in {".demo", "demo"}:
        return True
    return any("demo" in part.lower() for part in workspace.parts)


def emit(payload: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif payload["status"] == "ok":
        print(f"Demo workspace reset: {payload['workspace']}")
    else:
        print(f"error: {payload['error']}", file=sys.stderr)
    return 0 if payload["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
