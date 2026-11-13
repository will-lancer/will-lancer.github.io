import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import call, patch

from scripts.sync_substack import (
    DEFAULT_FEED_URL,
    DEFAULT_X_HANDLE,
    END_MARKER,
    START_MARKER,
    extract_x_status_ids_from_html,
    fetch_feed,
    fetch_posts,
    fetch_x_articles,
    main,
    parse_feed,
    parse_fxtwitter_article,
    sanitize_content,
    sync,
    sync_all_posts,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "substack-feed.xml"
X_FIXTURE = ROOT / "tests" / "fixtures" / "x-article.json"


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

    def test_substack_api_fallback_recovers_when_jina_also_fails(self) -> None:
        archive = json.dumps(
            {
                "posts": [
                    {
                        "slug": "api-post",
                        "title": "API post",
                        "subtitle": "Recovered from API.",
                        "canonical_url": "https://wlancer.substack.com/p/api-post",
                        "post_date": "2026-11-12T19:14:09.000Z",
                    }
                ]
            }
        ).encode("utf-8")
        detail = json.dumps(
            {
                "slug": "api-post",
                "title": "API post",
                "subtitle": "Recovered from API.",
                "canonical_url": "https://wlancer.substack.com/p/api-post",
                "post_date": "2026-11-12T19:14:09.000Z",
                "body_html": "<p>Body from API.</p><svg><path d='M0 0'/></svg>",
            }
        ).encode("utf-8")
        outcomes = [self.http_error(403), self.http_error(403), archive, detail]
        with patch("scripts.sync_substack.fetch_feed", side_effect=outcomes):
            with contextlib.redirect_stderr(io.StringIO()):
                posts = fetch_posts(DEFAULT_FEED_URL)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["slug"], "api-post")
        self.assertEqual(posts[0]["content_html"], "<p>Body from API.</p>")

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
                    outcomes = [self.http_error(403), result, self.http_error(403), self.http_error(403)]
                    with patch("scripts.sync_substack.fetch_feed", side_effect=outcomes):
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

    def test_parses_and_renders_x_article_with_styles_links_and_figures(self) -> None:
        payload = json.loads(X_FIXTURE.read_text(encoding="utf-8"))
        article = parse_fxtwitter_article(payload, DEFAULT_X_HANDLE)
        assert article is not None

        self.assertEqual(article["slug"], "two-suggestions-for-improving-automated-math-and-physics")
        self.assertEqual(article["source"], "x")
        self.assertEqual(article["category"], "X Article")
        self.assertEqual(article["url"], "https://x.com/wmlancer/status/2118033420706038023")
        self.assertEqual(article["published"], "2026-11-04T17:31:33+00:00")
        self.assertIn("<em>Remark: </em>", article["content_html"])
        self.assertIn('href="https://resolution.org/?x=1"', article["content_html"])
        self.assertIn("<h2>Do supervised fine-tuning to make LLM writing better.</h2>", article["content_html"])
        self.assertIn('<img src="https://pbs.twimg.com/media/HWS5P2fXgAE7l6T.png"', article["content_html"])
        self.assertIn("<figcaption>How well-written papers are structured.</figcaption>", article["content_html"])

        payload["tweet"]["author"]["screen_name"] = "impostor"
        with self.assertRaises(ValueError):
            parse_fxtwitter_article(payload, DEFAULT_X_HANDLE)

    def test_discovers_only_unseen_x_statuses_and_merges_chronologically(self) -> None:
        html_sample = """
        <a href="/wmlancer/status/2118033420706038023">Nov 4</a>
        <a href="/wmlancer/status/2118393600354447757">Nov 5</a>
        <a href="/someoneelse/status/1946477742855532918">Quote</a>
        """
        self.assertEqual(
            extract_x_status_ids_from_html(html_sample, "wmlancer"),
            ["2118393600354447757", "2118033420706038023"],
        )

        article_payload = X_FIXTURE.read_bytes()
        non_article_payload = json.dumps(
            {
                "code": 200,
                "tweet": {
                    "id": "2118393600354447757",
                    "author": {"screen_name": "wmlancer"},
                    "text": "Short post, not an article.",
                },
            }
        ).encode("utf-8")

        with patch("scripts.sync_substack.discover_x_status_ids", return_value=["2118393600354447757", "2118033420706038023"]):
            with patch("scripts.sync_substack.fetch_feed", side_effect=[article_payload]) as get:
                articles, seen_ids = fetch_x_articles("wmlancer", known_status_ids={"2118393600354447757"})
        get.assert_called_once()
        self.assertEqual(len(articles), 1)
        self.assertEqual(seen_ids, ["2118393600354447757", "2118033420706038023"])

        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            index = temp / "index.html"
            substack_cache = temp / "substack-posts.json"
            x_cache = temp / "x-articles.json"
            index.write_text(f"<section>\n  {START_MARKER}\n  {END_MARKER}\n</section>\n", encoding="utf-8")

            substack_posts = parse_feed(FIXTURE.read_bytes())
            count, changed = sync_all_posts(
                substack_posts,
                index,
                substack_cache,
                x_posts=articles,
                x_cache_path=x_cache,
                x_handle="wmlancer",
                x_status_ids=seen_ids,
            )
            rendered = index.read_text(encoding="utf-8")
            self.assertTrue(changed)
            self.assertEqual(count, 3)
            # Nov 2026 X Article appears above Aug 2026 Substack fixture posts.
            self.assertLess(rendered.index("data-x-article"), rendered.index("data-substack-post"))
            self.assertIn(">X</a>", rendered)

            # A subsequent run where X fails (x_posts=None) preserves the cached X article!
            count_after, changed_after = sync_all_posts(
                substack_posts,
                index,
                substack_cache,
                x_posts=None,
                x_cache_path=x_cache,
                x_handle="wmlancer",
            )
            self.assertEqual(count_after, 3)
            self.assertFalse(changed_after)


if __name__ == "__main__":
    unittest.main()
