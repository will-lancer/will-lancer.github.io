import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import call, patch

from scripts.sync_substack import (
    DEFAULT_FEED_URL, END_MARKER, START_MARKER, fetch_feed, fetch_posts, main,
    parse_feed, sanitize_content, sync,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "substack-feed.xml"


class SyncSubstackTest(unittest.TestCase):
    def http_error(self, status: int) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(DEFAULT_FEED_URL, status, "Request failed", {}, None)

    def test_fetches_direct_feed(self) -> None:
        with patch("scripts.sync_substack.urllib.request.urlopen", return_value=io.BytesIO(FIXTURE.read_bytes())) as get:
            self.assertEqual(fetch_posts(DEFAULT_FEED_URL), parse_feed(FIXTURE.read_bytes()))
        get.assert_called_once()
        self.assertEqual(get.call_args.args[0].full_url, DEFAULT_FEED_URL)
        self.assertEqual(get.call_args.kwargs["timeout"], 30)

    def test_blocked_direct_feed_uses_fresh_raw_rss_fallback(self) -> None:
        outcomes = [self.http_error(403), io.BytesIO(FIXTURE.read_bytes())]
        with patch("scripts.sync_substack.urllib.request.urlopen", side_effect=outcomes) as get:
            with patch("scripts.sync_substack.time.sleep") as sleep, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(fetch_posts(DEFAULT_FEED_URL), parse_feed(FIXTURE.read_bytes()))
        self.assertEqual(get.call_count, 2)
        request = get.call_args.args[0]
        self.assertEqual(request.full_url, "https://r.jina.ai/" + DEFAULT_FEED_URL)
        self.assertEqual(request.get_header("X-respond-with"), "html")
        self.assertEqual(request.get_header("X-no-cache"), "true")
        sleep.assert_not_called()

    def test_recovers_from_transient_http_and_network_errors(self) -> None:
        errors = [self.http_error(status) for status in (408, 429, 500, 502, 503, 504)]
        errors += [urllib.error.URLError("Connection reset"), TimeoutError("Timed out")]
        for error in errors:
            with self.subTest(error=error), contextlib.redirect_stderr(io.StringIO()):
                with patch("scripts.sync_substack.urllib.request.urlopen", side_effect=[error, io.BytesIO(FIXTURE.read_bytes())]) as get:
                    with patch("scripts.sync_substack.time.sleep") as sleep:
                        self.assertEqual(fetch_feed(DEFAULT_FEED_URL), FIXTURE.read_bytes())
                self.assertEqual(get.call_count, 2)
                sleep.assert_called_once_with(2)

    def test_persistent_failure_exhausts_bounded_retries(self) -> None:
        for error in (self.http_error(503), urllib.error.URLError("Connection reset"), TimeoutError("Timed out")):
            with self.subTest(error=error), contextlib.redirect_stderr(io.StringIO()):
                with patch("scripts.sync_substack.urllib.request.urlopen", side_effect=error) as get:
                    with patch("scripts.sync_substack.time.sleep") as sleep:
                        with self.assertRaises(type(error)):
                            fetch_feed(DEFAULT_FEED_URL)
                self.assertEqual(get.call_count, 3)
                self.assertEqual(sleep.call_args_list, [call(2), call(4)])

    def test_missing_feed_fails_immediately(self) -> None:
        with patch("scripts.sync_substack.urllib.request.urlopen", side_effect=self.http_error(404)) as get:
            with patch("scripts.sync_substack.time.sleep") as sleep:
                with self.assertRaises(urllib.error.HTTPError):
                    fetch_posts(DEFAULT_FEED_URL)
        get.assert_called_once()
        sleep.assert_not_called()

    def test_html_challenge_uses_rss_fallback(self) -> None:
        with patch("scripts.sync_substack.fetch_feed", side_effect=[b"<html/>", FIXTURE.read_bytes()]):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(fetch_posts(DEFAULT_FEED_URL), parse_feed(FIXTURE.read_bytes()))

    def test_rejects_html_and_non_rss_xml(self) -> None:
        for body in (b"<html><body>Just a moment...</body></html>", b"<rss/>", b"<feed/>"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_feed(body)

    def test_rejects_foreign_publications_and_unsafe_post_urls(self) -> None:
        feed = FIXTURE.read_bytes()
        for body in (
            feed.replace(b"<link>https://wlancer.substack.com</link>", b"<link>https://example.com</link>"),
            feed.replace(b"https://wlancer.substack.com/p/newest-post", b"javascript:alert(1)"),
        ):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_feed(body)

    def test_failed_sources_preserve_archive_and_report_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "index.html"
            cache = Path(directory) / "substack-posts.json"
            index.write_bytes(b"Existing page")
            cache.write_bytes(b"Existing cache")
            argv = ["sync_substack.py", "--index", str(index), "--cache", str(cache)]
            for result in (self.http_error(403), b"<html/>", b"broken XML"):
                with self.subTest(result=result), patch("sys.argv", argv):
                    with patch("scripts.sync_substack.fetch_feed", side_effect=[self.http_error(403), result]):
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
