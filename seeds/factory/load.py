"""Load the factory floor seed devices and fixture manuals.

Reads each `seeds/factory/devices/*.yaml`, calls ``upsert_device`` to
register and persist the profile, copies the matching manuals from
``seeds/factory/manuals/<asset_id>/`` into the configured
``source_docs/devices/<asset_id>/manuals/`` tree, then runs ``ingest_all``
to convert + index everything.

This script does no live web fetches; the manuals are pre-baked fixtures.

Usage:
    python seeds/factory/load.py

Honors the standard environment variables (HOME_WIKI_SOURCE_DOCS,
HOME_WIKI_LANCEDB_DIR, EMBEDDING_PROVIDER, ...).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEEDS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from homewiki.config import load_settings  # noqa: E402
from homewiki.devices import upsert_device  # noqa: E402
from homewiki.ingest import ingest_all  # noqa: E402
from homewiki.lancedb_store import open_store  # noqa: E402
from homewiki.resolver import _parse_profile_yaml  # noqa: E402
from homewiki.schemas import DeviceProfile, normalize_model_identifier  # noqa: E402


def _build_profile(yaml_path: Path) -> DeviceProfile:
    data = _parse_profile_yaml(yaml_path)
    if "normalized_model" not in data and "model" in data:
        data["normalized_model"] = normalize_model_identifier(str(data["model"]))
    return DeviceProfile.model_validate(data)


def _copy_manuals(asset_id: str, source_docs_root: Path) -> int:
    src = SEEDS_ROOT / "manuals" / asset_id
    if not src.is_dir():
        return 0
    dst = source_docs_root / "devices" / asset_id / "manuals"
    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in src.iterdir():
        if path.is_file() and path.suffix == ".md":
            shutil.copy2(path, dst / path.name)
            copied += 1
    return copied


def main() -> int:
    settings = load_settings()
    print(f"domain_mode={settings.domain_mode}")
    print(f"source_docs={settings.paths.source_docs}")
    print(f"lancedb_dir={settings.paths.lancedb_dir}")

    devices_dir = SEEDS_ROOT / "devices"
    profile_paths = sorted(devices_dir.glob("*.yaml"))
    if not profile_paths:
        print(f"No device YAMLs found in {devices_dir}")
        return 1

    upserted = 0
    copied_total = 0
    for yaml_path in profile_paths:
        profile = _build_profile(yaml_path)
        saved = upsert_device(profile, settings=settings)
        copied = _copy_manuals(saved.asset_id, settings.paths.source_docs)
        upserted += 1
        copied_total += copied
        print(f"  + {saved.asset_id}: copied {copied} manual(s)")

    print(f"Upserted {upserted} devices; copied {copied_total} manual files.")
    print("Running ingest...")
    store = open_store(settings)
    report = ingest_all(
        source_root=settings.paths.source_docs,
        markdown_root=settings.paths.markdown_docs,
        store=store,
    )
    print(
        "Ingest report: "
        f"converted={report.converted} indexed={report.indexed} "
        f"skipped={report.skipped} failed={report.failed} "
        f"removed={report.removed}"
    )
    if report.warnings:
        print("Warnings:")
        for warning in report.warnings:
            print(f"  - {warning}")
    if report.errors:
        print("Errors:")
        for err in report.errors:
            print(f"  - {err.code}: {err.message}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
