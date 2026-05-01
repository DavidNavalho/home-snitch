import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from homewiki.config import load_settings
from homewiki.devices import (
    generate_asset_id,
    get_device,
    list_devices,
    load_profile,
    render_profile_markdown,
    sync_registry_from_files,
    upsert_device,
)
from homewiki.schemas import DeviceProfile


ROOT = Path(__file__).resolve().parents[1]


class DeviceStoreTests(TestCase):
    def test_generate_asset_id_from_varied_inputs(self) -> None:
        self.assertEqual(
            generate_asset_id("Dish Washer", "Bosch Home", "SMS 6ZCW-00G"),
            "dish-washer-bosch-home-sms6zcw00g",
        )
        self.assertEqual(
            generate_asset_id("router", "ASUS", "RT_AX88U"),
            "router-asus-rtax88u",
        )

    def test_create_profile_writes_yaml_markdown_and_registry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = load_settings(environ={}, project_root=Path(temp_dir))
            profile = _bosch_profile()

            saved = upsert_device(profile, settings=settings)

            profile_path = (
                settings.paths.source_docs
                / "devices"
                / "dishwasher-bosch-sms6zcw00g"
                / "profile.yaml"
            )
            markdown_path = profile_path.with_name("profile.md")
            self.assertEqual(saved.asset_id, "dishwasher-bosch-sms6zcw00g")
            self.assertTrue(profile_path.exists())
            self.assertTrue(markdown_path.exists())
            self.assertTrue(settings.paths.device_registry.exists())

            loaded = load_profile(profile_path)
            self.assertEqual(loaded, profile)
            self.assertIn(
                "Warranty until: 2028-04-30",
                markdown_path.read_text(encoding="utf-8"),
            )

            from_registry = get_device(profile.asset_id, settings=settings)
            self.assertEqual(from_registry, profile)

    def test_upsert_is_idempotent_and_updates_existing_row(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = load_settings(environ={}, project_root=Path(temp_dir))
            profile = _bosch_profile(warranty_until=None, aliases=["kitchen dishwasher"])
            upsert_device(profile, settings=settings)

            updated = profile.model_copy(
                update={
                    "aliases": ["kitchen dishwasher", "dishwasher"],
                    "warranty_until": date(2028, 4, 30),
                    "updated_at": datetime(2026, 5, 1, 13, 0, tzinfo=timezone.utc),
                }
            )
            upsert_device(updated, settings=settings)

            self.assertEqual(list_devices(settings=settings), [updated])
            markdown = (
                settings.paths.source_docs
                / "devices"
                / updated.asset_id
                / "profile.md"
            ).read_text(encoding="utf-8")
            self.assertIn("- dishwasher", markdown)
            self.assertIn("Warranty until: 2028-04-30", markdown)

    def test_upsert_preserves_unknown_yaml_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = load_settings(environ={}, project_root=Path(temp_dir))
            profile = _bosch_profile()
            upsert_device(profile, settings=settings)
            profile_path = (
                settings.paths.source_docs / "devices" / profile.asset_id / "profile.yaml"
            )
            with profile_path.open("a", encoding="utf-8") as handle:
                handle.write("installer: Local Shop\n")

            upsert_device(
                profile.model_copy(update={"room": "utility"}),
                settings=settings,
            )

            self.assertIn(
                "installer: Local Shop",
                profile_path.read_text(encoding="utf-8"),
            )

    def test_sync_registry_from_existing_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = load_settings(environ={}, project_root=Path(temp_dir))
            profile = _bosch_profile()
            profile_dir = settings.paths.source_docs / "devices" / profile.asset_id
            profile_dir.mkdir(parents=True)
            (profile_dir / "profile.yaml").write_text(
                "\n".join(
                    [
                        "asset_id: dishwasher-bosch-sms6zcw00g",
                        "device_type: dishwasher",
                        "brand: Bosch",
                        "model: SMS6ZCW00G",
                        "normalized_model: sms6zcw00g",
                        "aliases:",
                        "  - kitchen dishwasher",
                        "room: kitchen",
                        "serial_number: ABC123",
                        "purchase_date: 2024-04-30",
                        "warranty_until: 2028-04-30",
                        "support_url: https://example.com/support",
                        "notes: Under counter.",
                        "tags:",
                        "  - appliance",
                        "created_at: 2026-05-01T12:00:00Z",
                        "updated_at: 2026-05-01T12:00:00Z",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            result = sync_registry_from_files(settings=settings)

            self.assertEqual(result.loaded, 1)
            self.assertEqual(result.updated, 1)
            self.assertEqual(result.failed, 0)
            self.assertEqual(result.errors, [])
            self.assertEqual(list_devices(settings=settings), [profile])

    def test_sync_reports_invalid_yaml_and_continues(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = load_settings(environ={}, project_root=Path(temp_dir))
            upsert_device(_bosch_profile(), settings=settings)
            bad_dir = settings.paths.source_docs / "devices" / "bad-profile"
            bad_dir.mkdir(parents=True)
            (bad_dir / "profile.yaml").write_text(
                "asset_id: bad-profile\n  - orphan\n",
                encoding="utf-8",
            )

            result = sync_registry_from_files(settings=settings)

            self.assertEqual(result.loaded, 1)
            self.assertEqual(result.failed, 1)
            self.assertEqual(result.errors[0].code, "invalid_profile")
            self.assertEqual(
                [profile.asset_id for profile in list_devices(settings=settings)],
                ["dishwasher-bosch-sms6zcw00g"],
            )

    def test_duplicate_normalized_models_are_allowed_and_flagged(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = load_settings(environ={}, project_root=Path(temp_dir))
            first = _profile(
                asset_id="sensor-acme-ab12",
                device_type="sensor",
                brand="Acme",
                model="AB-12",
                room="hall",
            )
            second = _profile(
                asset_id="sensor-contoso-ab12",
                device_type="sensor",
                brand="Contoso",
                model="AB 12",
                room="garage",
            )
            upsert_device(first, settings=settings)
            upsert_device(second, settings=settings)

            result = sync_registry_from_files(settings=settings)

            self.assertEqual(result.loaded, 2)
            self.assertEqual(result.failed, 0)
            self.assertEqual(result.errors[0].code, "duplicate_normalized_model")
            self.assertEqual(
                result.errors[0].details,
                {
                    "normalized_model": "ab12",
                    "asset_ids": ["sensor-acme-ab12", "sensor-contoso-ab12"],
                },
            )
            self.assertEqual(len(list_devices(settings=settings)), 2)

    def test_markdown_is_deterministic(self) -> None:
        profile = _bosch_profile()

        self.assertEqual(
            render_profile_markdown(profile),
            render_profile_markdown(profile),
        )


class DeviceCliTests(TestCase):
    def test_device_add_and_list_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            env = _cli_env(temp_dir)
            add = subprocess.run(
                [
                    sys.executable,
                    "scripts/device_add.py",
                    "--device-type",
                    "dishwasher",
                    "--brand",
                    "Bosch",
                    "--model",
                    "SMS6ZCW00G",
                    "--room",
                    "kitchen",
                    "--alias",
                    "kitchen dishwasher",
                    "--tag",
                    "appliance",
                    "--warranty-until",
                    "2028-04-30",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )

            self.assertEqual(add.returncode, 0, add.stderr)
            self.assertEqual(add.stdout.strip(), "dishwasher-bosch-sms6zcw00g")

            listed = subprocess.run(
                [sys.executable, "scripts/device_list.py", "--json"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )

            self.assertEqual(listed.returncode, 0, listed.stderr)
            payload = json.loads(listed.stdout)
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["asset_id"], "dishwasher-bosch-sms6zcw00g")
            self.assertEqual(payload[0]["normalized_model"], "sms6zcw00g")
            self.assertEqual(payload[0]["warranty_until"], "2028-04-30")

    def test_device_add_invalid_date_exits_nonzero_without_partial_profile(self) -> None:
        with TemporaryDirectory() as temp_dir:
            env = _cli_env(temp_dir)
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/device_add.py",
                    "--device-type",
                    "dishwasher",
                    "--brand",
                    "Bosch",
                    "--model",
                    "SMS6ZCW00G",
                    "--purchase-date",
                    "30-99-2026",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("purchase_date", result.stderr)
            self.assertFalse(
                (
                    Path(temp_dir)
                    / "source_docs"
                    / "devices"
                    / "dishwasher-bosch-sms6zcw00g"
                    / "profile.yaml"
                ).exists()
            )


def _bosch_profile(**updates: object) -> DeviceProfile:
    data = {
        "asset_id": "dishwasher-bosch-sms6zcw00g",
        "device_type": "dishwasher",
        "brand": "Bosch",
        "model": "SMS6ZCW00G",
        "normalized_model": "sms6zcw00g",
        "aliases": ["kitchen dishwasher"],
        "room": "kitchen",
        "serial_number": "ABC123",
        "purchase_date": date(2024, 4, 30),
        "warranty_until": date(2028, 4, 30),
        "support_url": "https://example.com/support",
        "notes": "Under counter.",
        "tags": ["appliance"],
        "created_at": datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
    }
    data.update(updates)
    return DeviceProfile.model_validate(data)


def _profile(
    *,
    asset_id: str,
    device_type: str,
    brand: str,
    model: str,
    room: str,
) -> DeviceProfile:
    return DeviceProfile(
        asset_id=asset_id,
        device_type=device_type,
        brand=brand,
        model=model,
        normalized_model="".join(char.lower() for char in model if char.isalnum()),
        aliases=[],
        room=room,
        tags=[],
    )


def _cli_env(temp_dir: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME_WIKI_SOURCE_DOCS": str(Path(temp_dir) / "source_docs"),
            "HOME_WIKI_MARKDOWN_DOCS": str(Path(temp_dir) / "markdown_docs"),
            "HOME_WIKI_DEVICE_REGISTRY": str(Path(temp_dir) / "data" / "devices.sqlite"),
            "HOME_WIKI_INGEST_MANIFEST": str(
                Path(temp_dir) / "data" / "ingest_manifest.sqlite"
            ),
            "HOME_WIKI_LANCEDB_DIR": str(Path(temp_dir) / "lancedb_data"),
        }
    )
    return env
