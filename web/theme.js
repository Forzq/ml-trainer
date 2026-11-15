/* Apply the saved theme before styles load, so the desktop window never flashes white. */
(() => {
  let saved;
  try { saved = localStorage.getItem("ml-theme"); } catch {}

  function set(theme) {
    const value = theme === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = value;
    document.documentElement.style.colorScheme = value;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", value === "dark" ? "#101017" : "#f7f8fa");
    try { localStorage.setItem("ml-theme", value); } catch {}
    window.dispatchEvent(new CustomEvent("ml-theme-change", { detail: value }));
    return value;
  }

  window.MLTheme = { set, get current() { return document.documentElement.dataset.theme; } };
  set(saved);
})();
