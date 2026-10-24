# Daily journal

Public address: `https://will-lancer.github.io/journal/`.

The page has an introduction, a date index, and entries ordered newest first. Search and topic filters work in the browser. Entry titles link to a permanent fragment. Photos open at full size. PDF attachments have open/download links and an expandable preview.

The journal stays off the site's navigation. Its `noindex` metadata asks search engines to omit it. Anyone with the URL can read it, and the GitHub repository is public. Jekyll omits this underscore-prefixed source directory from the deployed site; GitHub still exposes committed source and drafts.

## Add an entry from a chat

Will can send notes, photos, or PDFs and ask for an entry for a given date. An assistant can complete the update from those materials. The browser page serves as the reading view; publishing happens through this repository.

1. Read the current entry files and `site.json`. Check the Git branch and local changes.
2. Use the supplied date, with Europe/London as the journal's timezone. Create a draft:

   ```sh
   python3 scripts/build_journal.py new 2026-10-26 "Entry title"
   ```

3. Edit the new file in `_journal/entries/`. Fill `blocks` with the day's account. Set `tags` to the supplied course names or topics, such as `AI safety`. Leave `ai_safety_hours` as `null` until Will provides a duration. `kind: "entry"` counts the date as a logged day; `kind: "note"` is for introductory notes.
4. Copy supplied attachments to `journal/media/YYYY-MM-DD/` using short descriptive filenames. Photos should be browser-readable JPG, PNG, or WebP. Convert HEIC when needed, preserve readability, and remove location metadata from published image copies. Keep original supplied files intact. The site supports PDF files directly.
5. Once the entry is ready, set `draft` to `false`. Build and check it:

   ```sh
   python3 scripts/build_journal.py
   python3 scripts/build_journal.py --check
   python3 -m unittest discover -s tests -p 'test_journal.py'
   node --check journal/journal.js
   git diff --check
   ```

6. Review the rendered page at desktop and mobile widths when a browser is available. Check each added attachment. For a local preview, run `python3 -m http.server 8765 --bind 127.0.0.1` from the repository root and open `http://127.0.0.1:8765/journal/`. Stop the server afterwards.
7. When the user requests publication, commit the source, generated page, and supplied attachments together, then push to the Pages branch (`main`, verified when this journal was created). Recheck current Pages settings if they have changed. Verify the deployed page includes the new entry and attachment URLs respond successfully. A pushed commit alone does not verify publication.

Keep unpublished material out of commits until it is ready to be public. `draft: true` excludes an entry from the generated page, while the public repository still exposes any committed draft.

## Content format

Each entry's filename is `YYYY-MM-DD-lowercase-title.json`; the filename becomes its permanent anchor. Keep it stable after publication. JSON string values contain plain text, which the build escapes as HTML.

```json
{
  "date": "2026-10-26",
  "title": "Entry title",
  "kind": "entry",
  "draft": true,
  "tags": [],
  "ai_safety_hours": null,
  "blocks": [
    {"type": "paragraph", "text": "The day's account, using Will's supplied material."},
    {"type": "heading", "text": "A course or topic"},
    {"type": "list", "items": ["A completed piece of work", "A question to return to"]},
    {"type": "image", "src": "media/2026-10-26/notes.jpg", "alt": "Describe the work shown in the photo", "caption": "Optional caption"},
    {"type": "pdf", "src": "media/2026-10-26/work.pdf", "title": "Document title", "caption": "Optional description"},
    {"type": "link", "url": "https://example.org/", "text": "Link label"},
    {"type": "code", "text": "print('example')"}
  ]
}
```

Remove unused blocks. All attachment paths are relative to `journal/` and must point to existing files under `journal/media/`. The builder rejects missing files and unsafe attachment paths before changing the generated page. Supported image extensions: `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`, `.avif`.

`_journal/site.json` controls the title, introductory paragraphs, and goal labels. The goal labels describe the intended schedule. The sidebar counts dates with a published daily entry, and each entry can display the hours Will reports.

The site needs no package installation or server backend. Build with Python 3.9 or newer. Commit the generated HTML so GitHub Pages can serve it directly.
