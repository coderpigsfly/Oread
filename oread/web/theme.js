// Light, dark, or follow the device; remembered in this browser only.
(function () {
  var choice = null;
  try { choice = localStorage.getItem("oread-theme"); } catch (e) { /* private window */ }
  if (choice === "light" || choice === "dark") {
    document.documentElement.setAttribute("data-theme", choice);
  }
})();
