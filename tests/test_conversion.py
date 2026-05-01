import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from homewiki.conversion import convert_tree, output_path_for
from homewiki.schemas import ConversionStatus


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


class ConversionTests(TestCase):
    def test_markdown_fixture_copies_to_matching_output_path(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            source_root = workspace / "source_docs"
            markdown_root = workspace / "markdown_docs"
            shutil.copytree(FIXTURES / "source_docs", source_root)

            report = convert_tree(source_root, markdown_root)

            output = markdown_root / "devices/dishwasher-bosch-sms6zcw00g/profile.md"
            self.assertTrue(output.exists())
            text = output.read_text(encoding="utf-8")
            self.assertIn("source_path: source_docs/devices/dishwasher-bosch-sms6zcw00g/profile.md", text)
            self.assertIn("source_type: profile", text)
            self.assertIn("asset_id: dishwasher-bosch-sms6zcw00g", text)
            self.assertIn("Model: SMS6ZCW00G", text)
            self.assertGreaterEqual(report.copied, 1)

    def test_required_text_csv_json_html_and_pdf_conversions(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            source_root = workspace / "source_docs"
            markdown_root = workspace / "markdown_docs"
            notes = source_root / "devices/router-asus-rt-ax88u/notes"
            manuals = source_root / "devices/dishwasher-bosch-sms6zcw00g/manuals"
            notes.mkdir(parents=True)
            manuals.mkdir(parents=True)

            (notes / "diagnostics.txt").write_text("Admin URL documented here.\n", encoding="utf-8")
            (notes / "ports.csv").write_text("name,port\nhttp,80\nadmin,8443\n", encoding="utf-8")
            (notes / "settings.json").write_text(json.dumps({"wifi": {"ssid": "fixture"}}), encoding="utf-8")
            (notes / "admin.html").write_text(
                "<html><head><title>Admin Page</title></head><body><h1>Access</h1><p>Use router.asus.com.</p></body></html>",
                encoding="utf-8",
            )
            shutil.copyfile(FIXTURES / "web/manual.pdf", manuals / "user-manual.pdf")

            report = convert_tree(source_root, markdown_root)

            self.assertEqual(report.failed, 0)
            self.assertGreaterEqual(report.converted, 5)

            txt = (markdown_root / "devices/router-asus-rt-ax88u/notes/diagnostics.txt.md").read_text(encoding="utf-8")
            self.assertIn("# Diagnostics", txt)
            self.assertIn("Admin URL documented here.", txt)
            self.assertIn("source_type: note", txt)

            csv_text = (markdown_root / "devices/router-asus-rt-ax88u/notes/ports.csv.md").read_text(encoding="utf-8")
            self.assertIn("| name | port |", csv_text)
            self.assertIn("| admin | 8443 |", csv_text)

            json_text = (markdown_root / "devices/router-asus-rt-ax88u/notes/settings.json.md").read_text(encoding="utf-8")
            self.assertIn("```json", json_text)
            self.assertIn('"ssid": "fixture"', json_text)

            html_text = (markdown_root / "devices/router-asus-rt-ax88u/notes/admin.html.md").read_text(encoding="utf-8")
            self.assertIn("# Access", html_text)
            self.assertIn("Use router.asus.com.", html_text)

            pdf_text = (markdown_root / "devices/dishwasher-bosch-sms6zcw00g/manuals/user-manual.pdf.md").read_text(encoding="utf-8")
            self.assertIn("source_type: manual", pdf_text)
            self.assertIn("E15 means", pdf_text)

    def test_incremental_skip_and_force_reconvert(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            source_root = workspace / "source_docs"
            markdown_root = workspace / "markdown_docs"
            note = source_root / "devices/router-asus-rt-ax88u/notes/diagnostics.txt"
            note.parent.mkdir(parents=True)
            note.write_text("First version.\n", encoding="utf-8")

            first = convert_tree(source_root, markdown_root)
            second = convert_tree(source_root, markdown_root)
            forced = convert_tree(source_root, markdown_root, force=True)

            self.assertEqual(first.converted, 1)
            self.assertEqual(second.skipped, 1)
            self.assertEqual(forced.converted, 1)

    def test_corrupt_legacy_doc_reports_failure_and_continues(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            source_root = workspace / "source_docs"
            markdown_root = workspace / "markdown_docs"
            docs = source_root / "devices/router-asus-rt-ax88u/notes"
            docs.mkdir(parents=True)
            (docs / "ok.txt").write_text("Keep converting.\n", encoding="utf-8")
            (docs / "broken.doc").write_bytes(b"not a real legacy doc")

            report = convert_tree(source_root, markdown_root)

            self.assertEqual(report.converted, 1)
            self.assertEqual(report.failed, 1)
            failed = [item for item in report.files if item.status == ConversionStatus.FAILED]
            self.assertEqual(len(failed), 1)
            self.assertIn("markitdown", failed[0].error or "")
            self.assertTrue((markdown_root / "devices/router-asus-rt-ax88u/notes/ok.txt.md").exists())

    def test_fail_fast_stops_after_first_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            source_root = workspace / "source_docs"
            markdown_root = workspace / "markdown_docs"
            docs = source_root / "devices/router-asus-rt-ax88u/notes"
            docs.mkdir(parents=True)
            (docs / "a-broken.doc").write_bytes(b"not a real legacy doc")
            (docs / "z-ok.txt").write_text("Should not be converted.\n", encoding="utf-8")

            report = convert_tree(source_root, markdown_root, fail_fast=True)

            self.assertEqual(report.failed, 1)
            self.assertEqual(report.converted, 0)
            self.assertFalse((markdown_root / "devices/router-asus-rt-ax88u/notes/z-ok.txt.md").exists())

    def test_output_path_contract(self) -> None:
        source_root = Path("/tmp/source_docs")
        markdown_root = Path("/tmp/markdown_docs")

        self.assertEqual(
            output_path_for(
                source_root,
                markdown_root,
                source_root / "devices/example/profile.md",
            ),
            markdown_root / "devices/example/profile.md",
        )
        self.assertEqual(
            output_path_for(
                source_root,
                markdown_root,
                source_root / "devices/example/manuals/user-manual.pdf",
            ),
            markdown_root / "devices/example/manuals/user-manual.pdf.md",
        )

    def test_docs_convert_cli_json_report(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            source_root = workspace / "source_docs"
            markdown_root = workspace / "markdown_docs"
            note = source_root / "devices/router-asus-rt-ax88u/notes/diagnostics.txt"
            note.parent.mkdir(parents=True)
            note.write_text("CLI conversion.\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/docs_convert.py"),
                    "--source",
                    str(source_root),
                    "--output",
                    str(markdown_root),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["converted"], 1)
            self.assertTrue((markdown_root / "devices/router-asus-rt-ax88u/notes/diagnostics.txt.md").exists())
