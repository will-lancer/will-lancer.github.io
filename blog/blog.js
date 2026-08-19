(() => {
  const posts = Array.from(document.querySelectorAll("[data-post]"));
  const search = document.querySelector("#post-search");
  const status = document.querySelector("[data-search-status]");
  const emptyState = document.querySelector("[data-empty-state]");

  document.querySelectorAll("[data-katex]").forEach((element) => {
    if (!window.katex) return;

    window.katex.render(element.textContent, element, {
      displayMode: element.dataset.display === "true",
      throwOnError: false,
      strict: false,
    });
  });

  document.querySelectorAll("[data-read-more]").forEach((button) => {
    button.addEventListener("click", () => {
      const preview = document.getElementById(button.getAttribute("aria-controls"));
      const expanded = button.getAttribute("aria-expanded") === "true";

      button.setAttribute("aria-expanded", String(!expanded));
      preview.classList.toggle("is-expanded", !expanded);
      button.querySelector("[data-read-more-label]").textContent = expanded
        ? "Continue reading"
        : "Show less";
      button.querySelector("[data-read-more-arrow]").textContent = expanded ? "↓" : "↑";

      if (expanded) {
        button.closest("[data-post]").scrollIntoView({ block: "start" });
      }
    });
  });

  search.addEventListener("input", () => {
    const query = search.value.trim().toLowerCase();
    let visibleCount = 0;

    posts.forEach((post) => {
      const matches = post.textContent.toLowerCase().includes(query);
      post.hidden = !matches;
      if (matches) visibleCount += 1;
    });

    emptyState.hidden = visibleCount !== 0;
    status.textContent = query
      ? `${visibleCount} ${visibleCount === 1 ? "post" : "posts"} found for “${search.value.trim()}”.`
      : "";
  });
})();
