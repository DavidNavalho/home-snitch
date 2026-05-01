from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from unittest import TestCase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from homewiki.config import load_settings  # noqa: E402

try:
    from homewiki.schemas import (  # noqa: E402
        AskResponse,
        DeviceInformationResponse,
        DeviceProfile,
        ErrorResponse,
        SearchResponse,
    )
except ModuleNotFoundError as exc:
    if exc.name == "pydantic":
        raise unittest.SkipTest(
            "homewiki.schemas contract checks require project Python dependencies"
        ) from exc
    raise


FIXTURE_DIR = PROJECT_ROOT / "fixtures" / "api"


def read_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class UiContractTests(TestCase):
    def test_api_fixtures_validate_against_homewiki_schemas(self) -> None:
        devices = read_fixture("devices-list.json")
        for device in devices["devices"]:
            DeviceProfile(**device)

        SearchResponse(**read_fixture("search-scoped-bosch-e15.json"))
        SearchResponse(**read_fixture("search-ambiguous-dishwasher.json"))
        AskResponse(**read_fixture("ask-evidence-only-bosch-e15.json"))
        DeviceInformationResponse(**read_fixture("device-information-bosch.json"))
        DeviceInformationResponse(**read_fixture("device-information-siemens.json"))
        DeviceInformationResponse(**read_fixture("device-information-router.json"))
        ErrorResponse(**read_fixture("api-error.json")["error"])

    def test_ui_default_api_base_matches_homewiki_config(self) -> None:
        settings = load_settings(project_root=PROJECT_ROOT)
        api_js = (PROJECT_ROOT / "ui" / "src" / "api.js").read_text(
            encoding="utf-8"
        )
        match = re.search(r'DEFAULT_API_BASE = "([^"]+)"', api_js)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), settings.api.ui_api_base)

    def test_ui_fixture_module_does_not_copy_canonical_payloads(self) -> None:
        fixtures_js = (PROJECT_ROOT / "ui" / "src" / "fixtures.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("SMS6ZCW00G", fixtures_js)
        self.assertNotIn("SN23EC14CG", fixtures_js)
        self.assertNotIn("E15 means", fixtures_js)
