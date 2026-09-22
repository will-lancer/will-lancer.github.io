import json
import tempfile
import unittest
from pathlib import Path

from scripts.sync_substack import END_MARKER, START_MARKER, rss2json_item_to_entry, sanitize_content, sync


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "substack-feed.xml"


class SyncSubstackTest(unittest.TestCase):
    def test_converts_proxy_posts(self) -> None:
        post = rss2json_item_to_entry(
            {
                "guid": "https://wlancer.substack.com/p/proxy-post",
                "link": "https://wlancer.substack.com/p/proxy-post",
                "pubDate": "2026-08-25 18:00:00",
                "title": "Proxy post",
                "description": "From the RSS proxy.",
                "content": "<p>Safe body.</p><script>bad()</script>",
                "categories": ["Physics"],
            }
        )

        self.assertEqual(post["slug"], "proxy-post")
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

    def test_keeps_mention_names_and_local_footnotes(self) -> None:
        markup = """
        <p>See <a href="https://wlancer.substack.com/#footnote-1">1</a></p>
        <div class="footnote">
          <a id="footnote-1" href="https://wlancer.substack.com/#footnote-anchor-1">1</a>
          <div class="footnote-content">
            <p>Shoutout <span class="mention-wrap" data-component-name="MentionToDOM" data-attrs='{"name": "Miles K. Donahue", "url": null}'></span> now.</p>
          </div>
        </div>
        """
        rendered = sanitize_content(markup, "newest-post", "https://wlancer.substack.com/p/newest-post")
        self.assertIn("Miles K. Donahue", rendered)
        self.assertNotIn("mention-wrap", rendered)
        self.assertIn('href="#substack-newest-post-footnote-1"', rendered)
        self.assertIn('id="substack-newest-post-footnote-1"', rendered)
        self.assertNotIn("wlancer.substack.com/#", rendered)


if __name__ == "__main__":
    unittest.main()
