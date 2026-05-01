from pathlib import Path
from unittest import TestCase

from homewiki.config import load_settings


class SettingsTests(TestCase):
    def test_defaults_resolve_relative_paths_under_project_root(self) -> None:
        root = Path("/tmp/homewiki")
        settings = load_settings(environ={}, project_root=root)

        self.assertEqual(settings.paths.source_docs, root / "source_docs")
        self.assertEqual(settings.paths.markdown_docs, root / "markdown_docs")
        self.assertEqual(settings.paths.lancedb_dir, root / "lancedb_data")
        self.assertEqual(settings.paths.device_registry, root / "data/devices.sqlite")
        self.assertEqual(
            settings.paths.ingest_manifest, root / "data/ingest_manifest.sqlite"
        )
        self.assertEqual(settings.table, "home_wiki_chunks")
        self.assertEqual(settings.embedding.provider, "fake")
        self.assertEqual(settings.chat.provider, "disabled")
        self.assertEqual(settings.api.host, "127.0.0.1")
        self.assertEqual(settings.api.port, 8000)

    def test_absolute_paths_remain_absolute(self) -> None:
        source_docs = Path("/var/tmp/homewiki-source")

        settings = load_settings(
            environ={"HOME_WIKI_SOURCE_DOCS": str(source_docs)},
            project_root=Path("/tmp/homewiki"),
        )

        self.assertEqual(settings.paths.source_docs, source_docs)

    def test_invalid_provider_fails(self) -> None:
        with self.assertRaises(ValueError):
            load_settings(
                environ={"EMBEDDING_PROVIDER": "not-real"},
                project_root=Path("/tmp/homewiki"),
            )

    def test_invalid_port_fails(self) -> None:
        with self.assertRaises(ValueError):
            load_settings(
                environ={"API_PORT": "70000"},
                project_root=Path("/tmp/homewiki"),
            )
