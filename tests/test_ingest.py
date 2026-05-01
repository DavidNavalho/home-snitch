import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from homewiki.conversion import convert_tree
from homewiki.ingest import (
    build_index,
    document_metadata_for,
    infer_source_type,
    ingest_all,
    portable_source_path,
)
from homewiki.schemas import IndexResult, SourceType


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


class FakeStore:
    def __init__(self) -> None:
        self.rows = []
        self.deleted_paths: list[str] = []

    def index_chunks(self, chunks, mode="append"):
        if mode == "overwrite":
            self.rows = []
        self.rows.extend(chunks)
        return IndexResult(indexed=len(chunks))

    def delete_chunks_for_markdown_path(self, markdown_path: str) -> int:
        self.deleted_paths.append(markdown_path)
        before = len(self.rows)
        self.rows = [row for row in self.rows if row.markdown_path != markdown_path]
        return before - len(self.rows)


class IngestTests(TestCase):
    def test_document_metadata_attaches_profile_and_source_type(self) -> None:
        markdown_path = (
            FIXTURES
            / "markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md"
        )

        metadata = document_metadata_for(
            markdown_path=markdown_path,
            markdown_root=FIXTURES / "markdown_docs",
            source_root=FIXTURES / "source_docs",
        )

        self.assertEqual(metadata.asset_id, "dishwasher-bosch-sms6zcw00g")
        self.assertEqual(metadata.source_type, SourceType.MANUAL)
        self.assertEqual(metadata.brand, "Bosch")
        self.assertEqual(metadata.model, "SMS6ZCW00G")
        self.assertEqual(metadata.normalized_model, "sms6zcw00g")
        self.assertEqual(metadata.room, "kitchen")
        self.assertEqual(metadata.tags, ["appliance", "kitchen"])

    def test_build_index_indexes_fixture_profile_and_manual_chunks(self) -> None:
        with TemporaryDirectory() as tmp:
            source_root, markdown_root = self._copy_fixture_roots(Path(tmp))
            store = FakeStore()

            report = build_index(markdown_root, source_root, store)

            self.assertEqual(report.failed, 0)
            self.assertGreater(report.indexed, 0)
            self.assertTrue(
                any(
                    row.asset_id == "dishwasher-bosch-sms6zcw00g"
                    and row.source_type == SourceType.MANUAL
                    and "Troubleshooting > Error Codes" in row.section_title
                    and "E15 means" in row.text
                    for row in store.rows
                )
            )
            self.assertTrue(
                any(
                    row.asset_id == "dishwasher-bosch-sms6zcw00g"
                    and row.source_type == SourceType.PROFILE
                    for row in store.rows
                )
            )

    def test_incremental_second_run_skips_unchanged_documents(self) -> None:
        with TemporaryDirectory() as tmp:
            source_root, markdown_root = self._copy_fixture_roots(Path(tmp))
            store = FakeStore()

            first = build_index(markdown_root, source_root, store)
            row_count_after_first = len(store.rows)
            second = build_index(markdown_root, source_root, store)

            self.assertGreater(first.indexed, 0)
            self.assertEqual(second.indexed, 0)
            self.assertGreater(second.skipped, 0)
            self.assertEqual(len(store.rows), row_count_after_first)

    def test_changed_manual_replaces_old_chunks(self) -> None:
        with TemporaryDirectory() as tmp:
            source_root, markdown_root = self._copy_fixture_roots(Path(tmp))
            store = FakeStore()
            manual = (
                markdown_root
                / "devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md"
            )

            build_index(markdown_root, source_root, store)
            manual.write_text(
                manual.read_text(encoding="utf-8").replace(
                    "E15 means the water protection system has been activated",
                    "E15 means updated fixture water protection wording",
                ),
                encoding="utf-8",
            )
            report = build_index(markdown_root, source_root, store)

            self.assertGreater(report.indexed, 0)
            self.assertIn(
                "markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md",
                store.deleted_paths,
            )
            matching_text = "\n".join(row.text for row in store.rows)
            self.assertIn("updated fixture water protection wording", matching_text)
            self.assertNotIn(
                "E15 means the water protection system has been activated",
                matching_text,
            )

    def test_deleted_markdown_file_removes_stale_chunks(self) -> None:
        with TemporaryDirectory() as tmp:
            source_root, markdown_root = self._copy_fixture_roots(Path(tmp))
            store = FakeStore()
            note = markdown_root / "devices/router-asus-rt-ax88u/notes/admin-notes.md"

            build_index(markdown_root, source_root, store)
            self.assertTrue(any(row.asset_id == "router-asus-rt-ax88u" for row in store.rows))
            note.unlink()
            report = build_index(markdown_root, source_root, store)

            self.assertGreater(report.removed, 0)
            self.assertFalse(any(row.markdown_path.endswith("admin-notes.md") for row in store.rows))

    def test_empty_changed_document_removes_existing_chunks(self) -> None:
        with TemporaryDirectory() as tmp:
            source_root, markdown_root = self._copy_fixture_roots(Path(tmp))
            store = FakeStore()
            manual = (
                markdown_root
                / "devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md"
            )

            build_index(markdown_root, source_root, store)
            bosch_manual_path = (
                "markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md"
            )
            self.assertTrue(any(row.markdown_path == bosch_manual_path for row in store.rows))
            manual.write_text("---\nsource_type: manual\n---\n\n", encoding="utf-8")
            report = build_index(markdown_root, source_root, store)

            self.assertGreater(report.removed, 0)
            self.assertGreater(report.skipped, 0)
            self.assertFalse(any(row.markdown_path == bosch_manual_path for row in store.rows))

    def test_missing_profile_is_reported_and_not_indexed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "source_docs"
            markdown_root = root / "markdown_docs"
            unknown = markdown_root / "devices/unknown-device/manuals/manual.md"
            unknown.parent.mkdir(parents=True)
            source_root.mkdir()
            unknown.write_text("# Manual\n\nUnknown device text.\n", encoding="utf-8")
            store = FakeStore()

            report = build_index(markdown_root, source_root, store)

            self.assertEqual(report.failed, 1)
            self.assertFalse(store.rows)
            self.assertIn("missing profile", report.errors[0].message)

    def test_ingest_all_converts_then_indexes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "source_docs"
            markdown_root = root / "markdown_docs"
            shutil.copytree(FIXTURES / "source_docs", source_root)
            store = FakeStore()

            report = ingest_all(source_root, markdown_root, store)

            self.assertEqual(report.failed, 0)
            self.assertGreater(report.converted, 0)
            self.assertGreater(report.indexed, 0)
            self.assertTrue(
                markdown_root.joinpath(
                    "devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md"
                ).exists()
            )

    def test_infer_source_type_and_portable_source_path(self) -> None:
        self.assertEqual(
            infer_source_type(Path("devices/router-asus-rt-ax88u/notes/admin.md")),
            SourceType.NOTE,
        )
        self.assertEqual(
            portable_source_path(
                Path("/tmp/source_docs"),
                Path("devices/router-asus-rt-ax88u/notes/admin.md"),
            ),
            "source_docs/devices/router-asus-rt-ax88u/notes/admin.md",
        )
        self.assertEqual(
            portable_source_path(
                Path("/tmp/source_docs"),
                Path("devices/router-asus-rt-ax88u/manuals/manual.pdf.md"),
            ),
            "source_docs/devices/router-asus-rt-ax88u/manuals/manual.pdf",
        )

    def _copy_fixture_roots(self, root: Path) -> tuple[Path, Path]:
        source_root = root / "source_docs"
        markdown_root = root / "markdown_docs"
        shutil.copytree(FIXTURES / "source_docs", source_root)
        shutil.copytree(FIXTURES / "markdown_docs", markdown_root)
        return source_root, markdown_root
