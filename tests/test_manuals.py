from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from homewiki.manuals import (
    build_manual_search_query,
    download_manual,
    find_manual_candidates,
    parse_manual_search_html,
)


ROOT = Path(__file__).resolve().parents[1]
WEB_FIXTURES = ROOT / "fixtures" / "web"
ASSET_ID = "dishwasher-bosch-sms6zcw00g"


def test_parse_fixture_search_returns_ranked_candidates() -> None:
    query = build_manual_search_query("Bosch", "SMS6ZCW00G", "dishwasher")
    html = (WEB_FIXTURES / "duckduckgo-manual-search.html").read_text(
        encoding="utf-8"
    )

    result = parse_manual_search_html(
        html,
        query=query,
        brand="Bosch",
        model="SMS6ZCW00G",
        device_type="dishwasher",
    )

    assert result.query == "Bosch SMS6ZCW00G dishwasher manual pdf"
    assert len(result.candidates) == 3
    assert result.candidates[0].is_pdf is True
    assert result.candidates[0].url.endswith(".pdf")
    assert "Bosch SMS6ZCW00G" in result.candidates[0].title
    assert result.candidates[0].source_host == "downloads.example.test"
    assert result.candidates[1].source_host == "support.example.test"


def test_find_manual_candidates_accepts_fixture_html() -> None:
    html = (WEB_FIXTURES / "duckduckgo-manual-search.html").read_text(
        encoding="utf-8"
    )

    result = find_manual_candidates(
        "Bosch",
        "SMS6ZCW00G",
        "dishwasher",
        search_html=html,
    )

    assert result.candidates
    assert result.candidates[0].rank == 1
    assert result.candidates[0].is_pdf is True


def test_download_manual_saves_pdf_and_sidecar_from_file_url(tmp_path: Path) -> None:
    source_root = _source_root_with_asset(tmp_path)
    url = (WEB_FIXTURES / "manual.pdf").as_uri()

    result = download_manual(
        ASSET_ID,
        url,
        source_root,
        title="Bosch SMS6ZCW00G Dishwasher User Manual PDF",
        search_query="Bosch SMS6ZCW00G dishwasher manual pdf",
    )

    assert result.downloaded is True
    assert result.error is None
    assert result.saved_path is not None
    assert result.sidecar_path is not None

    saved_path = Path(result.saved_path)
    sidecar_path = Path(result.sidecar_path)
    assert saved_path.parent == source_root / "devices" / ASSET_ID / "manuals"
    assert saved_path.read_bytes().startswith(b"%PDF")
    assert sidecar_path.exists()

    sidecar = sidecar_path.read_text(encoding="utf-8")
    assert f"source_url: {json.dumps(url)}" in sidecar
    assert 'title: "Bosch SMS6ZCW00G Dishwasher User Manual PDF"' in sidecar
    assert 'search_query: "Bosch SMS6ZCW00G dishwasher manual pdf"' in sidecar


def test_download_manual_rejects_non_pdf_body(tmp_path: Path) -> None:
    source_root = _source_root_with_asset(tmp_path)
    html_path = tmp_path / "not-a-manual.html"
    html_path.write_text("<!doctype html><title>Not a PDF</title>", encoding="utf-8")

    result = download_manual(ASSET_ID, html_path.as_uri(), source_root)

    assert result.downloaded is False
    assert result.saved_path is None
    assert result.error is not None
    assert "not PDF-looking" in result.error
    assert not list((source_root / "devices" / ASSET_ID).glob("manuals/*.pdf"))


def test_download_manual_rejects_unknown_asset_id(tmp_path: Path) -> None:
    source_root = tmp_path / "source_docs"
    url = (WEB_FIXTURES / "manual.pdf").as_uri()

    result = download_manual(ASSET_ID, url, source_root)

    assert result.downloaded is False
    assert result.error is not None
    assert "Unknown asset_id" in result.error


def test_manual_find_cli_reads_fixture_html() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "manual_find.py"),
            "--brand",
            "Bosch",
            "--model",
            "SMS6ZCW00G",
            "--device-type",
            "dishwasher",
            "--fixture-html",
            str(WEB_FIXTURES / "duckduckgo-manual-search.html"),
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["query"] == "Bosch SMS6ZCW00G dishwasher manual pdf"
    assert payload["candidates"][0]["is_pdf"] is True


def test_manual_download_cli_downloads_direct_url(tmp_path: Path) -> None:
    source_root = _source_root_with_asset(tmp_path)
    url = (WEB_FIXTURES / "manual.pdf").as_uri()

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "manual_download.py"),
            "--asset-id",
            ASSET_ID,
            "--url",
            url,
            "--source-root",
            str(source_root),
            "--title",
            "Fixture manual",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["downloaded"] is True
    assert Path(payload["saved_path"]).read_bytes().startswith(b"%PDF")


@pytest.mark.skipif(
    os.environ.get("RUN_WEB_TESTS") != "1",
    reason="live web manual search is optional",
)
def test_live_manual_search_returns_plausible_candidate() -> None:
    result = find_manual_candidates("Bosch", "SMS6ZCW00G", "dishwasher")

    assert any(
        candidate.is_pdf or "manual" in candidate.title.lower()
        for candidate in result.candidates
    )


def _source_root_with_asset(tmp_path: Path) -> Path:
    source_root = tmp_path / "source_docs"
    (source_root / "devices" / ASSET_ID).mkdir(parents=True)
    return source_root
