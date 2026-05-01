#!/usr/bin/env python3
"""Seed a disposable Home Wiki demo workspace from checked-in fixtures."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from homewiki.config import Settings, find_project_root, load_settings  # noqa: E402
from homewiki.devices import list_devices, sync_registry_from_files  # noqa: E402


FIXTURE_COPIES = {
    "source_docs": "source_docs",
    "markdown_docs": "markdown_docs",
    "api": "api",
    "web": "web",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Demo workspace to seed. Defaults to <project>/.demo.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a JSON manifest instead of a short text summary.",
    )
    args = parser.parse_args(argv)

    project_root = find_project_root(ROOT)
    workspace = resolve_demo_workspace(args.workspace, project_root)
    fixtures_root = project_root / "fixtures"
    scenarios = fixtures_root / "demo" / "scenarios.json"

    workspace.mkdir(parents=True, exist_ok=True)
    for target_name, fixture_name in FIXTURE_COPIES.items():
        copy_fixture_tree(fixtures_root / fixture_name, workspace / target_name)

    (workspace / "lancedb_data").mkdir(parents=True, exist_ok=True)
    (workspace / "data").mkdir(parents=True, exist_ok=True)
    shutil.copy2(scenarios, workspace / "scenarios.json")

    settings = demo_settings(project_root, workspace)
    sync_result = sync_registry_from_files(settings=settings)
    devices = list_devices(settings=settings)

    manifest = {
        "mode": "fixture",
        "workspace": str(workspace),
        "source_docs": str(settings.paths.source_docs),
        "markdown_docs": str(settings.paths.markdown_docs),
        "lancedb_dir": str(settings.paths.lancedb_dir),
        "device_registry": str(settings.paths.device_registry),
        "scenarios": str(workspace / "scenarios.json"),
        "device_count": len(devices),
        "devices": [device.asset_id for device in devices],
        "registry_sync": sync_result.to_json_dict(),
    }
    (workspace / "demo_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace / "demo.env").write_text(
        demo_env_text(project_root, workspace),
        encoding="utf-8",
    )

    if args.json:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        print(
            "Demo workspace seeded: "
            f"{workspace} ({len(devices)} devices, "
            f"sync failed={sync_result.failed})"
        )
    return 1 if sync_result.failed else 0


def resolve_demo_workspace(value: Path | None, project_root: Path) -> Path:
    workspace = value or project_root / ".demo"
    if not workspace.is_absolute():
        workspace = project_root / workspace
    return workspace.expanduser().resolve()


def copy_fixture_tree(source: Path, target: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"missing demo fixture source: {source}")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def demo_settings(project_root: Path, workspace: Path) -> Settings:
    return load_settings(environ=demo_env(project_root, workspace), project_root=project_root)


def demo_env(project_root: Path, workspace: Path) -> dict[str, str]:
    return {
        "HOME_WIKI_SOURCE_DOCS": str(workspace / "source_docs"),
        "HOME_WIKI_MARKDOWN_DOCS": str(workspace / "markdown_docs"),
        "HOME_WIKI_LANCEDB_DIR": str(workspace / "lancedb_data"),
        "HOME_WIKI_DEVICE_REGISTRY": str(workspace / "data" / "devices.sqlite"),
        "HOME_WIKI_INGEST_MANIFEST": str(workspace / "data" / "ingest_manifest.sqlite"),
        "HOME_WIKI_TABLE": "home_wiki_chunks",
        "EMBEDDING_PROVIDER": "fake",
        "CHAT_PROVIDER": "disabled",
        "API_HOST": "127.0.0.1",
        "API_PORT": "8000",
        "UI_API_BASE": "http://127.0.0.1:8000",
    }


def demo_env_text(project_root: Path, workspace: Path) -> str:
    lines = [f"# Demo workspace settings for {project_root}"]
    for key, value in demo_env(project_root, workspace).items():
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
