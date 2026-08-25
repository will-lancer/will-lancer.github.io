#!/usr/bin/env python3
"""Copy new Substack RSS entries into the static blog archive."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
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
DEFAULT_INDEX = ROOT / "blog" / "index.html"
DEFAULT_CACHE = ROOT / "blog" / "substack-posts.json"
START_MARKER = "<!-- BEGIN AUTO-SYNCED SUBSTACK POSTS -->"
END_MARKER = "<!-- END AUTO-SYNCED SUBSTACK POSTS -->"
CONTENT_NAMESPACE = "http://purl.org/rss/1.0/modules/content/"
PACIFIC = ZoneInfo("America/Los_Angeles")
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0 Safari/537.36"
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
HTML_VOID_TAGS = VOID_TAGS | {"area", "base", "col", "embed", "input", "link", "meta", "param", "source", "track", "wbr"}
DROP_WITH_CONTENT = {"button", "form", "iframe", "noscript", "object", "script", "style"}
DROP_VOID = {"embed", "input", "source"}
BLOCK_TAGS = {"blockquote", "div", "figcaption", "figure", "h2", "h3", "h4", "li", "ol", "p", "pre", "ul"}
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

    query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if not key.startswith("utm_")]
    return urlunparse(parsed._replace(query=urlencode(query)))


def safe_identifier(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")
    return cleaned or "item"


class SafeSubstackHTML(HTMLParser):
    """Keep article markup while dropping forms, scripts, widgets, and unsafe attributes."""

    def __init__(self, slug: str, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.anchor_prefix = f"substack-{safe_identifier(slug)}-"
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
            self.skip_depth = 1
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


def sanitize_content(markup: str, slug: str, base_url: str) -> str:
    parser = SafeSubstackHTML(slug, base_url)
    parser.feed(markup)
    parser.close()
    return parser.result()


def post_slug(link: str, guid: str, title: str) -> str:
    for candidate in (link, guid):
        path_name = Path(urlparse(candidate).path).name
        if path_name:
            return safe_identifier(path_name.lower())
    return safe_identifier(title.lower())


def parse_feed(feed_bytes: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(feed_bytes)
    posts: list[dict[str, str]] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "Untitled").strip()
        link = (item.findtext("link") or "").strip()
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
                "content_html": content,
            }
        )
    return posts


def api_post_to_entry(post: dict[str, object]) -> dict[str, str]:
    slug = safe_identifier(str(post["slug"]).lower())
    link = str(post.get("canonical_url") or f"https://wlancer.substack.com/p/{slug}")
    raw_content = str(post.get("body_html") or "")
    raw_date = str(post["post_date"]).replace("Z", "+00:00")
    published = datetime.fromisoformat(raw_date).astimezone(timezone.utc)
    raw_tags = post.get("postTags")
    tags = raw_tags if isinstance(raw_tags, list) else []
    first_tag = tags[0] if tags else None
    category = str(first_tag.get("name", "Substack")) if isinstance(first_tag, dict) else "Substack"
    return {
        "slug": slug,
        "title": str(post.get("title") or "Untitled"),
        "subtitle": plain_text(str(post.get("subtitle") or post.get("description") or "")),
        "url": link,
        "published": published.isoformat(timespec="seconds"),
        "category": category,
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


def render_post(post: dict[str, str]) -> str:
    slug = safe_identifier(post["slug"])
    title = html.escape(post["title"])
    subtitle = html.escape(post.get("subtitle", ""))
    category = html.escape(post.get("category", "Substack"))
    url = html.escape(post["url"], quote=True)
    machine_date, display_date = format_published(post["published"])
    minutes = reading_time(post["content_html"])
    subtitle_html = f'\n              <p class="post-subtitle">{subtitle}</p>' if subtitle else ""
    content = indent_content(post["content_html"], 14)
    return f'''          <article class="post" id="{slug}" data-substack-post data-post>
            <header class="post-header">
              <p class="post-category">{category}</p>
              <h2>{title}</h2>
              <p class="post-meta">
                <time datetime="{machine_date}">{display_date}</time>
                <span aria-hidden="true">&middot;</span>
                <span>{minutes} min read</span>
                <span aria-hidden="true">&middot;</span>
                <a href="{url}" target="_blank" rel="noopener">Substack</a>
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


def load_cache(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("feed_url") != DEFAULT_FEED_URL or not isinstance(data.get("posts"), list):
        raise ValueError(f"Unexpected cache format in {path}")
    return data["posts"]


def manual_post_ids(index_html: str, start: int, end: int) -> set[str]:
    outside_managed_block = index_html[:start] + index_html[end + len(END_MARKER) :]
    return set(re.findall(r'<article\b[^>]*\bid="([^"]+)"[^>]*\bdata-post\b', outside_managed_block))


def update_index(index_html: str, posts: list[dict[str, str]]) -> str:
    start = index_html.index(START_MARKER) + len(START_MARKER)
    end = index_html.index(END_MARKER, start)
    rendered = "\n\n" + "\n\n".join(render_post(post) for post in posts) + "\n\n          " if posts else "\n          "
    return index_html[:start] + rendered + index_html[end:]


def sync_posts(feed_posts: list[dict[str, str]], index_path: Path, cache_path: Path) -> tuple[int, bool]:
    index_html = index_path.read_text(encoding="utf-8")
    start = index_html.index(START_MARKER) + len(START_MARKER)
    end = index_html.index(END_MARKER, start)
    manual_ids = manual_post_ids(index_html, start, end)

    cached = {post["slug"]: post for post in load_cache(cache_path)}
    for post in feed_posts:
        if post["slug"] not in manual_ids:
            cached[post["slug"]] = post
    for slug in manual_ids:
        cached.pop(slug, None)

    posts = sorted(cached.values(), key=lambda post: post["published"], reverse=True)
    new_index = update_index(index_html, posts)
    cache_text = json.dumps({"feed_url": DEFAULT_FEED_URL, "posts": posts}, ensure_ascii=False, indent=2) + "\n"
    old_cache = cache_path.read_text(encoding="utf-8") if cache_path.exists() else ""
    changed = new_index != index_html or cache_text != old_cache
    if changed:
        index_path.write_text(new_index, encoding="utf-8")
        cache_path.write_text(cache_text, encoding="utf-8")
    return len(posts), changed


def sync(feed_bytes: bytes, index_path: Path, cache_path: Path) -> tuple[int, bool]:
    return sync_posts(parse_feed(feed_bytes), index_path, cache_path)


def fetch_feed(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.7",
            "User-Agent": BROWSER_USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def fetch_json(url: str) -> object:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": BROWSER_USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def fetch_substack_api(feed_url: str) -> list[dict[str, str]]:
    parsed = urlparse(feed_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    archive_url = f"{base_url}/api/v1/archive?sort=new&search=&offset=0&limit=50"
    archive = fetch_json(archive_url)
    if not isinstance(archive, list):
        raise ValueError("Substack archive API returned an unexpected response")

    posts: list[dict[str, str]] = []
    for summary in archive:
        if not isinstance(summary, dict) or not summary.get("slug"):
            continue
        detail_url = f"{base_url}/api/v1/posts/{quote(str(summary['slug']))}"
        detail = fetch_json(detail_url)
        if isinstance(detail, dict) and detail.get("body_html"):
            posts.append(api_post_to_entry(detail))
    return posts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed-url", default=DEFAULT_FEED_URL)
    parser.add_argument("--feed-file", type=Path)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args()

    if args.feed_file:
        posts = parse_feed(args.feed_file.read_bytes())
    else:
        try:
            posts = parse_feed(fetch_feed(args.feed_url))
        except urllib.error.HTTPError as error:
            if error.code != 403:
                raise
            print("RSS request was blocked; using Substack's public archive API.", file=sys.stderr)
            posts = fetch_substack_api(args.feed_url)
    count, changed = sync_posts(posts, args.index, args.cache)
    state = "updated" if changed else "already current"
    print(f"Substack archive {state}: {count} automated post{'s' if count != 1 else ''}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
