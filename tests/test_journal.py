"""Check publishing boundaries and attachment handling without external packages."""

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_journal", ROOT / "scripts/build_journal.py")
journal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journal)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "_journal", self.root / "_journal")
        for source in (self.root / "_journal/entries").glob("*.json"):
            source.unlink()
        (self.root / "journal/media/2026-10-26").mkdir(parents=True)
        self.entry = {
            "date": "2026-10-26", "title": "Work & questions", "kind": "entry",
            "draft": False, "tags": ["AI safety", "QFT"], "ai_safety_hours": 3.5,
            "blocks": [{"type": "paragraph", "text": "A <script> tag & some work."}],
        }

    def tearDown(self):
        self.temp.cleanup()

    def write_entry(self, name="2026-10-26-work", entry=None):
        (self.root / "_journal/entries" / f"{name}.json").write_text(json.dumps(entry or self.entry))

    def test_published_content_and_draft_exclusion(self):
        self.write_entry()
        draft = copy.deepcopy(self.entry)
        draft.update(draft=True, title="UNPUBLISHED MATERIAL")
        self.write_entry("2026-10-26-draft", draft)
        page = journal.render(self.root)
        self.assertNotIn("UNPUBLISHED MATERIAL", page)
        self.assertIn("A &lt;script&gt; tag &amp; some work.", page)
        self.assertIn("3.5h logged", page)
        self.assertIn("1 day logged", page)
        self.assertIn('content="noindex, nofollow, noarchive"', page)
        self.assertIn('href="#2026-10-26-work"', page)
        self.assertNotIn("@@", page)

    def test_newest_first_and_unique_day_count(self):
        self.write_entry()
        second = copy.deepcopy(self.entry)
        second.update(title="Second entry")
        self.write_entry("2026-10-26-second", second)
        older = copy.deepcopy(self.entry)
        older.update(date="2026-10-25", kind="note")
        self.write_entry("2026-10-25-note", older)
        page = journal.render(self.root)
        self.assertLess(page.index('id="2026-10-26-work"'), page.index('id="2026-10-25-note"'))
        self.assertIn("1 day logged", page)

    def test_image_and_pdf_links(self):
        media = self.root / "journal/media/2026-10-26"
        (media / "work sheet.pdf").write_bytes(b"%PDF-1.4\n")
        (media / "notes.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        self.entry["blocks"] += [
            {"type": "image", "src": "media/2026-10-26/notes.png", "alt": "Notes <1>", "caption": "Page one"},
            {"type": "pdf", "src": "media/2026-10-26/work sheet.pdf", "title": "Work sheet"},
        ]
        self.write_entry()
        page = journal.render(self.root)
        self.assertIn('alt="Notes &lt;1&gt;"', page)
        self.assertIn('href="media/2026-10-26/work%20sheet.pdf" download', page)
        self.assertIn('data-src="media/2026-10-26/work%20sheet.pdf#view=FitH"', page)
        self.assertIn('<summary>Read PDF here</summary>', page)

    def test_missing_and_outside_attachments_fail(self):
        (self.root / "outside.pdf").write_bytes(b"%PDF-1.4\n")
        for source in ["media/missing.pdf", "../outside.pdf", "media/../../outside.pdf", "https://example.org/work.pdf"]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                journal.render_block({"type": "pdf", "src": source, "title": "Work"}, self.root)

    def test_unsafe_links_and_invalid_hours_fail(self):
        with self.assertRaises(ValueError):
            journal.render_block({"type": "link", "url": "javascript:alert(1)", "text": "Unsafe"}, self.root)
        for hours in [-1, 25, True, float("nan")]:
            with self.subTest(hours=hours), self.assertRaises(ValueError):
                self.entry["ai_safety_hours"] = hours
                self.write_entry()
                journal.render(self.root)


if __name__ == "__main__":
    unittest.main()
