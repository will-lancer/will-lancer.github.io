# Daily journal

This directory contains the journal's source. The page lives at `/journal/` on Will's existing website. Read `README.md` here before adding an entry.

Use the material Will supplies for the requested day. Preserve his voice and distinguish work completed from plans. Ask for the date when the supplied material leaves it unclear. Record hours only when Will provides them. Use the exact course names he supplies. Add photos and PDFs where they belong in the account of the day.

Keep the journal off the main navigation and retain its `noindex` metadata. The page and its attachments are publicly accessible. Files committed to the repository can also be read publicly, including source files and drafts.

Edit `site.json` for the introduction and goals. Each entry has its own JSON file in `entries/`; generate `../journal/index.html` with `python3 scripts/build_journal.py` from the repository root. Follow the checks in `README.md` before publishing. Scope commits to the requested journal update and preserve unrelated edits.

Keep local work brief. Heavy local CPU work requires Will's explicit approval for the specific workload. Use remote compute for sustained work and get budget approval before paid compute. Resize only supplied images that need it; avoid bulk OCR or parallel compute workers.
