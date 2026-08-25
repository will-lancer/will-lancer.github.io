(() => {
  document.querySelectorAll("[data-katex]").forEach((element) => {
    if (!window.katex) return;

    window.katex.render(element.textContent, element, {
      displayMode: element.dataset.display === "true",
      throwOnError: false,
      strict: false,
    });
  });

  document.querySelectorAll("[data-paper-read-more]").forEach((button) => {
    const preview = document.getElementById(button.getAttribute("aria-controls"));
    const body = button.closest(".paper-record-body, .resource-item-body");

    if (preview && preview.scrollHeight <= preview.clientHeight + 8) {
      button.hidden = true;
      const fade = body?.querySelector(".paper-fade");
      if (fade) fade.hidden = true;
      preview.style.maxHeight = "none";
      preview.style.overflow = "visible";
      return;
    }

    button.addEventListener("click", () => {
      const expanded = button.getAttribute("aria-expanded") === "true";

      button.setAttribute("aria-expanded", String(!expanded));
      preview.classList.toggle("is-expanded", !expanded);
      button.querySelector("[data-read-more-label]").textContent = expanded
        ? "Show more"
        : "Show less";
      button.querySelector("[data-read-more-arrow]").textContent = expanded ? "↓" : "↑";

      if (expanded) {
        button.closest(".paper-record, .resource-list li")?.scrollIntoView({
          block: "start",
        });
      }
    });
  });
})();
