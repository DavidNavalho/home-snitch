from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from homewiki.config import load_settings
from homewiki.embeddings import EmbeddingConfigurationError
from homewiki.lancedb_store import LanceStoreError, open_store
from homewiki.schemas import IndexChunk, SearchFilters, SourceType


BOSCH_ASSET_ID = "dishwasher-bosch-sms6zcw00g"
ROUTER_ASSET_ID = "router-asus-rt-ax88u"


class LanceDBStoreTests(TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_fake_provider_indexes_and_scoped_searches(self) -> None:
        store = open_store(self._settings())

        result = store.index_chunks(self._sample_chunks(), mode="overwrite")

        self.assertEqual(result.indexed, 4)
        scoped = store.hybrid_search(
            "E15",
            filters=SearchFilters(asset_id=BOSCH_ASSET_ID),
            limit=5,
        )

        self.assertTrue(scoped)
        self.assertTrue(all(row.asset_id == BOSCH_ASSET_ID for row in scoped))
        self.assertTrue(any("E15" in row.text for row in scoped))
        self.assertNotIn("vector", scoped[0].to_json_dict())

        natural_language = store.hybrid_search(
            "water protection leak in the base",
            filters=SearchFilters(asset_id=BOSCH_ASSET_ID),
            limit=5,
        )

        self.assertTrue(natural_language)
        self.assertTrue(
            all(row.asset_id == BOSCH_ASSET_ID for row in natural_language)
        )
        self.assertTrue(
            any("water protection" in row.text.lower() for row in natural_language)
        )

    def test_global_search_can_return_multiple_devices(self) -> None:
        store = open_store(self._settings())
        store.index_chunks(self._sample_chunks(), mode="overwrite")

        results = store.hybrid_search("reset", limit=8)

        asset_ids = {row.asset_id for row in results}
        self.assertIn(BOSCH_ASSET_ID, asset_ids)
        self.assertIn(ROUTER_ASSET_ID, asset_ids)

    def test_filtered_search_never_returns_other_assets(self) -> None:
        store = open_store(self._settings())
        store.index_chunks(self._sample_chunks(), mode="overwrite")

        results = store.hybrid_search(
            "reset",
            filters=SearchFilters(asset_id=ROUTER_ASSET_ID),
            limit=8,
        )

        self.assertTrue(results)
        self.assertTrue(all(row.asset_id == ROUTER_ASSET_ID for row in results))

    def test_normalized_model_filter_never_returns_other_models(self) -> None:
        store = open_store(self._settings())
        store.index_chunks(self._sample_chunks(), mode="overwrite")

        results = store.hybrid_search(
            "E24 drain hose",
            filters=SearchFilters(normalized_model="sn23ec14cg"),
            limit=8,
        )

        self.assertTrue(results)
        self.assertTrue(
            all(row.normalized_model == "sn23ec14cg" for row in results)
        )
        self.assertTrue(any("E24" in row.text for row in results))

    def test_delete_by_markdown_path_removes_rows(self) -> None:
        store = open_store(self._settings())
        chunks = self._sample_chunks()
        store.index_chunks(chunks, mode="overwrite")

        deleted = store.delete_chunks_for_markdown_path(chunks[-1].markdown_path)
        results = store.hybrid_search("factory reset", limit=8)
        status = store.status()

        self.assertEqual(deleted, 1)
        self.assertNotIn(ROUTER_ASSET_ID, {row.asset_id for row in results})
        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["row_count"], len(chunks) - 1)
        self.assertEqual(status["embedding_provider"], "fake")

    def test_upsert_updates_existing_markdown_chunk_key(self) -> None:
        store = open_store(self._settings())
        original = self._chunk(
            text="Old service code ABC123 appears in the manual.",
            asset_id=BOSCH_ASSET_ID,
            source_path="source_docs/devices/bosch/manual.md",
            markdown_path="markdown_docs/devices/bosch/manual.md",
            chunk_index=0,
            content_hash="old",
        )
        updated = self._chunk(
            text="New service code ZX900 appears in the manual.",
            asset_id=BOSCH_ASSET_ID,
            source_path=original.source_path,
            markdown_path=original.markdown_path,
            chunk_index=original.chunk_index,
            content_hash="new",
        )

        store.index_chunks([original], mode="overwrite")
        result = store.index_chunks([updated], mode="upsert")
        results = store.hybrid_search("ZX900", limit=5)

        self.assertEqual(result.indexed, 1)
        self.assertEqual(store.status()["row_count"], 1)
        self.assertEqual(results[0].content_hash, "new")
        self.assertIn("ZX900", results[0].text)

    def test_missing_table_status_and_search_error_are_clear(self) -> None:
        store = open_store(self._settings())

        status = store.status()

        self.assertEqual(status["status"], "missing_table")
        self.assertEqual(status["row_count"], 0)
        self.assertIn("home_wiki_chunks", status["error"])
        with self.assertRaisesRegex(LanceStoreError, "not available"):
            store.hybrid_search("reset")

    def test_openai_compatible_missing_config_fails_clearly(self) -> None:
        settings = load_settings(
            environ={
                "EMBEDDING_PROVIDER": "openai_compatible",
                "EMBEDDING_API_BASE": "",
                "EMBEDDING_MODEL": "",
            },
            project_root=self.root,
        )

        with self.assertRaisesRegex(
            EmbeddingConfigurationError,
            "EMBEDDING_API_BASE, EMBEDDING_MODEL",
        ):
            open_store(settings)

    def _settings(self):
        return load_settings(
            environ={
                "EMBEDDING_PROVIDER": "fake",
                "HOME_WIKI_LANCEDB_DIR": str(self.root / "lancedb_data"),
            },
            project_root=self.root,
        )

    def _sample_chunks(self) -> list[IndexChunk]:
        return [
            self._chunk(
                text="E15 means water protection system activated. Check for leaks in the dishwasher base.",
                asset_id=BOSCH_ASSET_ID,
                source_path="source_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/quick.md",
                markdown_path="markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/quick.md",
                chunk_index=0,
                content_hash="bosch-e15",
            ),
            self._chunk(
                text="Reset the dishwasher program by holding Start for three seconds.",
                asset_id=BOSCH_ASSET_ID,
                source_path="source_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/quick.md",
                markdown_path="markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/quick.md",
                chunk_index=1,
                content_hash="bosch-reset",
            ),
            self._chunk(
                text="The Siemens dishwasher shows E24 when the drain hose is blocked.",
                asset_id="dishwasher-siemens-sn23ec14cg",
                source_path="source_docs/devices/dishwasher-siemens-sn23ec14cg/manuals/quick.md",
                markdown_path="markdown_docs/devices/dishwasher-siemens-sn23ec14cg/manuals/quick.md",
                chunk_index=0,
                content_hash="siemens-e24",
                brand="Siemens",
                model="SN23EC14CG",
                normalized_model="sn23ec14cg",
            ),
            self._chunk(
                text="Reset button restores factory settings on the ASUS router.",
                asset_id=ROUTER_ASSET_ID,
                source_path="source_docs/devices/router-asus-rt-ax88u/notes/admin.md",
                markdown_path="markdown_docs/devices/router-asus-rt-ax88u/notes/admin.md",
                chunk_index=0,
                content_hash="router-reset",
                brand="ASUS",
                model="RT-AX88U",
                normalized_model="rtax88u",
                device_type="router",
                room="office",
            ),
        ]

    def _chunk(
        self,
        *,
        text: str,
        asset_id: str,
        source_path: str,
        markdown_path: str,
        chunk_index: int,
        content_hash: str,
        brand: str = "Bosch",
        model: str = "SMS6ZCW00G",
        normalized_model: str = "sms6zcw00g",
        device_type: str = "dishwasher",
        room: str = "kitchen",
    ) -> IndexChunk:
        return IndexChunk(
            text=text,
            asset_id=asset_id,
            source_type=SourceType.MANUAL,
            brand=brand,
            model=model,
            normalized_model=normalized_model,
            device_type=device_type,
            room=room,
            source_path=source_path,
            markdown_path=markdown_path,
            section_title="Troubleshooting",
            chunk_index=chunk_index,
            content_hash=content_hash,
            modified_at=0.0,
            tags=["test"],
        )
