import json
import tempfile
import unittest
from pathlib import Path

from scripts.sync_substack import END_MARKER, START_MARKER, api_post_to_entry, sync


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "substack-feed.xml"


class SyncSubstackTest(unittest.TestCase):
    def test_converts_public_api_posts(self) -> None:
        post = api_post_to_entry(
            {
                "slug": "api-post",
                "canonical_url": "https://wlancer.substack.com/p/api-post",
                "post_date": "2026-08-25T18:00:00.000Z",
                "title": "API post",
                "subtitle": "From the public archive.",
                "body_html": "<p>Safe body.</p><script>bad()</script>",
                "postTags": [{"name": "Physics"}],
            }
        )

        self.assertEqual(post["slug"], "api-post")
        self.assertEqual(post["category"], "Physics")
        self.assertIn("Safe body.", post["content_html"])
        self.assertNotIn("bad()", post["content_html"])

    def test_adds_new_posts_safely_and_keeps_manual_posts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            index = temp / "index.html"
            cache = temp / "substack-posts.json"
            index.write_text(
                f'''<section>
  {START_MARKER}
  {END_MARKER}
  <article id="manual-post" data-post><p>Hand-written copy.</p></article>
</section>
''',
                encoding="utf-8",
            )

            count, changed = sync(FIXTURE.read_bytes(), index, cache)
            rendered = index.read_text(encoding="utf-8")

            self.assertTrue(changed)
            self.assertEqual(count, 1)
            self.assertIn('id="newest-post"', rendered)
            self.assertEqual(rendered.count('id="manual-post"'), 1)
            self.assertIn("https://example.com/?x=1", rendered)
            self.assertIn("#substack-newest-post-note-1", rendered)
            self.assertIn('id="substack-newest-post-note-1"', rendered)
            self.assertIn("The note.", rendered)
            self.assertIn('data-katex data-display="true">E = mc^2</div>', rendered)
            self.assertNotIn("subscription-widget", rendered)
            self.assertNotIn("alert", rendered)
            self.assertEqual(json.loads(cache.read_text())["posts"][0]["slug"], "newest-post")

            second_count, second_changed = sync(FIXTURE.read_bytes(), index, cache)
            self.assertEqual(second_count, 1)
            self.assertFalse(second_changed)


if __name__ == "__main__":
    unittest.main()
