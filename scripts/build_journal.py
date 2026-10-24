#!/usr/bin/env python3
"""Build the static journal using Python's standard library.

Usage: python3 scripts/build_journal.py [--check]
       python3 scripts/build_journal.py new YYYY-MM-DD "Entry title"
"""

import argparse
from datetime import date
from html import escape
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected nonempty text")
    return escape(value, quote=True)


def media_url(root, source, extensions):
    """Keep attachments inside journal/media and verify each file exists."""
    if not isinstance(source, str):
        raise ValueError("An attachment needs a local src")
    path = Path(source)
    base = (root / "journal/media").resolve()
    target = (root / "journal" / path).resolve()
    if (not source.startswith("media/") or not target.is_relative_to(base)
            or path.suffix.lower() not in extensions or not target.is_file()):
        raise ValueError(f"Missing or unsupported journal attachment: {source}")
    return quote(source, safe="/")


def render_block(block, root):
    kind = block["type"]
    if kind == "paragraph":
        return f'<p>{text(block["text"])}</p>'
    if kind == "heading":
        return f'<h3>{text(block["text"])}</h3>'
    if kind == "list":
        if not isinstance(block["items"], list) or not block["items"]:
            raise ValueError("A list needs items")
        return '<ul>' + ''.join(f'<li>{text(item)}</li>' for item in block["items"]) + '</ul>'
    if kind == "code":
        return f'<pre><code>{text(block["text"])}</code></pre>'
    if kind == "link":
        url = block["url"]
        parsed = urlsplit(url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("Links must use an absolute http or https URL")
        return f'<p><a href="{text(url)}" rel="noreferrer">{text(block["text"])}</a></p>'
    if kind == "image":
        source = media_url(root, block["src"], {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"})
        caption = f'<figcaption>{text(block["caption"])}</figcaption>' if block.get("caption") else ''
        return (f'<figure class="entry-photo"><a href="{source}" target="_blank" rel="noopener" '
                f'aria-label="Open full-size image: {text(block["alt"])}">'
                f'<img src="{source}" alt="{text(block["alt"])}" loading="lazy" decoding="async">'
                f'</a>{caption}</figure>')
    if kind == "pdf":
        source = media_url(root, block["src"], {".pdf"})
        title = text(block["title"])
        caption = f'<p class="attachment-caption">{text(block["caption"])}</p>' if block.get("caption") else ''
        return (f'<section class="pdf-attachment" aria-label="PDF: {title}">'
                '<div class="attachment-header"><span class="file-badge" aria-hidden="true">PDF</span>'
                f'<div><p class="attachment-title">{title}</p><div class="attachment-links">'
                f'<a href="{source}" target="_blank" rel="noopener">Open PDF ↗</a>'
                f'<a href="{source}" download>Download</a></div></div></div>{caption}'
                '<details class="pdf-preview"><summary>Read PDF here</summary>'
                f'<iframe data-src="{source}#view=FitH" title="{title}" loading="lazy"></iframe>'
                '<noscript><p>Use the Open PDF link above to read this document.</p></noscript>'
                '</details></section>')
    raise ValueError(f"Unknown block type: {kind}")


def load_entries(root):
    entries = []
    for source in sorted((root / "_journal/entries").glob("*.json")):
        try:
            entry = json.loads(source.read_text())
            if type(entry.get("draft")) is not bool:
                raise ValueError("Set draft to true or false")
            if entry["draft"]:
                continue
            day = date.fromisoformat(entry["date"])
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*", source.stem):
                raise ValueError("Filename must be YYYY-MM-DD-lowercase-slug.json")
            if not source.stem.startswith(f'{day.isoformat()}-'):
                raise ValueError("Filename date must match the entry date")
            text(entry["title"])
            if entry.get("kind") not in {"note", "entry"}:
                raise ValueError("kind must be note or entry")
            tags = entry.get("tags", [])
            if not isinstance(tags, list) or any(not isinstance(tag, str) or not tag.strip() for tag in tags):
                raise ValueError("tags must be a list of nonempty strings")
            hours = entry.get("ai_safety_hours")
            if hours is not None and (type(hours) not in {int, float} or not math.isfinite(hours) or not 0 <= hours <= 24):
                raise ValueError("ai_safety_hours must be null or a number from 0 to 24")
            if not isinstance(entry["blocks"], list) or not entry["blocks"]:
                raise ValueError("Each published entry needs content blocks")
            entry.update(id=source.stem, day=day, tags=list(dict.fromkeys(tags)),
                         body='\n'.join(render_block(block, root) for block in entry["blocks"]))
            entries.append(entry)
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError(f"{source.name}: {error}") from error
    return sorted(entries, key=lambda entry: (entry["date"], entry["id"]), reverse=True)


def render_entry(entry):
    tags = ''.join(f'<span>{text(tag)}</span>' for tag in entry["tags"])
    hours = entry.get("ai_safety_hours")
    if hours is not None:
        tags += f'<span class="hours">AI safety · {hours:g}h logged</span>'
    labels = f'<div class="entry-labels">{tags}</div>' if tags else ''
    kind = '<span class="kind">Opening note</span>' if entry["kind"] == "note" else ''
    return (f'<article class="entry" id="{entry["id"]}" data-tags="{escape(json.dumps(entry["tags"]), quote=True)}">'
            f'<header><div class="entry-meta"><time datetime="{entry["date"]}">'
            f'{entry["day"].strftime("%A, %-d %B %Y")}</time>{kind}</div>'
            f'<h2><a href="#{entry["id"]}" aria-label="Link to entry: {text(entry["title"])}">{text(entry["title"])}</a></h2>'
            f'{labels}</header><div class="entry-body">{entry["body"]}</div></article>')


def render(root=ROOT):
    config = json.loads((root / "_journal/site.json").read_text())
    entries = load_entries(root)
    months = {}
    for entry in entries:
        months.setdefault(entry["day"].strftime("%B %Y"), []).append(entry)
    index = []
    for month, items in months.items():
        links = ''.join(f'<li><a href="#{entry["id"]}" data-entry-link>'
                        f'<time datetime="{entry["date"]}">{entry["day"].day:02}</time>'
                        f'<span>{text(entry["title"])}</span></a></li>' for entry in items)
        index.append(f'<div class="index-month"><h3>{month}</h3><ol>{links}</ol></div>')
    tags = sorted({tag for entry in entries for tag in entry["tags"]})
    days = len({entry["date"] for entry in entries if entry["kind"] == "entry"})
    substitutions = {
        "TITLE": text(config["title"]),
        "EYEBROW": text(config["eyebrow"]),
        "INTRO": ''.join(f'<p>{text(paragraph)}</p>' for paragraph in config["intro"]),
        "GOALS": ''.join(f'<div><dt>{text(goal["value"])}</dt><dd>{text(goal["label"])}</dd></div>' for goal in config["goals"]),
        "FILTERS": ''.join(f'<option value="{text(tag)}">{text(tag)}</option>' for tag in tags),
        "INDEX": '\n'.join(index),
        "DAY_COUNT": f'{days} {"day" if days == 1 else "days"} logged',
        "START_DATE": min(entry["day"] for entry in entries).strftime("%B %Y") if entries else 'the first entry',
        "ENTRIES": '\n'.join(render_entry(entry) for entry in entries) or '<p class="empty-search">The first entry is on its way.</p>',
    }
    template = (root / "_journal/template.html").read_text()
    return re.sub(r"@@([A-Z_]+)@@", lambda match: substitutions[match[1]], template)


def new_entry(day_string, title):
    day = date.fromisoformat(day_string)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        raise ValueError("Use a title with at least one ASCII letter or digit")
    entry = {
        "date": day.isoformat(), "title": title, "kind": "entry", "draft": True,
        "tags": [], "ai_safety_hours": None,
        "blocks": [{"type": "paragraph", "text": "Describe the day's work here."}],
    }
    destination = ROOT / "_journal/entries" / f'{day.isoformat()}-{slug}.json'
    with destination.open("x") as output:
        output.write(json.dumps(entry, indent=2, ensure_ascii=False) + "\n")
    print(f"Created draft: {destination.relative_to(ROOT)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the generated page is out of date")
    subparsers = parser.add_subparsers(dest="command")
    new = subparsers.add_parser("new", help="Create a draft entry")
    new.add_argument("date")
    new.add_argument("title")
    args = parser.parse_args()
    try:
        if args.command == "new":
            new_entry(args.date, args.title)
            return
        page = render()
        destination = ROOT / "journal/index.html"
        if args.check:
            if not destination.exists() or destination.read_text() != page:
                raise ValueError("Journal is out of date. Run python3 scripts/build_journal.py")
            print("Journal is up to date; all published attachments exist.")
        else:
            destination.write_text(page)
            print(f"Built {destination.relative_to(ROOT)}")
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"Journal build failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
