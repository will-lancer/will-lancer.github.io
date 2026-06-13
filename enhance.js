(() => {
  const slug = (s) =>
    s
      .toLowerCase()
      .trim()
      .replace(/[^\w\s-]/g, "")
      .replace(/\s+/g, "-")
      .replace(/-+/g, "-");

  const article = document.querySelector(".article");

  // Give every article H2 a stable id, a title record, and a hover anchor link.
  if (article) {
    const used = new Set();
    article.querySelectorAll("h2").forEach((h) => {
      const title = h.textContent.trim();
      let id = h.id || slug(title) || "section";
      while (used.has(id)) id += "-x";
      used.add(id);
      h.id = id;
      h.dataset.title = title;

      const anchor = document.createElement("a");
      anchor.className = "head-anchor";
      anchor.href = "#" + id;
      anchor.setAttribute("aria-label", "Link to this section");
      anchor.textContent = "#";
      h.prepend(anchor);
    });
  }

  // Build a table of contents into [data-toc] when there are enough sections.
  const tocHost = document.querySelector("[data-toc]");
  if (tocHost && article) {
    const heads = [...article.querySelectorAll("h2")];
    if (heads.length >= 3) {
      const ol = document.createElement("ol");
      heads.forEach((h) => {
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = "#" + h.id;
        a.textContent = h.dataset.title;
        li.appendChild(a);
        ol.appendChild(li);
      });
      const label = document.createElement("p");
      label.className = "section-label toc-label";
      label.textContent = "Contents";
      tocHost.classList.add("toc");
      tocHost.append(label, ol);
    } else {
      tocHost.remove();
    }
  }

  // Flag off-site links so the stylesheet can mark them, and open them safely.
  const host = location.hostname;
  document.querySelectorAll(".article a[href], .prose a[href]").forEach((a) => {
    try {
      const url = new URL(a.href, location.href);
      if (url.host && url.host !== host && /^https?:$/.test(url.protocol)) {
        a.setAttribute("data-external", "");
        if (!a.target) a.target = "_blank";
        a.rel = "noopener";
      }
    } catch {
      /* ignore malformed hrefs */
    }
  });
})();
