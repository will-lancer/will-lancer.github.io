(() => {
  const root = document.documentElement;
  const toggleButtons = document.querySelectorAll("[data-theme-toggle]");
  const storageKey = "theme";

  const readSavedTheme = () => {
    try {
      const value = localStorage.getItem(storageKey);
      return value === "light" || value === "dark" ? value : null;
    } catch {
      return null;
    }
  };

  const applyTheme = (theme, persist) => {
    root.setAttribute("data-theme", theme);

    // Keep the browser chrome tint in step with the active theme (PDF toolbar).
    const themeColor = theme === "dark" ? "#232427" : "#323639";
    document.querySelectorAll('meta[name="theme-color"]').forEach((meta) => {
      meta.setAttribute("content", themeColor);
    });

    toggleButtons.forEach((button) => {
      const isDark = theme === "dark";
      // Keep the toggle icon-only even if stale text nodes get restored by the browser.
      button.replaceChildren();
      button.setAttribute("aria-pressed", String(isDark));
      const label = isDark ? "Switch to light mode" : "Switch to dark mode";
      button.setAttribute("aria-label", label);
      button.setAttribute("title", label);
    });

    if (!persist) return;

    try {
      localStorage.setItem(storageKey, theme);
    } catch {
      // Ignore storage failures (private mode, storage policies, etc).
    }
  };

  let activeTheme = root.getAttribute("data-theme") || readSavedTheme() || "light";
  applyTheme(activeTheme, false);

  toggleButtons.forEach((button) => {
    button.addEventListener("click", () => {
      activeTheme = activeTheme === "dark" ? "light" : "dark";
      applyTheme(activeTheme, true);
    });
  });
})();
