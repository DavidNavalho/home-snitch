from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from homewiki.chunking import extract_frontmatter, split_markdown_document
from homewiki.schemas import DocumentMetadata, SourceType


ROOT = Path(__file__).resolve().parents[1]


class ChunkingTests(TestCase):
    def test_fixture_manual_preserves_heading_breadcrumbs(self) -> None:
        markdown_path = (
            ROOT
            / "fixtures/markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md"
        )
        metadata = DocumentMetadata(
            asset_id="dishwasher-bosch-sms6zcw00g",
            source_type=SourceType.MANUAL,
            brand="Bosch",
            model="SMS6ZCW00G",
            normalized_model="sms6zcw00g",
            device_type="dishwasher",
            room="kitchen",
            source_path="fixtures/source_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md",
            markdown_path="fixtures/markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md",
            tags=["appliance", "kitchen"],
        )

        chunks = split_markdown_document(markdown_path, metadata)

        e15_chunks = [chunk for chunk in chunks if "E15 means" in chunk.text]
        self.assertTrue(e15_chunks)
        e15 = e15_chunks[0]
        self.assertIn("Troubleshooting > Error Codes > E15", e15.section_title)
        self.assertIn("Section: ", e15.text)
        self.assertEqual(e15.asset_id, "dishwasher-bosch-sms6zcw00g")
        self.assertEqual(e15.source_type, SourceType.MANUAL)
        self.assertEqual(e15.brand, "Bosch")
        self.assertEqual(e15.tags, ["appliance", "kitchen"])

    def test_intro_text_before_first_heading_becomes_introduction(self) -> None:
        with TemporaryDirectory() as tmp:
            markdown_path = Path(tmp) / "note.md"
            markdown_path.write_text(
                "Loose intro text.\n\n# Main\n\nMain body.\n",
                encoding="utf-8",
            )
            metadata = DocumentMetadata(
                source_type=SourceType.OTHER,
                source_path="source_docs/note.md",
                markdown_path="markdown_docs/note.md",
            )

            chunks = split_markdown_document(markdown_path, metadata)

            self.assertEqual(chunks[0].section_title, "Introduction")
            self.assertIn("Loose intro text.", chunks[0].text)
            self.assertEqual(chunks[1].section_title, "Main")

    def test_frontmatter_is_not_indexed_as_text(self) -> None:
        with TemporaryDirectory() as tmp:
            markdown_path = Path(tmp) / "manual.md"
            markdown_path.write_text(
                "---\nasset_id: router-asus-rt-ax88u\nsource_type: note\n---\n\n# Access\n\nAdmin URL.\n",
                encoding="utf-8",
            )
            metadata = DocumentMetadata(
                asset_id="router-asus-rt-ax88u",
                source_type=SourceType.NOTE,
                source_path="source_docs/devices/router/notes/manual.md",
                markdown_path="markdown_docs/devices/router/notes/manual.md",
            )

            chunks = split_markdown_document(markdown_path, metadata)

            self.assertEqual(len(chunks), 1)
            self.assertNotIn("asset_id:", chunks[0].text)
            self.assertIn("Admin URL.", chunks[0].text)

    def test_long_sections_are_split_into_searchable_chunks(self) -> None:
        with TemporaryDirectory() as tmp:
            markdown_path = Path(tmp) / "manual.md"
            filler = " ".join(["front matter"] * 250)
            target = "E:30-00 means the water protection system is activated."
            tail = " ".join(["appendix"] * 250)
            markdown_path.write_text(
                f"# Manual\n\n{filler}\n\n{target}\n\n{tail}\n",
                encoding="utf-8",
            )
            metadata = DocumentMetadata(
                asset_id="dishwasher-bosch-sms6zcw00g",
                source_type=SourceType.MANUAL,
                source_path="source_docs/devices/dishwasher/manual.pdf",
                markdown_path="markdown_docs/devices/dishwasher/manual.pdf.md",
            )

            chunks = split_markdown_document(markdown_path, metadata)

            self.assertGreater(len(chunks), 1)
            target_chunks = [chunk for chunk in chunks if target in chunk.text]
            self.assertEqual(len(target_chunks), 1)
            self.assertLess(len(target_chunks[0].text), len(filler) + len(tail))

    def test_extract_frontmatter_returns_scalar_fields(self) -> None:
        markdown = (
            "---\n"
            "source_path: source_docs/devices/router/notes/admin.md\n"
            "source_type: note\n"
            "asset_id: router-asus-rt-ax88u\n"
            "---\n"
            "# Admin\n"
        )

        fields = extract_frontmatter(markdown)

        self.assertEqual(fields["source_type"], "note")
        self.assertEqual(fields["asset_id"], "router-asus-rt-ax88u")
