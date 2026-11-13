#!/usr/bin/env python3
"""Sync Substack posts and X Articles into the static blog archive."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEED_URL = "https://wlancer.substack.com/feed"
DEFAULT_X_HANDLE = "wmlancer"
DEFAULT_INDEX = ROOT / "blog" / "index.html"
DEFAULT_CACHE = ROOT / "blog" / "substack-posts.json"
DEFAULT_X_CACHE = ROOT / "blog" / "x-articles.json"
START_MARKER = "<!-- BEGIN AUTO-SYNCED SUBSTACK POSTS -->"
END_MARKER = "<!-- END AUTO-SYNCED SUBSTACK POSTS -->"
CONTENT_NAMESPACE = "http://purl.org/rss/1.0/modules/content/"
PACIFIC = ZoneInfo("America/Los_Angeles")
FETCH_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
)

ALLOWED_TAGS = {
    "a",
    "b",
    "blockquote",
    "br",
    "code",
    "div",
    "em",
    "figcaption",
    "figure",
    "h2",
    "h3",
    "h4",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "span",
    "strong",
    "sub",
    "sup",
    "ul",
}
VOID_TAGS = {"br", "hr", "img"}
HTML_VOID_TAGS = VOID_TAGS | {
    "area",
    "base",
    "col",
    "embed",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
DROP_WITH_CONTENT = {"button", "form", "iframe", "noscript", "object", "script", "style", "svg"}
DROP_VOID = {"embed", "input", "source"}
BLOCK_TAGS = {"blockquote", "div", "figcaption", "figure", "h2", "h3", "h4", "hr", "li", "ol", "p", "pre", "ul"}
SAFE_CLASSES = {"footnote", "footnote-anchor", "footnote-content", "footnote-number"}


def clean_url(value: str, base_url: str, anchor_prefix: str) -> str | None:
    value = value.strip()
    if value.startswith("#"):
        return f"#{anchor_prefix}{value[1:]}"

    absolute = urljoin(base_url, value)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https", "mailto"}:
        return None
    if parsed.scheme == "mailto":
        return absolute

    # Feed proxies expand in-article anchors to the publication home.
    # Keep those on this page, beside the prefixed footnote ids.
    if parsed.fragment:
        base = urlparse(base_url)
        publication = urlparse(DEFAULT_FEED_URL)
        same_document = parsed.netloc == base.netloc and parsed.path.rstrip("/") == base.path.rstrip("/")
        publication_home = parsed.netloc == publication.netloc and parsed.path in {"", "/"}
        if same_document or publication_home:
            return f"#{anchor_prefix}{parsed.fragment}"

    query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if not key.startswith("utm_")]
    return urlunparse(parsed._replace(query=urlencode(query)))


def safe_identifier(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")
    return cleaned or "item"


def slugify_title(value: str, fallback: str = "article") -> str:
    words = re.findall(r"[a-z0-9]+", value.lower())
    if not words:
        return safe_identifier(fallback)
    return "-".join(words[:8])


def mention_html(attrs: dict[str, str]) -> str | None:
    """Substack mentions store the visible name only in a data attribute."""
    classes = set(attrs.get("class", "").split())
    if attrs.get("data-component-name") != "MentionToDOM" and "mention-wrap" not in classes:
        return None
    try:
        data = json.loads(attrs.get("data-attrs", ""))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    name = str(data.get("name") or "").strip()
    if not name:
        return None
    url = data.get("url")
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        href = html.escape(url, quote=True)
        return f'<a href="{href}" target="_blank" rel="noopener">{html.escape(name)}</a>'
    return html.escape(name)


class SafeSubstackHTML(HTMLParser):
    """Keep article markup while dropping forms, scripts, widgets, and unsafe attributes."""

    def __init__(self, slug: str, base_url: str, *, anchor_namespace: str = "substack") -> None:
        super().__init__(convert_charrefs=True)
        self.anchor_prefix = f"{safe_identifier(anchor_namespace)}-{safe_identifier(slug)}-"
        self.base_url = base_url
        self.output: list[str] = []
        self.stack: list[str | None] = []
        self.skip_depth = 0
        self.math_depth = 0
        self.math_display = False
        self.math_collect = False
        self.math_tex: list[str] = []

    def _widget(self, attrs: dict[str, str]) -> bool:
        classes = set(attrs.get("class", "").split())
        component = attrs.get("data-component-name", "")
        return any("subscription-widget" in name for name in classes) or component in {
            "RecommendationUnitToDOM",
            "SubscribeButtonToDOM",
            "SubscribeWidgetToDOM",
        }

    def _mapped_tag(self, tag: str, attrs: dict[str, str]) -> str | None:
        if tag not in ALLOWED_TAGS:
            return None
        if tag != "div":
            return tag
        classes = set(attrs.get("class", "").split())
        return "div" if classes & {"footnote", "footnote-content"} else None

    def _safe_attrs(self, tag: str, attrs: dict[str, str]) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []

        element_id = attrs.get("id")
        if element_id:
            result.append(("id", self.anchor_prefix + safe_identifier(element_id)))

        classes = [name for name in attrs.get("class", "").split() if name in SAFE_CLASSES]
        if classes:
            result.append(("class", " ".join(classes)))

        if tag == "a" and attrs.get("href"):
            href = clean_url(attrs["href"], self.base_url, self.anchor_prefix)
            if href:
                result.append(("href", href))
                if href.startswith(("http://", "https://")):
                    result.extend((("target", "_blank"), ("rel", "noopener")))
            if attrs.get("title"):
                result.append(("title", attrs["title"]))

        if tag == "img" and attrs.get("src"):
            src = clean_url(attrs["src"], self.base_url, self.anchor_prefix)
            if src and src.startswith(("http://", "https://")):
                result.extend((("src", src), ("loading", "lazy"), ("decoding", "async")))
                for name in ("alt", "title", "width", "height"):
                    if attrs.get(name):
                        result.append((name, attrs[name]))

        return result

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs = {key.lower(): value or "" for key, value in attrs_list}
        if self.math_depth:
            if tag not in HTML_VOID_TAGS:
                self.math_depth += 1
            if tag == "annotation" and attrs.get("encoding") == "application/x-tex":
                self.math_collect = True
            return
        classes = set(attrs.get("class", "").split())
        if tag == "span" and classes & {"katex", "katex-display"}:
            self.math_depth = 1
            self.math_display = "katex-display" in classes
            self.math_collect = False
            self.math_tex = []
            return
        if self.skip_depth:
            if tag not in HTML_VOID_TAGS:
                self.skip_depth += 1
            return
        if tag in DROP_VOID:
            return
        if tag in DROP_WITH_CONTENT or self._widget(attrs):
            if tag not in HTML_VOID_TAGS:
                self.skip_depth = 1
            return
        if tag == "span" and (mention := mention_html(attrs)):
            self.output.append(mention)
            self.stack.append(None)
            return

        mapped = self._mapped_tag(tag, attrs)
        if tag not in HTML_VOID_TAGS:
            self.stack.append(mapped)
        if mapped is None:
            return

        safe_attrs = "".join(
            f' {name}="{html.escape(value, quote=True)}"' for name, value in self._safe_attrs(mapped, attrs)
        )
        self.output.append(f"<{mapped}{safe_attrs}>")
        if mapped == "hr":
            self.output.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip_depth or self.math_depth:
            return
        self.handle_starttag(tag, attrs)
        if tag.lower() not in HTML_VOID_TAGS and not self.skip_depth:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.math_depth:
            if tag.lower() == "annotation":
                self.math_collect = False
            self.math_depth -= 1
            if self.math_depth == 0:
                tex = "".join(self.math_tex).strip()
                if tex:
                    if self.math_display:
                        self.output.append(
                            f'<div class="display-math" data-katex data-display="true">{html.escape(tex)}</div>\n'
                        )
                    else:
                        self.output.append(f"<span data-katex>{html.escape(tex)}</span>")
                self.math_display = False
                self.math_tex = []
            return
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if tag.lower() in HTML_VOID_TAGS or not self.stack:
            return
        mapped = self.stack.pop()
        if mapped:
            self.output.append(f"</{mapped}>")
            if mapped in BLOCK_TAGS:
                self.output.append("\n")

    def handle_data(self, data: str) -> None:
        if self.math_depth:
            if self.math_collect:
                self.math_tex.append(data)
            return
        if not self.skip_depth:
            self.output.append(html.escape(data, quote=False))

    def result(self) -> str:
        text = "".join(self.output)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


class PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_text(markup: str) -> str:
    parser = PlainText()
    parser.feed(markup)
    return " ".join("".join(parser.parts).split())


def sanitize_content(markup: str, slug: str, base_url: str, *, anchor_namespace: str = "substack") -> str:
    parser = SafeSubstackHTML(slug, base_url, anchor_namespace=anchor_namespace)
    parser.feed(markup)
    parser.close()
    return parser.result()


def post_slug(link: str, guid: str, title: str) -> str:
    for candidate in (link, guid):
        path_name = Path(urlparse(candidate).path).name
        if path_name:
            return safe_identifier(path_name.lower())
    return safe_identifier(title.lower())


def parse_iso_utc(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_feed(feed_bytes: bytes, feed_url: str = DEFAULT_FEED_URL) -> list[dict[str, str]]:
    root = ET.fromstring(feed_bytes)
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("Expected an RSS feed with a channel")
    source_host = urlparse(feed_url).hostname
    publication = urlparse(root.findtext("channel/link") or "")
    if publication.scheme not in {"http", "https"} or publication.hostname != source_host:
        raise ValueError("RSS feed does not match the requested publication")
    posts: list[dict[str, str]] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "Untitled").strip()
        link = (item.findtext("link") or "").strip()
        parsed_link = urlparse(link)
        if parsed_link.scheme not in {"http", "https"} or parsed_link.hostname != source_host:
            raise ValueError("RSS post URL does not match the requested publication")
        guid = (item.findtext("guid") or link).strip()
        slug = post_slug(link, guid, title)
        published = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(timezone.utc)
        description_markup = item.findtext("description") or ""
        raw_content = item.findtext(f"{{{CONTENT_NAMESPACE}}}encoded") or description_markup
        content = sanitize_content(raw_content, slug, link or DEFAULT_FEED_URL)
        categories = [text.strip() for node in item.findall("category") if (text := node.text)]
        posts.append(
            {
                "slug": slug,
                "title": title,
                "subtitle": plain_text(description_markup),
                "url": link,
                "published": published.isoformat(timespec="seconds"),
                "category": categories[0] if categories else "Substack",
                "source": "substack",
                "source_label": "Substack",
                "content_html": content,
            }
        )
    return posts


def rss2json_item_to_entry(item: dict[str, object], feed_url: str = DEFAULT_FEED_URL) -> dict[str, str]:
    source_host = urlparse(feed_url).hostname
    link = str(item.get("link") or "").strip()
    parsed_link = urlparse(link)
    if parsed_link.scheme not in {"http", "https"} or parsed_link.hostname != source_host:
        raise ValueError("Proxy RSS post URL does not match the requested publication")
    title = str(item.get("title") or "Untitled").strip()
    slug = post_slug(link, str(item.get("guid") or link), title)
    raw_content = str(item.get("content") or item.get("description") or "")
    pub_text = str(item.get("pubDate") or "").strip()
    published = datetime.strptime(pub_text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    raw_categories = item.get("categories")
    categories = [str(cat).strip() for cat in raw_categories if str(cat).strip()] if isinstance(raw_categories, list) else []
    return {
        "slug": slug,
        "title": title,
        "subtitle": plain_text(str(item.get("description") or "")),
        "url": link,
        "published": published.isoformat(timespec="seconds"),
        "category": categories[0] if categories else "Substack",
        "source": "substack",
        "source_label": "Substack",
        "content_html": sanitize_content(raw_content, slug, link),
    }


def format_published(value: str) -> tuple[str, str]:
    published = datetime.fromisoformat(value).astimezone(PACIFIC)
    hour = published.hour % 12 or 12
    display = (
        f"{published.strftime('%B')} {published.day}, {published.year} at "
        f"{hour}:{published.strftime('%M:%S %p %Z')}"
    )
    return published.isoformat(timespec="seconds"), display


def reading_time(content_html: str) -> int:
    words = len(re.findall(r"\b[\w’'-]+\b", plain_text(content_html)))
    return max(1, (words + 219) // 220)


def indent_content(content: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else "" for line in content.splitlines())


def infer_source(post: dict[str, str]) -> tuple[str, str]:
    source = post.get("source")
    if source == "x" or urlparse(post.get("url", "")).hostname in {"x.com", "www.x.com", "twitter.com"}:
        return "x", post.get("source_label") or "X"
    return "substack", post.get("source_label") or "Substack"


def render_post(post: dict[str, str]) -> str:
    slug = safe_identifier(post["slug"])
    title = html.escape(post["title"])
    subtitle = html.escape(post.get("subtitle", ""))
    source_kind, source_label_raw = infer_source(post)
    default_category = "X Article" if source_kind == "x" else "Substack"
    category = html.escape(post.get("category") or default_category)
    source_label = html.escape(source_label_raw)
    source_attr = "data-x-article" if source_kind == "x" else "data-substack-post"
    url = html.escape(post["url"], quote=True)
    machine_date, display_date = format_published(post["published"])
    minutes = reading_time(post["content_html"])
    subtitle_html = f'\n              <p class="post-subtitle">{subtitle}</p>' if subtitle else ""
    content = indent_content(post["content_html"], 14)
    return f'''          <article class="post" id="{slug}" {source_attr} data-post>
            <header class="post-header">
              <p class="post-category">{category}</p>
              <h2>{title}</h2>
              <p class="post-meta">
                <time datetime="{machine_date}">{display_date}</time>
                <span aria-hidden="true">&middot;</span>
                <span>{minutes} min read</span>
                <span aria-hidden="true">&middot;</span>
                <a href="{url}" target="_blank" rel="noopener">{source_label}</a>
              </p>{subtitle_html}
            </header>
            <div class="post-preview" id="post-{slug}" data-post-preview>
{content}
            </div>
            <div class="post-fade" aria-hidden="true"></div>
            <button class="read-more" type="button" aria-expanded="false" aria-controls="post-{slug}" data-read-more>
              <span data-read-more-label>Continue reading</span>
              <span aria-hidden="true" data-read-more-arrow>&darr;</span>
            </button>
          </article>'''


def load_cache(path: Path, expected_feed_url: str = DEFAULT_FEED_URL) -> list[dict[str, str]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("feed_url") != expected_feed_url or not isinstance(data.get("posts"), list):
        raise ValueError(f"Unexpected cache format in {path}")
    return data["posts"]


def load_x_cache(path: Path, handle: str = DEFAULT_X_HANDLE) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    data = json.loads(path.read_text(encoding="utf-8"))
    cached_handle = str(data.get("handle") or "").lstrip("@").lower()
    if cached_handle != handle.lstrip("@").lower() or not isinstance(data.get("posts"), list):
        raise ValueError(f"Unexpected X cache format in {path}")
    raw_ids = data.get("status_ids", [])
    status_ids = [str(sid) for sid in raw_ids if str(sid).isdigit()] if isinstance(raw_ids, list) else []
    return data["posts"], status_ids


def manual_post_ids(index_html: str, start: int, end: int) -> set[str]:
    outside_managed_block = index_html[:start] + index_html[end + len(END_MARKER) :]
    return set(re.findall(r'<article\b[^>]*\bid="([^"]+)"[^>]*\bdata-post\b', outside_managed_block))


def update_index(index_html: str, posts: list[dict[str, str]]) -> str:
    start = index_html.index(START_MARKER) + len(START_MARKER)
    end = index_html.index(END_MARKER, start)
    rendered = "\n\n" + "\n\n".join(render_post(post) for post in posts) + "\n\n          " if posts else "\n          "
    return index_html[:start] + rendered + index_html[end:]


def merge_cached_posts(
    existing: list[dict[str, str]],
    incoming: list[dict[str, str]] | None,
    manual_ids: set[str],
) -> list[dict[str, str]]:
    merged = {post["slug"]: post for post in existing}
    if incoming is not None:
        for post in incoming:
            if post["slug"] not in manual_ids:
                merged[post["slug"]] = post
    for slug in manual_ids:
        merged.pop(slug, None)
    return sorted(merged.values(), key=lambda post: post["published"], reverse=True)


def sync_all_posts(
    substack_posts: list[dict[str, str]] | None,
    index_path: Path,
    cache_path: Path,
    *,
    feed_url: str = DEFAULT_FEED_URL,
    x_posts: list[dict[str, str]] | None = None,
    x_cache_path: Path | None = None,
    x_handle: str = DEFAULT_X_HANDLE,
    x_status_ids: list[str] | None = None,
) -> tuple[int, bool]:
    index_html = index_path.read_text(encoding="utf-8")
    start = index_html.index(START_MARKER) + len(START_MARKER)
    end = index_html.index(END_MARKER, start)
    manual_ids = manual_post_ids(index_html, start, end)

    merged_substack = merge_cached_posts(load_cache(cache_path, feed_url), substack_posts, manual_ids)

    merged_x: list[dict[str, str]] = []
    final_status_ids: list[str] = []
    if x_cache_path is not None:
        existing_x, existing_ids = load_x_cache(x_cache_path, x_handle)
        merged_x = merge_cached_posts(existing_x, x_posts, manual_ids)
        combined_ids = set(existing_ids) | set(x_status_ids or [])
        for post in merged_x:
            if (sid := post.get("status_id", "")) and sid.isdigit():
                combined_ids.add(sid)
        final_status_ids = sorted(combined_ids, key=int, reverse=True)

    combined = sorted(merged_substack + merged_x, key=lambda post: post["published"], reverse=True)
    new_index = update_index(index_html, combined)

    substack_cache_text = json.dumps({"feed_url": feed_url, "posts": merged_substack}, ensure_ascii=False, indent=2) + "\n"
    old_substack_cache = cache_path.read_text(encoding="utf-8") if cache_path.exists() else ""
    substack_changed = substack_cache_text != old_substack_cache

    x_changed = False
    x_cache_text = ""
    if x_cache_path is not None and (x_posts is not None or x_cache_path.exists()):
        clean_handle = x_handle.lstrip("@")
        x_payload = {
            "handle": clean_handle,
            "profile_url": f"https://x.com/{clean_handle}",
            "status_ids": final_status_ids,
            "posts": merged_x,
        }
        x_cache_text = json.dumps(x_payload, ensure_ascii=False, indent=2) + "\n"
        old_x_cache = x_cache_path.read_text(encoding="utf-8") if x_cache_path.exists() else ""
        x_changed = x_cache_text != old_x_cache

    index_changed = new_index != index_html
    changed = index_changed or substack_changed or x_changed
    if index_changed:
        index_path.write_text(new_index, encoding="utf-8")
    if substack_changed:
        cache_path.write_text(substack_cache_text, encoding="utf-8")
    if x_changed and x_cache_path is not None:
        x_cache_path.write_text(x_cache_text, encoding="utf-8")
    return len(combined), changed


def sync_posts(feed_posts: list[dict[str, str]], index_path: Path, cache_path: Path) -> tuple[int, bool]:
    return sync_all_posts(feed_posts, index_path, cache_path)


def sync(feed_bytes: bytes, index_path: Path, cache_path: Path) -> tuple[int, bool]:
    return sync_posts(parse_feed(feed_bytes), index_path, cache_path)


def fetch_feed(url: str, *, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": BROWSER_USER_AGENT, **(headers or {})},
    )
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in RETRYABLE_STATUS_CODES or attempt == FETCH_ATTEMPTS:
                raise
            reason = f"HTTP {error.code}"
        except (urllib.error.URLError, TimeoutError):
            if attempt == FETCH_ATTEMPTS:
                raise
            reason = "network error"
        delay = 2 ** attempt
        print(f"Feed request failed ({reason}); retrying in {delay}s.", file=sys.stderr)
        time.sleep(delay)
    raise RuntimeError("Feed fetch exhausted its retry attempts")


def fetch_substack_api_posts(feed_url: str) -> list[dict[str, str]]:
    parsed = urlparse(feed_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    archive_raw = fetch_feed(
        f"{origin}/api/v1/archive?sort=new&limit=15",
        headers={"Accept": "application/json"},
    )
    archive = json.loads(archive_raw)
    items = archive if isinstance(archive, list) else archive.get("posts") if isinstance(archive, dict) else None
    if not isinstance(items, list):
        raise ValueError("Unexpected Substack archive API response")

    posts: list[dict[str, str]] = []
    for summary in items:
        if not isinstance(summary, dict) or not summary.get("slug"):
            continue
        slug = safe_identifier(str(summary["slug"]).lower())
        detail_raw = fetch_feed(f"{origin}/api/v1/posts/{quote(str(summary['slug']))}", headers={"Accept": "application/json"})
        detail = json.loads(detail_raw)
        if not isinstance(detail, dict):
            continue
        link = str(detail.get("canonical_url") or summary.get("canonical_url") or f"{origin}/p/{slug}").strip()
        if urlparse(link).hostname != parsed.hostname:
            raise ValueError("Substack API post URL does not match the requested publication")
        title = str(detail.get("title") or summary.get("title") or "Untitled").strip()
        subtitle = plain_text(str(detail.get("subtitle") or detail.get("description") or summary.get("subtitle") or ""))
        published = parse_iso_utc(str(detail.get("post_date") or summary.get("post_date") or ""))
        body_html = str(detail.get("body_html") or "")
        posts.append(
            {
                "slug": slug,
                "title": title,
                "subtitle": subtitle,
                "url": link,
                "published": published.isoformat(timespec="seconds"),
                "category": "Substack",
                "source": "substack",
                "source_label": "Substack",
                "content_html": sanitize_content(body_html, slug, link),
            }
        )
    return posts


def fetch_rss2json_posts(feed_url: str) -> list[dict[str, str]]:
    proxy_url = f"https://api.rss2json.com/v1/api.json?rss_url={quote(feed_url, safe='')}"
    payload = json.loads(fetch_feed(proxy_url, headers={"Accept": "application/json"}))
    if not isinstance(payload, dict) or payload.get("status") != "ok" or not isinstance(payload.get("items"), list):
        raise ValueError("rss2json returned an unexpected response")
    feed_info = payload.get("feed")
    if not isinstance(feed_info, dict) or urlparse(str(feed_info.get("link") or "")).hostname != urlparse(feed_url).hostname:
        raise ValueError("rss2json feed does not match the requested publication")
    return [rss2json_item_to_entry(item, feed_url) for item in payload["items"] if isinstance(item, dict)]


def fetch_posts(feed_url: str) -> list[dict[str, str]]:
    try:
        return parse_feed(fetch_feed(feed_url), feed_url)
    except (urllib.error.URLError, TimeoutError, ET.ParseError, ValueError) as error:
        if isinstance(error, urllib.error.HTTPError) and error.code not in RETRYABLE_STATUS_CODES | {403}:
            raise
        print(f"Direct RSS request failed ({error}); using Jina Reader for raw RSS.", file=sys.stderr)

    # Request the original markup and a fresh fetch so new posts appear promptly.
    try:
        feed_bytes = fetch_feed(
            f"https://r.jina.ai/{feed_url}",
            headers={"X-Respond-With": "html", "X-No-Cache": "true"},
        )
        return parse_feed(feed_bytes, feed_url)
    except (urllib.error.URLError, TimeoutError, ET.ParseError, ValueError) as jina_error:
        print(f"Jina Reader RSS fallback failed ({jina_error}); trying Substack archive API.", file=sys.stderr)

    try:
        return fetch_substack_api_posts(feed_url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as api_error:
        print(f"Substack API fallback failed ({api_error}); trying rss2json proxy.", file=sys.stderr)

    return fetch_rss2json_posts(feed_url)


# --- X Articles sync ---


def utf16_slice_map(text: str) -> list[int]:
    """Map UTF-16 code unit offsets (used by Draft.js) to Python character indices."""
    mapping = [0]
    for char_index, ch in enumerate(text, start=1):
        units = 2 if ord(ch) > 0xFFFF else 1
        for _ in range(units):
            mapping.append(char_index)
    return mapping


def resolve_draft_range(offset: int, length: int, text_len: int, u16_map: list[int]) -> tuple[int, int]:
    if 0 <= offset <= len(u16_map) - 1 and 0 <= offset + length <= len(u16_map) - 1:
        return u16_map[offset], u16_map[offset + length]
    start = max(0, min(offset, text_len))
    end = max(start, min(offset + length, text_len))
    return start, end


def render_draft_inline(
    text: str,
    style_ranges: list[dict[str, object]],
    entity_ranges: list[dict[str, object]],
    entity_map: dict[str, dict[str, object]],
    base_url: str,
    anchor_prefix: str,
) -> str:
    if not text:
        return ""
    u16_map = utf16_slice_map(text)
    n = len(text)
    boundaries = {0, n}

    styles: list[tuple[int, int, str]] = []
    for item in style_ranges:
        raw_style = str(item.get("style") or "")
        if raw_style not in {"Bold", "Italic", "Code", "Strikethrough"}:
            continue
        start, end = resolve_draft_range(int(item.get("offset") or 0), int(item.get("length") or 0), n, u16_map)
        if start < end:
            styles.append((start, end, raw_style))
            boundaries.update((start, end))

    links: list[tuple[int, int, str]] = []
    for item in entity_ranges:
        entity = entity_map.get(str(item.get("key")))
        if not isinstance(entity, dict) or entity.get("type") != "LINK":
            continue
        data = entity.get("data")
        raw_url = str(data.get("url") or "") if isinstance(data, dict) else ""
        href = clean_url(raw_url, base_url, anchor_prefix) if raw_url else None
        if not href:
            continue
        start, end = resolve_draft_range(int(item.get("offset") or 0), int(item.get("length") or 0), n, u16_map)
        if start < end:
            links.append((start, end, href))
            boundaries.update((start, end))

    points = sorted(boundaries)
    parts: list[str] = []
    for idx in range(len(points) - 1):
        seg_start, seg_end = points[idx], points[idx + 1]
        segment = html.escape(text[seg_start:seg_end], quote=False).replace("\n", "<br>")
        active_styles = {style for s_start, s_end, style in styles if s_start <= seg_start and seg_end <= s_end}
        if "Code" in active_styles:
            segment = f"<code>{segment}</code>"
        if "Italic" in active_styles:
            segment = f"<em>{segment}</em>"
        if "Bold" in active_styles:
            segment = f"<strong>{segment}</strong>"
        active_links = [href for l_start, l_end, href in links if l_start <= seg_start and seg_end <= l_end]
        if active_links:
            href_attr = html.escape(active_links[0], quote=True)
            segment = f'<a href="{href_attr}" target="_blank" rel="noopener">{segment}</a>'
        parts.append(segment)
    return "".join(parts)


def render_x_media_block(
    entity: dict[str, object],
    media_lookup: dict[str, dict[str, object]],
    base_url: str,
    anchor_prefix: str,
) -> str | None:
    data = entity.get("data")
    if not isinstance(data, dict):
        return None
    caption = str(data.get("caption") or "").strip()
    media_items = data.get("mediaItems")
    if not isinstance(media_items, list):
        return None

    figures: list[str] = []
    for item in media_items:
        if not isinstance(item, dict):
            continue
        media_id = str(item.get("mediaId") or "")
        info = media_lookup.get(media_id)
        if not isinstance(info, dict):
            continue
        raw_src = str(info.get("original_img_url") or "")
        src = clean_url(raw_src, base_url, anchor_prefix) if raw_src else None
        if not src or not src.startswith(("http://", "https://")):
            continue
        attrs = [
            f'src="{html.escape(src, quote=True)}"',
            'loading="lazy"',
            'decoding="async"',
        ]
        if caption:
            attrs.append(f'alt="{html.escape(caption, quote=True)}"')
        for dim_key, attr_name in (("original_img_width", "width"), ("original_img_height", "height")):
            dim = info.get(dim_key)
            if isinstance(dim, int) and dim > 0:
                attrs.append(f'{attr_name}="{dim}"')
        caption_html = f"<figcaption>{html.escape(caption, quote=False)}</figcaption>" if caption else ""
        figures.append(f"<figure><img {' '.join(attrs)}>{caption_html}</figure>")
    return "\n".join(figures) if figures else None


def render_x_article_html(article: dict[str, object], slug: str, post_url: str) -> str:
    content = article.get("content")
    if not isinstance(content, dict):
        raise ValueError("X Article is missing content")
    blocks = content.get("blocks")
    if not isinstance(blocks, list):
        raise ValueError("X Article is missing content blocks")

    raw_entities = content.get("entityMap")
    entity_map: dict[str, dict[str, object]] = {}
    if isinstance(raw_entities, list):
        for entry in raw_entities:
            if isinstance(entry, dict) and "key" in entry and isinstance(entry.get("value"), dict):
                entity_map[str(entry["key"])] = entry["value"]
    elif isinstance(raw_entities, dict):
        for key, val in raw_entities.items():
            if isinstance(val, dict):
                entity_map[str(key)] = val

    media_lookup: dict[str, dict[str, object]] = {}
    raw_media = article.get("media_entities")
    if isinstance(raw_media, list):
        for media in raw_media:
            if isinstance(media, dict) and media.get("media_id") and isinstance(media.get("media_info"), dict):
                media_lookup[str(media["media_id"])] = media["media_info"]

    anchor_prefix = f"x-{safe_identifier(slug)}-"
    rendered_blocks: list[str] = []
    open_list: str | None = None

    def close_list() -> None:
        nonlocal open_list
        if open_list:
            rendered_blocks.append(f"</{open_list}>")
            open_list = None

    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "unstyled")
        text = str(block.get("text") or "")
        style_ranges = block.get("inlineStyleRanges") if isinstance(block.get("inlineStyleRanges"), list) else []
        entity_ranges = block.get("entityRanges") if isinstance(block.get("entityRanges"), list) else []

        if block_type == "atomic":
            close_list()
            for er in entity_ranges:
                if not isinstance(er, dict):
                    continue
                entity = entity_map.get(str(er.get("key")))
                if not isinstance(entity, dict):
                    continue
                if entity.get("type") == "MEDIA":
                    figure_html = render_x_media_block(entity, media_lookup, post_url, anchor_prefix)
                    if figure_html:
                        rendered_blocks.append(figure_html)
                elif entity.get("type") in {"DIVIDER", "HORIZONTAL_RULE"}:
                    rendered_blocks.append("<hr>")
            continue

        if not text.strip():
            close_list()
            continue

        list_tag = (
            "ul"
            if block_type == "unordered-list-item"
            else "ol"
            if block_type == "ordered-list-item"
            else None
        )
        if list_tag != open_list:
            close_list()
            if list_tag:
                rendered_blocks.append(f"<{list_tag}>")
                open_list = list_tag

        # Standalone short bold lines in X Articles act as section headings when header blocks aren't used.
        is_full_bold_heading = (
            block_type == "unstyled"
            and len(text.strip()) <= 120
            and not entity_ranges
            and len(style_ranges) == 1
            and isinstance(style_ranges[0], dict)
            and style_ranges[0].get("style") == "Bold"
            and int(style_ranges[0].get("offset") or 0) == 0
            and int(style_ranges[0].get("length") or 0) >= len(text.rstrip())
        )
        if is_full_bold_heading:
            rendered_blocks.append(f"<h2>{html.escape(text.strip(), quote=False)}</h2>")
            continue

        inline_html = render_draft_inline(text, style_ranges, entity_ranges, entity_map, post_url, anchor_prefix)

        if list_tag:
            rendered_blocks.append(f"<li>{inline_html}</li>")
        elif block_type in {"header-one", "header-two"}:
            rendered_blocks.append(f"<h2>{inline_html}</h2>")
        elif block_type in {"header-three", "header-four"}:
            rendered_blocks.append(f"<h3>{inline_html}</h3>")
        elif block_type == "blockquote":
            rendered_blocks.append(f"<blockquote><p>{inline_html}</p></blockquote>")
        elif block_type == "code-block":
            rendered_blocks.append(f"<pre><code>{html.escape(text, quote=False)}</code></pre>")
        else:
            rendered_blocks.append(f"<p>{inline_html}</p>")

    close_list()
    raw_markup = "\n".join(rendered_blocks)
    return sanitize_content(raw_markup, slug, post_url, anchor_namespace="x")


def parse_fxtwitter_article(payload: dict[str, object], expected_handle: str = DEFAULT_X_HANDLE) -> dict[str, str] | None:
    tweet = payload.get("tweet")
    if not isinstance(tweet, dict):
        raise ValueError("Unexpected fxtwitter payload")
    author = tweet.get("author")
    screen_name = str(author.get("screen_name") or "") if isinstance(author, dict) else ""
    clean_expected = expected_handle.lstrip("@")
    if screen_name.lower() != clean_expected.lower():
        raise ValueError(f"Tweet author @{screen_name} does not match @{clean_expected}")

    article = tweet.get("article")
    if not isinstance(article, dict):
        return None

    status_id = str(tweet.get("id") or "").strip()
    if not status_id.isdigit():
        raise ValueError("Missing numeric X status id")
    title = str(article.get("title") or "").strip() or "Untitled"
    slug = slugify_title(title, fallback=f"x-article-{status_id}")
    post_url = f"https://x.com/{screen_name}/status/{status_id}"
    created_raw = str(article.get("created_at") or "").strip()
    if created_raw:
        published = parse_iso_utc(created_raw)
    elif tweet.get("created_timestamp") is not None:
        published = datetime.fromtimestamp(int(tweet["created_timestamp"]), tz=timezone.utc)
    else:
        published = parsedate_to_datetime(str(tweet.get("created_at") or "")).astimezone(timezone.utc)

    content_html = render_x_article_html(article, slug, post_url)
    return {
        "slug": slug,
        "status_id": status_id,
        "article_id": str(article.get("id") or ""),
        "title": title,
        "subtitle": "",
        "url": post_url,
        "published": published.isoformat(timespec="seconds"),
        "category": "X Article",
        "source": "x",
        "source_label": "X",
        "content_html": content_html,
    }


def extract_x_status_ids_from_html(markup: str, handle: str = DEFAULT_X_HANDLE) -> list[str]:
    clean_handle = re.escape(handle.lstrip("@"))
    found = set(
        re.findall(
            rf"(?:https?://(?:x|twitter)\.com)?/{clean_handle}/status/([0-9]{{15,22}})",
            markup,
            flags=re.IGNORECASE,
        )
    )

    # X also embeds SSR Relay JSON streams containing tweet objects with article metadata.
    for match in re.finditer(r'"(\{\\"data\\":.*?)"\}\}\)\)', markup):
        try:
            decoded = json.loads('"' + match.group(1) + '"')
            payload = json.loads(decoded)
        except json.JSONDecodeError:
            continue
        _collect_ssr_user_status_ids(payload, handle.lstrip("@").lower(), found)

    return sorted(found, key=int, reverse=True)


def _collect_ssr_user_status_ids(node: object, handle_lower: str, out: set[str]) -> None:
    if isinstance(node, dict):
        if node.get("__typename") == "Tweet" and isinstance(node.get("rest_id"), str):
            user_core = (
                node.get("core", {})
                .get("user_results", {})
                .get("result", {})
                .get("core", {})
            )
            if isinstance(user_core, dict) and str(user_core.get("screen_name") or "").lower() == handle_lower:
                rest_id = node["rest_id"]
                if rest_id.isdigit():
                    out.add(rest_id)
        for value in node.values():
            _collect_ssr_user_status_ids(value, handle_lower, out)
    elif isinstance(node, list):
        for item in node:
            _collect_ssr_user_status_ids(item, handle_lower, out)


def discover_x_status_ids(handle: str = DEFAULT_X_HANDLE) -> list[str]:
    clean_handle = handle.lstrip("@")
    profile_url = f"https://x.com/{clean_handle}"
    discovered: set[str] = set()
    errors: list[str] = []

    try:
        raw_profile = fetch_feed(
            profile_url,
            headers={"Accept": "text/html,application/xhtml+xml"},
        ).decode("utf-8", "replace")
        discovered.update(extract_x_status_ids_from_html(raw_profile, clean_handle))
    except (urllib.error.URLError, TimeoutError) as error:
        errors.append(f"direct X profile ({error})")

    if not discovered:
        try:
            jina_profile = fetch_feed(
                f"https://r.jina.ai/{profile_url}",
                headers={"X-Respond-With": "html", "X-No-Cache": "true"},
            ).decode("utf-8", "replace")
            discovered.update(extract_x_status_ids_from_html(jina_profile, clean_handle))
        except (urllib.error.URLError, TimeoutError) as error:
            errors.append(f"Jina X profile ({error})")

    if not discovered and errors:
        raise ValueError("; ".join(errors))
    return sorted(discovered, key=int, reverse=True)


def fetch_x_article_by_status(handle: str, status_id: str) -> dict[str, str] | None:
    clean_handle = handle.lstrip("@")
    api_url = f"https://api.fxtwitter.com/{quote(clean_handle)}/status/{quote(status_id)}"
    payload = json.loads(fetch_feed(api_url, headers={"Accept": "application/json"}))
    if not isinstance(payload, dict) or payload.get("code") != 200:
        raise ValueError(f"fxtwitter returned an unexpected status for {status_id}")
    return parse_fxtwitter_article(payload, clean_handle)


def fetch_x_articles(
    handle: str = DEFAULT_X_HANDLE,
    *,
    known_status_ids: set[str] | None = None,
    extra_status_ids: list[str] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    known = set(known_status_ids or set())
    discovered = discover_x_status_ids(handle)
    explicit = [sid for sid in (extra_status_ids or []) if sid.isdigit()]

    to_inspect = [sid for sid in dict.fromkeys(explicit + discovered) if sid not in known or sid in explicit]
    articles: list[dict[str, str]] = []
    inspected: list[str] = []
    for status_id in to_inspect:
        article = fetch_x_article_by_status(handle, status_id)
        inspected.append(status_id)
        if article is not None:
            articles.append(article)
    return articles, sorted(known | set(inspected), key=int, reverse=True)


def extract_status_id_arg(value: str) -> str:
    cleaned = value.strip()
    if cleaned.isdigit():
        return cleaned
    match = re.search(r"/status/([0-9]{15,22})", cleaned)
    if match:
        return match.group(1)
    raise ValueError(f"Expected a numeric X status ID or status URL, got: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed-url", default=DEFAULT_FEED_URL)
    parser.add_argument("--feed-file", type=Path)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--x-handle", default="")
    parser.add_argument("--x-cache", type=Path, default=DEFAULT_X_CACHE)
    parser.add_argument("--x-articles-file", type=Path)
    parser.add_argument(
        "--x-status",
        action="append",
        default=[],
        help="Explicit X status ID or https://x.com/<user>/status/<id> URL to import.",
    )
    args = parser.parse_args()

    substack_posts: list[dict[str, str]] | None = None
    substack_failed = False
    try:
        substack_posts = (
            parse_feed(args.feed_file.read_bytes(), args.feed_url)
            if args.feed_file
            else fetch_posts(args.feed_url)
        )
        print(f"Read {len(substack_posts)} post{'s' if len(substack_posts) != 1 else ''} from Substack.")
    except (urllib.error.URLError, TimeoutError, ET.ParseError, json.JSONDecodeError, ValueError) as error:
        print(f"Substack sync failed: {error}", file=sys.stderr)
        substack_failed = True

    x_enabled = bool(args.x_handle or args.x_articles_file or args.x_status)
    x_handle = (args.x_handle or DEFAULT_X_HANDLE).lstrip("@")
    x_posts: list[dict[str, str]] | None = None
    x_status_ids: list[str] | None = None
    x_failed = False

    if x_enabled:
        try:
            if args.x_articles_file:
                raw_payload = json.loads(args.x_articles_file.read_text(encoding="utf-8"))
                items = raw_payload if isinstance(raw_payload, list) else [raw_payload]
                parsed_articles = [
                    article
                    for item in items
                    if isinstance(item, dict)
                    and (article := parse_fxtwitter_article(item, x_handle)) is not None
                ]
                x_posts = parsed_articles
                x_status_ids = [post["status_id"] for post in parsed_articles if post.get("status_id")]
            else:
                _, known_ids = load_x_cache(args.x_cache, x_handle)
                explicit_ids = [extract_status_id_arg(val) for val in args.x_status]
                x_posts, x_status_ids = fetch_x_articles(
                    x_handle,
                    known_status_ids=set(known_ids),
                    extra_status_ids=explicit_ids,
                )
            print(f"Read {len(x_posts)} new X article{'s' if len(x_posts) != 1 else ''} from @{x_handle}.")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as error:
            print(f"X articles sync failed: {error}", file=sys.stderr)
            x_failed = True

    if substack_failed and (not x_enabled or x_failed):
        return 1
    if not x_enabled and substack_failed:
        return 1

    count, changed = sync_all_posts(
        substack_posts,
        args.index,
        args.cache,
        feed_url=args.feed_url,
        x_posts=x_posts,
        x_cache_path=args.x_cache if (x_enabled or args.x_cache.exists()) else None,
        x_handle=x_handle,
        x_status_ids=x_status_ids,
    )
    state = "updated" if changed else "already current"
    print(f"Blog archive {state}: {count} automated post{'s' if count != 1 else ''}.")
    return 1 if (substack_failed or x_failed) else 0


if __name__ == "__main__":
    sys.exit(main())
