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

  const getSystemTheme = () =>
    window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";

  const applyTheme = (theme, persist) => {
    root.setAttribute("data-theme", theme);

    toggleButtons.forEach((button) => {
      const isDark = theme === "dark";
      button.textContent = isDark ? "Light mode" : "Dark mode";
      button.setAttribute("aria-pressed", String(isDark));
      button.setAttribute(
        "aria-label",
        isDark ? "Switch to light mode" : "Switch to dark mode"
      );
    });

    if (!persist) return;

    try {
      localStorage.setItem(storageKey, theme);
    } catch {
      // Ignore storage failures (private mode, storage policies, etc).
    }
  };

  let activeTheme =
    root.getAttribute("data-theme") || readSavedTheme() || getSystemTheme();
  applyTheme(activeTheme, false);

  toggleButtons.forEach((button) => {
    button.addEventListener("click", () => {
      activeTheme = activeTheme === "dark" ? "light" : "dark";
      applyTheme(activeTheme, true);
    });
  });

  const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
  const syncWithSystemTheme = () => {
    if (readSavedTheme()) return;
    activeTheme = getSystemTheme();
    applyTheme(activeTheme, false);
  };

  if (typeof mediaQuery.addEventListener === "function") {
    mediaQuery.addEventListener("change", syncWithSystemTheme);
  } else if (typeof mediaQuery.addListener === "function") {
    mediaQuery.addListener(syncWithSystemTheme);
  }
})();
