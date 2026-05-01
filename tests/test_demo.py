from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from homewiki.devices import list_devices
from scripts.demo_seed import demo_settings


ROOT = Path(__file__).resolve().parents[1]


def run_script(script_name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script_name), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_demo_check_fixture_mode_passes() -> None:
    completed = run_script("demo_check.py", "--json")

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok"
    assert payload["mode"] == "fixture"
    assert payload["failed"] == 0
    checked_ids = {check["id"] for check in payload["checks"]}
    assert {"DEMO-01", "DEMO-02", "DEMO-03", "DEMO-04", "DEMO-05", "DEMO-06"}.issubset(
        checked_ids
    )


def test_demo_reset_creates_empty_demo_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "demo-workspace"
    stale = workspace / "source_docs" / "stale.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("old", encoding="utf-8")

    completed = run_script("demo_reset.py", "--workspace", str(workspace), "--json")

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok"
    assert payload["removed_existing"] is True
    assert not stale.exists()
    for name in ("source_docs", "markdown_docs", "lancedb_data", "data", "api", "web"):
        assert (workspace / name).is_dir()


def test_demo_seed_populates_workspace_and_registry(tmp_path: Path) -> None:
    workspace = tmp_path / "demo-workspace"

    completed = run_script("demo_seed.py", "--workspace", str(workspace), "--json")

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["mode"] == "fixture"
    assert payload["device_count"] == 3
    assert (workspace / "source_docs/devices/dishwasher-bosch-sms6zcw00g/profile.yaml").exists()
    assert (workspace / "markdown_docs/devices/router-asus-rt-ax88u/notes/admin-notes.md").exists()
    assert (workspace / "api/search-scoped-bosch-e15.json").exists()
    assert (workspace / "scenarios.json").exists()
    assert (workspace / "demo_manifest.json").exists()
    assert (workspace / "demo.env").exists()

    settings = demo_settings(ROOT, workspace)
    devices = list_devices(settings=settings)
    assert {device.asset_id for device in devices} == {
        "dishwasher-bosch-sms6zcw00g",
        "dishwasher-siemens-sn23ec14cg",
        "router-asus-rt-ax88u",
    }


def test_demo_check_validates_seeded_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "demo-workspace"
    seed = run_script("demo_seed.py", "--workspace", str(workspace), "--json")
    assert seed.returncode == 0, seed.stderr

    completed = run_script(
        "demo_check.py",
        "--workspace",
        str(workspace),
        "--json",
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok"
    assert any(
        check["id"] == "seeded-workspace" and check["status"] == "ok"
        for check in payload["checks"]
    )


def test_demo_check_retrieval_mode_ingests_and_searches(tmp_path: Path) -> None:
    workspace = tmp_path / "demo-workspace"
    seed = run_script("demo_seed.py", "--workspace", str(workspace), "--json")
    assert seed.returncode == 0, seed.stderr

    completed = run_script(
        "demo_check.py",
        "--mode",
        "retrieval",
        "--workspace",
        str(workspace),
        "--json",
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok"
    assert payload["mode"] == "retrieval"
    assert payload["failed"] == 0
    checks = {check["id"]: check for check in payload["checks"]}
    assert checks["retrieval-ingest"]["status"] == "ok"
    assert checks["retrieval-index-status"]["status"] == "ok"
    assert checks["retrieval-exact-device"]["status"] == "ok"
    assert checks["retrieval-alias-device"]["status"] == "ok"
    assert checks["retrieval-ambiguous-device"]["status"] == "ok"
    assert checks["retrieval-router-note"]["status"] == "ok"
    assert checks["retrieval-ask-e15"]["status"] == "ok"
    assert checks["retrieval-ask-ambiguous"]["status"] == "ok"
    assert checks["retrieval-ask-router-note"]["status"] == "ok"
