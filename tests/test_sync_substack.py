import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from curl_cffi import requests

from scripts.sync_substack import (
    DEFAULT_FEED_URL, END_MARKER, START_MARKER, fetch_feed, main,
    parse_feed, sanitize_content, sync,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "substack-feed.xml"


class SyncSubstackTest(unittest.TestCase):
    def response(self, status: int = 200) -> Mock:
        response = Mock(status_code=status, content=FIXTURE.read_bytes())
        if status >= 400:
            response.raise_for_status.side_effect = requests.RequestsError(f"HTTP {status}")
        return response

    def test_fetches_rss_with_browser_transport(self) -> None:
        with patch("scripts.sync_substack.requests.get", return_value=self.response()) as get:
            self.assertEqual(fetch_feed(DEFAULT_FEED_URL), FIXTURE.read_bytes())
        get.assert_called_once_with(DEFAULT_FEED_URL, impersonate="chrome", timeout=30)

    def test_recovers_from_blocking_and_transient_http_errors(self) -> None:
        for status in (403, 408, 429, 500, 502, 503, 504):
            with self.subTest(status=status), contextlib.redirect_stderr(io.StringIO()):
                with patch("scripts.sync_substack.requests.get", side_effect=[self.response(status), self.response()]) as get:
                    with patch("scripts.sync_substack.time.sleep") as sleep:
                        self.assertEqual(fetch_feed(DEFAULT_FEED_URL), FIXTURE.read_bytes())
                self.assertEqual(get.call_count, 2)
                sleep.assert_called_once_with(2)

    def test_recovers_from_network_errors(self) -> None:
        with patch("scripts.sync_substack.requests.get", side_effect=[requests.RequestsError("Timed out"), self.response()]) as get:
            with patch("scripts.sync_substack.time.sleep"), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(fetch_feed(DEFAULT_FEED_URL), FIXTURE.read_bytes())
        self.assertEqual(get.call_count, 2)

    def test_persistent_failure_exhausts_bounded_retries(self) -> None:
        for outcome in (self.response(403), requests.RequestsError("Timed out")):
            with self.subTest(outcome=outcome), contextlib.redirect_stderr(io.StringIO()):
                with patch("scripts.sync_substack.requests.get", side_effect=[outcome] * 3) as get:
                    with patch("scripts.sync_substack.time.sleep") as sleep:
                        with self.assertRaises(requests.RequestsError):
                            fetch_feed(DEFAULT_FEED_URL)
                self.assertEqual(get.call_count, 3)
                self.assertEqual(sleep.call_args_list, [call(2), call(4)])

    def test_permanent_http_error_fails_immediately(self) -> None:
        with patch("scripts.sync_substack.requests.get", return_value=self.response(404)) as get:
            with patch("scripts.sync_substack.time.sleep") as sleep:
                with self.assertRaises(requests.RequestsError):
                    fetch_feed(DEFAULT_FEED_URL)
        get.assert_called_once()
        sleep.assert_not_called()

    def test_rejects_html_and_non_rss_xml(self) -> None:
        for body in (b"<html><body>Just a moment...</body></html>", b"<rss/>", b"<feed/>"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_feed(body)

    def test_failed_fetch_or_invalid_feed_preserves_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "index.html"
            cache = Path(directory) / "substack-posts.json"
            index.write_bytes(b"Existing page")
            cache.write_bytes(b"Existing cache")
            argv = ["sync_substack.py", "--index", str(index), "--cache", str(cache)]
            for result in (requests.RequestsError("HTTP 403"), b"<html/>", b"broken XML"):
                with self.subTest(result=result), patch("sys.argv", argv):
                    with patch("scripts.sync_substack.fetch_feed", side_effect=[result]):
                        with contextlib.redirect_stderr(io.StringIO()) as stderr:
                            self.assertEqual(main(), 1)
                    self.assertIn("Substack sync failed:", stderr.getvalue())
                    self.assertEqual(index.read_bytes(), b"Existing page")
                    self.assertEqual(cache.read_bytes(), b"Existing cache")

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
