// Oread's pages. Plain JavaScript, ECMAScript 2020 only (checked by the lint test):
// no framework, no build step, nothing loaded from the internet.

const app = document.getElementById("app");
let session = null; // {user, can, grantable, version}

// ---------- small helpers ----------

// Build an element. Text always goes in as text, never as HTML.
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function show(...nodes) {
  app.replaceChildren(...nodes);
  const first = app.querySelector("[autofocus]");
  if (first) first.focus();
}

async function api(path, options) {
  const opts = options || {};
  const init = { method: opts.method || "GET", credentials: "same-origin",
                 headers: { "X-Requested-With": "oread" } };
  if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  const response = await fetch(path, init);
  let data = null;
  try { data = await response.json(); } catch (e) { data = null; }
  if (!response.ok) {
    const error = new Error(messageOf(data) || `Oread answered ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function messageOf(data) {
  if (!data || data.detail === undefined) return "";
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg).join("; ");
  return "";
}

function field(label, input, hint) {
  // the hint is linked to the box (read out after the label), not part of the label itself
  if (hint) input.setAttribute("aria-describedby", input.id + "-hint");
  return h("div", { class: "field" },
    h("label", { for: input.id }, label),
    input,
    hint ? h("span", { class: "hint", id: input.id + "-hint" }, hint) : null);
}

function input(id, type, extra) {
  return h("input", Object.assign({ id: id, name: id, type: type }, extra || {}));
}

function brand() {
  return h("div", { class: "brand" }, h("img", { src: "icon.svg", alt: "" }), h("span", {}, "Oread"));
}

// A form whose submit button shows it's busy, and whose errors appear above the button.
function form(fields, buttonText, onSubmit) {
  const error = h("p", { class: "error", role: "alert" });
  const button = h("button", { class: "primary wide", type: "submit" }, buttonText);
  const el = h("form", {
    novalidate: true,
    onsubmit: async (event) => {
      event.preventDefault();
      error.textContent = "";
      button.disabled = true;
      try {
        await onSubmit(el, error);
      } catch (e) {
        error.textContent = e.message;
      } finally {
        button.disabled = false;
      }
    },
  }, fields, error, button);
  return el;
}

// Under the second password box, say as you type whether the two match (and whether
// the first is long enough), so mistakes show before pressing the button.
function checkPasswords(formEl, firstId, secondId) {
  const first = formEl.querySelector("#" + firstId);
  const second = formEl.querySelector("#" + secondId);
  const note = h("p", { class: "match", id: secondId + "-match", role: "status", "aria-live": "polite" });
  second.parentNode.append(note);
  second.setAttribute("aria-describedby", note.id);
  const update = () => {
    note.className = "match";
    if (!second.value) {
      note.textContent = "";
    } else if (first.value.length < 10) {
      note.textContent = "\u2717 The password needs at least 10 characters (" + first.value.length + " so far)";
      note.classList.add("bad");
    } else if (first.value === second.value) {
      note.textContent = "\u2713 Passwords match";
      note.classList.add("good");
    } else {
      note.textContent = "\u2717 Passwords don't match";
      note.classList.add("bad");
    }
  };
  first.addEventListener("input", update);
  second.addEventListener("input", update);
  formEl.addEventListener("reset", () => { note.textContent = ""; note.className = "match"; });
}

function value(formEl, id) {
  return formEl.querySelector("#" + id).value;
}

// "Are you sure?" asked in place of the button that was pressed, not in a pop-up: the question,
// then the action's own button and Cancel. Cancel (or Escape) puts the first button back.
function askFirst(button, question, yesText, action) {
  const sure = h("button", { type: "button", class: "primary danger" }, yesText);
  const cancel = h("button", { type: "button" }, "Cancel");
  const box = h("span", { class: "ask", role: "group", "aria-label": question },
    h("span", { class: "ask-q" }, question), sure, cancel);
  const back = () => { if (box.isConnected) { box.replaceWith(button); button.focus(); } };
  button.replaceWith(box);
  sure.focus();
  cancel.addEventListener("click", back);
  box.addEventListener("keydown", (e) => { if (e.key === "Escape") back(); });
  sure.addEventListener("click", async () => {
    sure.disabled = true;
    try { await action(); } finally { back(); }
  });
}

// ---------- starting up ----------

async function start() {
  try {
    const setup = await api("/api/setup");
    if (setup.needed) return showSetup();
  } catch (e) {
    return show(h("div", { class: "door" }, h("div", { class: "card" }, brand(),
      h("p", { class: "error" }, "Couldn't reach Oread: " + e.message))));
  }
  try {
    session = await api("/api/session");
    showFrame();
  } catch (e) {
    if (e.status === 401) showSignIn();
    else show(h("p", { class: "error" }, e.message));
  }
}

// ---------- first run ----------

function showSetup() {
  const f = form([
    field("Setup code", input("code", "text", { autocomplete: "off", autocapitalize: "characters",
      spellcheck: "false", placeholder: "XXXX-XXXX-XXXX", autofocus: true, required: true }),
      "On the server: in data/setup-code.txt, or in Oread's log (docker compose logs oread)."),
    field("Your username", input("username", "text", { autocomplete: "username",
      autocapitalize: "none", spellcheck: "false", required: true }),
      "Pick your own; avoid \"admin\"."),
    field("Password", input("password", "password", { autocomplete: "new-password", required: true }),
      "At least 10 characters."),
    field("Password again", input("password2", "password", { autocomplete: "new-password", required: true })),
    h("div", { class: "field" }, h("label", { class: "check" }, input("sample", "checkbox"), " Start with a sample household"),
      h("span", { class: "hint" }, "Three volunteers' voices to try Oread on (about a minute); remove it any time in Settings.")),
  ], "Create the super user", async (el) => {
    if (value(el, "password") !== value(el, "password2")) throw new Error("The two passwords don't match");
    await api("/api/setup", { method: "POST", body: {
      code: value(el, "code"), username: value(el, "username"), password: value(el, "password") } });
    session = await api("/api/session");
    const withSample = el.querySelector("#sample").checked;
    if (withSample) await api("/sample", { method: "POST" });
    location.hash = withSample ? "#/learn" : "#/account";
    showFrame();
  });
  checkPasswords(f, "password", "password2");
  show(h("div", { class: "door" }, h("main", { class: "card" }, brand(),
    h("h1", {}, "Welcome to Oread"),
    h("p", { class: "quiet" }, "The first account is the super user: it does everything and adds everyone else. ",
      guideMore("4. First run: create the super user")),
    f)));
}

// ---------- signing in ----------

function showSignIn(message) {
  const f = form([
    field("Username", input("username", "text", { autocomplete: "username", autocapitalize: "none",
      spellcheck: "false", autofocus: true, required: true })),
    field("Password", input("password", "password", { autocomplete: "current-password", required: true })),
  ], "Sign in", async (el) => {
    await api("/api/session", { method: "POST", body: {
      username: value(el, "username"), password: value(el, "password") } });
    session = await api("/api/session");
    showFrame();
  });
  show(h("div", { class: "door" }, h("main", { class: "card" }, brand(),
    h("h1", {}, "Sign in"),
    message ? h("p", { class: "quiet" }, message) : null,
    f,
    h("p", { class: "quiet", style: null }, h("small", {},
      "Forgot your password? Someone above you can reset it on the Users page, or reset it " +
      "on the server: docker compose exec oread python -m oread.users reset <name>")))));
}

// ---------- the app frame ----------

// Each page: where it lives, its name, the API area it needs, and (until it's built) what it will hold.
const PAGES = [
  { id: "learn", name: "Learn", needs: "clips", wide: true },
  { id: "people", name: "People", needs: "profiles", wide: true },
  { id: "mishearings", name: "Mishearings", needs: "mishearings", wide: true },
  { id: "explore", name: "Explore", needs: "clips", wide: true },
  { id: "ospri", name: "OSPRI", needs: "ospri" },
  { id: "wepwawet", name: "Wepwawet", needs: "wepwawet" },
  { id: "devices", name: "Devices", needs: "devices" },
  { id: "settings", name: "Settings", needs: "settings" },
  { id: "imports", name: "Imports", needs: "settings" },
  { id: "connections", name: "Connections", needs: "home assistant" },
  { id: "try", name: "Try it", needs: "try" },
  { id: "stats", name: "Stats", needs: "resources", wide: true },
  { id: "users", name: "Users", needs: "users" },
  { id: "account", name: "Account", needs: null },
  { id: "guide", name: "Setup guide", needs: null, icon: "help" },
];

// the usual help sign: a question mark in a circle (drawn here, so nothing is downloaded)
function helpIcon() {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", "icon");
  const parts = [
    ["circle", { cx: "12", cy: "12", r: "10" }],
    ["path", { d: "M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2.5-3 4.5" }],
    ["circle", { cx: "11.9", cy: "17.6", r: "0.6", fill: "currentColor" }],
  ];
  for (const [tag, attrs] of parts) {
    const el = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    svg.append(el);
  }
  return svg;
}

function mayOpen(page) {
  return !page.needs || (session.can[page.needs] && session.can[page.needs].read);
}

function currentPage() {
  const id = (location.hash.match(/^#\/([a-z-]+)/) || [])[1];
  const pages = PAGES.filter(mayOpen);
  return pages.find((p) => p.id === id) || pages[0];
}

function showFrame() {
  const page = currentPage();
  const side = h("nav", { class: "side", id: "side", "aria-label": "Pages" },
    brand(),
    h("div", { class: "nav" }, PAGES.filter(mayOpen).map((p) =>
      h("a", { href: "#/" + p.id, "aria-current": p.id === page.id ? "page" : null,
        class: p.icon ? "with-icon" : null }, p.icon ? helpIcon() : null, p.name))),
    h("div", { class: "who" },
      h("strong", {}, session.user.name),
      h("span", { class: "badge" }, session.user.role)));
  const toggle = h("button", { class: "menu-toggle", type: "button", "aria-controls": "side",
    "aria-expanded": "false", onclick: () => {
      const open = side.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    } }, "Menu");
  const main = h("main", { class: page.wide ? "main wide" : "main", id: "main" });
  show(h("div", { class: "frame" },
    h("header", { class: "top" }, brand(), toggle),
    side, main));
  document.title = page.name + " · Oread";
  foldEverything(main, page.id);
  renderPage(page, main);
}

// Every box with a heading folds away, for room (remembered in this browser, per page and heading).
// Boxes drawn later (after a load) are folded as they appear.
function foldEverything(main, pageId) {
  const fold = (card) => {
    if (card.tagName === "DETAILS" || card.closest("details") || card.closest("form")) return;
    const head = card.querySelector(":scope > h2");
    if (!head) return;
    const box = h("details", { class: card.className + " fold" });
    for (const [k, v] of Object.entries(card.dataset)) box.dataset[k] = v;
    if (card.id) box.id = card.id;
    card.replaceWith(box);
    head.remove();
    box.append(h("summary", {}, head), ...Array.from(card.childNodes));
    foldable(box, pageId + ":" + head.textContent.trim().replace(/\s*\(\d+\)$/, ""));
  };
  const sweep = (root) => root.querySelectorAll("section.card, div.card.panel").forEach(fold);
  new MutationObserver((changes) => changes.forEach((c) => c.addedNodes.forEach((n) => {
    if (n.nodeType !== 1) return;
    if (n.matches && n.matches("section.card, div.card.panel")) fold(n);
    sweep(n);
  }))).observe(main, { childList: true, subtree: true });
}

function renderPage(page, main) {
  if (page.id === "account") return renderAccount(main);
  if (page.id === "stats") return renderStats(main);
  if (page.id === "connections") return renderConnections(main);
  if (page.id === "try") return renderTry(main);
  if (page.id === "learn") return renderLearn(main);
  if (page.id === "people") return renderPeople(main);
  if (page.id === "devices") return renderDevices(main);
  if (page.id === "settings") return renderSettings(main);
  if (page.id === "users") return renderUsers(main);
  if (page.id === "guide") return renderGuide(main);
  if (page.id === "imports") return renderImports(main);
  if (page.id === "mishearings") return renderMishearings(main);
  if (page.id === "wepwawet") return renderWepwawet(main);
  if (page.id === "explore") return renderExplore(main);
  if (page.id === "ospri") return renderOspri(main);
  main.append(
    h("h1", {}, page.name),
    h("div", { class: "card panel" },
      h("p", {}, page.soon),
      h("p", { class: "quiet" }, "This page is next to be built. Everything it will show already " +
        "works on the API page (/docs).")));
}

// ---------- Explore: every clip and every misheard word, in a pivot table ----------

// PivotTable.js (pivottable.js.org, MIT) with jQuery and jQuery UI, kept in vendor/ and loaded only here
let pivotReady = null;
function loadPivot() {
  if (pivotReady) return pivotReady;
  const script = (src) => new Promise((resolve, reject) => {
    document.head.append(h("script", { src, onload: resolve, onerror: () => reject(new Error("Couldn't load " + src)) }));
  });
  document.head.append(h("link", { rel: "stylesheet", href: "vendor/pivot.min.css" }));
  pivotReady = script("vendor/jquery.min.js").then(() => script("vendor/jquery-ui.min.js"))
    .then(() => script("vendor/pivot.min.js")).then(() => script("vendor/export_renderers.min.js"))
    .catch((e) => { pivotReady = null; throw e; });
  return pivotReady;
}

const EXPLORE_SETS = {
  clips: { label: "Clips heard", hidden: ["clip", "time", "heard", "meant", "Score", "Seconds", "Words", "Speech dB",
    "Noise dB", "Speech over noise dB"],
    start: { rows: ["Speaker"], cols: ["Device"], aggregatorName: "Share that are yes (95% range)", vals: ["Misheard"],
      rendererName: "Heatmap" } },
  words: { label: "Words misheard", hidden: ["clip", "time", "heard", "meant", "Times"],
    start: { rows: ["Meant", "Heard"], cols: ["Speaker"], aggregatorName: "Count", vals: [], rendererName: "Table",
      exclusions: { Kind: ["right"] } } },
};
const PIVOT_KEYS = ["rows", "cols", "aggregatorName", "vals", "rendererName", "exclusions", "inclusions", "rowOrder", "colOrder"];

// fields worked out on the page: local day, hour and weekday, bands of the numbers, wrong or right
function exploreRow(r) {
  const out = Object.assign({}, r);
  if (r.time) {
    const d = new Date(r.time);
    const two = (n) => String(n).padStart(2, "0");
    out.Day = d.getFullYear() + "-" + two(d.getMonth() + 1) + "-" + two(d.getDate());
    out.Hour = two(d.getHours());
    out.Weekday = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getDay()];
    out.Month = d.getFullYear() + "-" + two(d.getMonth() + 1);
  }
  const band = (v, size, unit) => (typeof v === "number" ? (Math.floor(v / size) * size).toFixed(size < 1 ? 1 : 0) + unit : "none");
  if ("Score" in r) out["Score band"] = band(r.Score, 0.1, "");
  if ("Seconds" in r) out["Seconds band"] = band(r.Seconds, 1, " s");
  if ("Speech over noise dB" in r) out["Speech over noise band"] = band(r["Speech over noise dB"], 5, " dB");
  if ("Kind" in r) out.Wrong = r.Kind === "right" ? "no" : "yes";
  return out;
}

// the share of rows whose chosen field is "yes", with its 95% range (Wilson): small counts show wide ranges
function shareAggregator() {
  return function ([attr]) {
    return function () {
      return {
        yes: 0, n: 0,
        push(record) { this.n += 1; if (String(record[attr]) === "yes") this.yes += 1; },
        value() { return this.n ? this.yes / this.n : null; },
        format(x) {
          if (x === null || !this.n) return "";
          const z = 1.96, n = this.n, p = x, zz = z * z / n;
          const mid = (p + zz / 2) / (1 + zz);
          const half = z * Math.sqrt(p * (1 - p) / n + zz / (4 * n)) / (1 + zz);
          const pct = (v) => Math.round(Math.max(0, Math.min(1, v)) * 100) + "%";
          return pct(p) + " (" + pct(mid - half) + "–" + pct(mid + half) + ") of " + n;
        },
        numInputs: 1,
      };
    };
  };
}

function renderExplore(main) {
  let current = hashParams().get("set") || "clips";
  if (!EXPLORE_SETS[current]) current = "clips";
  const tabs = h("div", { class: "tabs", role: "tablist", "aria-label": "Which rows" });
  const error = h("p", { class: "error", role: "alert" });
  const count = h("p", { class: "quiet" });
  const holder = h("div", { class: "pivot-wrap", id: "pivot" });
  const behind = h("div", { id: "behind" });
  let data = null;
  let shown = [];              // the rows the pivot's filters let through, for the download
  const saved = (set) => {
    try { return JSON.parse(localStorage.getItem("oread-explore:" + set) || "null"); } catch (e) { return null; }
  };
  const remember = (set, config) => {
    const keep = {};
    PIVOT_KEYS.forEach((k) => { keep[k] = config[k]; });
    try { localStorage.setItem("oread-explore:" + set, JSON.stringify(keep)); } catch (e) { /* storage off */ }
  };
  const passes = (row, config) => Object.entries(config.exclusions || {}).every(([k, out]) => !out.includes(String(row[k]))) &&
    Object.entries(config.inclusions || {}).every(([k, keep]) => !keep.length || keep.includes(String(row[k])));
  const draw = async () => {
    tabs.replaceChildren(...Object.entries(EXPLORE_SETS).map(([id, set]) => h("button", { type: "button", role: "tab",
      "aria-selected": id === current ? "true" : "false",
      onclick: () => { current = id; history.replaceState(null, "", "#/explore?set=" + id); behind.replaceChildren(); draw(); } }, set.label)));
    error.textContent = "";
    try {
      await loadPivot();
      if (!data) data = await api("/explore");
    } catch (e) {
      error.textContent = e.message;
      return;
    }
    const $ = window.jQuery;
    const set = EXPLORE_SETS[current];
    const rows = data[current].map(exploreRow);
    count.textContent = rows.length + " rows. Drag a field into the rows or columns, click ▾ on a field to filter it, " +
      "click a cell to hear the clips behind it.";
    const util = $.pivotUtilities;
    const aggregators = Object.assign({ "Share that are yes (95% range)": shareAggregator() }, util.aggregators);
    const renderers = Object.assign({}, util.renderers, util.export_renderers);
    $(holder).empty();
    $(holder).pivotUI(rows, Object.assign({
      aggregators, renderers,
      hiddenFromDragDrop: set.hidden,
      hiddenFromAggregators: ["clip", "time", "heard", "meant"],
      unusedAttrsVertical: true,
      menuLimit: 1000,
      rendererOptions: { table: { clickCallback: (e, value, filters, pivotData) => {
        const found = [];
        pivotData.forEachMatchingRecord(filters, (r) => found.push(r));
        drawBehind(behind, found, filters);
      } } },
      onRefresh: (config) => { remember(current, config); shown = rows.filter((r) => passes(r, config)); },
    }, set.start, saved(current) || {}), true);
  };
  const download = () => {
    const rows = shown.length ? shown : [];
    if (!rows.length) return;
    const keys = Object.keys(rows[0]);
    const cell = (v) => { const t = v === null || v === undefined ? "" : String(v); return /[",\n]/.test(t) ? "\"" + t.replace(/"/g, "\"\"") + "\"" : t; };
    const csv = [keys.map(cell).join(",")].concat(rows.map((r) => keys.map((k) => cell(r[k])).join(","))).join("\n");
    const link = h("a", { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: "oread-" + current + ".csv" });
    document.body.append(link);
    link.click();
    link.remove();
  };
  const reset = () => {
    try { localStorage.removeItem("oread-explore:" + current); } catch (e) { /* storage off */ }
    behind.replaceChildren();
    draw();
  };
  main.append(h("h1", {}, "Explore"),
    h("p", { class: "quiet" }, "Every clip and misheard word, to slice any way you like. ",
      guideMore("Explore: slice the clips and the mishearings")),
    h("div", { class: "toolbar" }, tabs,
      h("button", { type: "button", onclick: download }, "Download these rows (CSV)"),
      h("button", { type: "button", class: "quiet-button", onclick: reset }, "Start the layout over")),
    error, count, holder, behind);
  draw();
}

// the clips behind a cell of the pivot table, newest first, each playable while Oread still has it
function drawBehind(box, found, filters) {
  const where = Object.entries(filters).map(([k, v]) => k + ": " + v).join(", ") || "every row";
  const rows = found.slice().sort((a, b) => String(b.time).localeCompare(String(a.time))).slice(0, 100);
  box.replaceChildren(h("section", { class: "card panel" }, h("h2", {}, "Behind the cell (" + found.length + ")"),
    h("p", { class: "quiet" }, where + (found.length > rows.length ? ". The newest " + rows.length + " shown." : ".")),
    h("ul", { class: "rows behind" }, rows.map((r) => h("li", {},
      r.clip ? playButton("/clips/" + encodeURIComponent(r.clip) + "/audio", Number(r.Seconds) || 0) : null, " ",
      h("span", { class: "quiet small" }, r.time ? when(r.time) : ""), " ",
      h("strong", {}, r.Speaker || ""), " on ", r.Device || "", ": ",
      h("q", {}, r.heard || ""),
      r.meant ? h("span", { class: "quiet" }, " meant ", h("q", {}, r.meant)) : null)))));
}

// ---------- OSPRI: in v1.0.0 it gathers a record of each request and exports them ----------

function renderOspri(main) {
  const body = h("div", {}, h("p", { class: "quiet" }, "Loading\u2026"));
  const error = h("p", { class: "error", role: "alert" });
  const load = async () => {
    try {
      const d = await api("/ospri");
      const gather = h("input", { type: "checkbox", id: "ospri-gather", checked: d.gather, disabled: !can("ospri", true),
        onchange: async () => {
          error.textContent = "";
          try { await api("/ospri", { method: "PATCH", body: { gather: gather.checked } }); load(); } catch (e) { error.textContent = e.message; }
        } });
      const kb = d.bytes < 1024 * 1024 ? Math.max(1, Math.round(d.bytes / 1024)) + " KB" : (d.bytes / 1024 / 1024).toFixed(1) + " MB";
      body.replaceChildren(h("section", { class: "card panel", id: "ospri-records" }, h("h2", {}, "Records"),
        h("div", { class: "field" }, h("label", { class: "check" }, gather, " Gather records"),
          h("span", { class: "hint" }, "While on, each request adds a record, kept even after its clip is trimmed.")),
        h("dl", { class: "kv" },
          h("dt", {}, "Records"), h("dd", {}, String(d.records)),
          h("dt", {}, "From"), h("dd", {}, d.first ? when(d.first) + " to " + when(d.last) : "none yet"),
          h("dt", {}, "On disk"), h("dd", {}, d.records ? kb + " (" + d.file + ")" : "nothing yet")),
        h("p", { class: "quiet" }, "Each export joins in what was meant, from the mishearings pulled from the house router, so " +
          "every record says whether it was misheard."),
        h("div", { class: "row" },
          h("a", { class: "button-link", href: "/ospri/records?format=csv", download: "oread-ospri-records.csv" }, "Export CSV"),
          h("a", { class: "button-link", href: "/ospri/records?format=json", download: "oread-ospri-records.json" }, "Export JSON")),
        error));
    } catch (e) {
      body.replaceChildren(h("p", { class: "error" }, e.message));
    }
  };
  main.append(h("h1", {}, "OSPRI"),
    h("p", { class: "quiet" }, "Oread STT Pattern Recognition Improvement: gathers a record of each request to export. ",
      guideMore("OSPRI: gather records for analysis")), body);
  load();
}

// ---------- Wepwawet: how Oread works with the house router ----------

function renderWepwawet(main) {
  const body = h("div", {}, h("p", { class: "quiet" }, "Loading…"));
  const load = async () => {
    try {
      drawWepwawet(body, await api("/wepwawet"), load);
    } catch (e) {
      body.replaceChildren(h("p", { class: "error" }, e.message));
    }
  };
  main.append(h("h1", {}, "Wepwawet"),
    h("p", { class: "quiet" }, "Optional: connect Oread to a Wepwawet house router (Wepwawet Veil, coming soon). ",
      guideMore("The Wepwawet page")), body);
  load();
}

function drawWepwawet(body, d, reload) {
  const canChange = can("wepwawet", true);
  const error = h("p", { class: "error", role: "alert" });
  const done = h("p", { class: "ok", role: "status" });
  const act = async (fn, okText) => {
    error.textContent = "";
    done.textContent = "";
    try { await fn(); await reload(); } catch (e) { error.textContent = e.message; return; }
    const ok = body.querySelector(".ok[role=status]");
    if (ok && okText) ok.textContent = okText;
  };
  const toggle = (key, label, hint) => {
    const box = h("input", { type: "checkbox", id: "ww-" + key, checked: Boolean(d[key]), disabled: !canChange,
      onchange: () => act(() => api("/wepwawet", { method: "PATCH", body: { [key]: box.checked } }), "Saved.") });
    return h("div", { class: "field" }, h("label", { class: "check" }, box, " " + label), h("span", { class: "hint" }, hint));
  };
  // the router: on or off, its address, its token
  const urlBox = input("router-url", "text", { value: d.url || "", placeholder: "for example http://192.168.1.20:8770",
    autocomplete: "off", spellcheck: "false" });
  const keyBox = input("router-key", "password", { autocomplete: "off", placeholder: "the router's token for its oread door" });
  const conn = h("section", { class: "card panel", id: "router" }, h("h2", {}, "The house router"),
    toggle("enabled", "Enabled", "Off: Oread works on its own; nothing is pulled from or told to the router."),
    h("dl", { class: "kv" },
      h("dt", {}, "Address"), h("dd", {}, d.url ? h("span", { class: "mono" }, d.url) : "not set: off",
        " ", h("span", { class: "quiet small" }, "(from " + d.url_source + ")")),
      h("dt", {}, "Its token"), h("dd", {}, d.token_in_vault ? "in the vault as " + d.token_key
        : "not in the vault yet (the router makes it: Security, API keys, the oread door)")));
  if (canChange) {
    conn.append(h("form", { class: "inline", novalidate: true, onsubmit: (event) => {
      event.preventDefault();
      act(() => api("/mishearings/router", { method: "PUT", body: { url: urlBox.value.trim() } }), "Address saved.");
    } }, h("label", { for: "router-url" }, "The router's address (its chat door; empty: off)"),
      h("div", { class: "row" }, urlBox, h("button", { type: "submit" }, "Save"))));
  }
  if (can("vault", true)) {
    conn.append(h("form", { class: "inline", novalidate: true, onsubmit: (event) => {
      event.preventDefault();
      if (!keyBox.value.trim()) { error.textContent = "Paste the router's token first"; return; }
      act(() => api("/vault/" + encodeURIComponent(d.token_key), { method: "PUT",
        body: { value: keyBox.value.trim(), service: "wepwawet", note: "the house router's oread door" } }), "Token saved in the vault.");
    } }, h("label", { for: "router-key" }, d.token_in_vault ? "Replace its token" : "Its token"),
      h("div", { class: "row" }, keyBox, h("button", { type: "submit" }, "Save"))));
  }
  // people in step with the router's people grid
  const p = d.people;
  const rows = p ? p.here.map((x) => [x.name, x.at_router ? (x.at_router === x.name ? "yes" : "yes, as " + x.at_router) : "not yet"]) : [];
  const syncBtn = h("button", { type: "button", class: "primary", disabled: !canChange || !p || null,
    onclick: () => act(() => api("/wepwawet/people", { method: "POST" }), "The router has everyone now.") }, "Add the missing ones to the router");
  const people = h("section", { class: "card panel" }, h("h2", {}, "People"),
    toggle("people_sync", "Keep people in step", "People added or renamed here change at the router too."),
    p ? [table(["Here", "At the router"], rows),
      p.only_at_router.length ? h("p", { class: "quiet small" }, "At the router, not here: " + p.only_at_router.join(", ")) : null,
      h("div", { class: "toolbar gap-top" }, syncBtn)]
      : h("p", { class: "quiet" }, d.people_error || "Set the router up above to see your people beside its people grid."));
  // the nightly pull
  const hour = h("select", { id: "ww-hour", disabled: !canChange,
    onchange: () => act(() => api("/wepwawet", { method: "PATCH", body: { pull_hour: Number(hour.value) } }), "Saved.") },
    Array.from({ length: 24 }, (_, i) => h("option", { value: i, selected: i === d.pull_hour }, i + ":00")));
  const last = d.last_pull;
  const pull = h("section", { class: "card panel" }, h("h2", {}, "Mishearings"),
    toggle("nightly_pull", "Pull them every night", "Once a night, by this server's clock."),
    field("At", hour, "The hour it pulls."),
    h("p", { class: "quiet small" }, last ? "Last pull " + when(last.time) + ": " + last.lines + " lines (" + last.new + " new)." : "Not pulled yet.",
      " ", h("a", { href: "#/mishearings" }, "Mishearings")));
  body.replaceChildren(conn, people, pull, error, done);
}

// ---------- Mishearings: pulled from the house router (Wepwawet Veil) ----------

const MISHEARD_COLUMNS = [
  ["Really said", (l) => (l.meant || "").toLowerCase()],
  ["Heard", (l) => l.said.toLowerCase()],
  ["Times", (l) => l.count],
  ["Devices", (l) => devicesOf(l).join(", ")],
  ["Speech model", (l) => modelsOf(l).join(", ")],
  ["Clips", null],
  ["Last heard", (l) => l.last || ""],
  ["At the router", (l) => (l.gone ? 0 : 1)],
];

function devicesOf(line) {
  return [...new Set((line.clips || []).map((c) => c.device).filter(Boolean))].sort();
}

function modelsOf(line) {
  return [...new Set((line.clips || []).map((c) => (c.heard_with || {}).stt_model).filter(Boolean))].sort();
}

function renderMishearings(main) {
  const body = h("div", {}, h("p", { class: "quiet" }, "Loading…"));
  const sort = { col: 6, down: true };
  const load = async () => {
    try {
      drawMishearings(body, await api("/mishearings"), sort, load);
    } catch (e) {
      body.replaceChildren(h("p", { class: "error" }, e.message));
    }
  };
  main.append(h("h1", {}, "Mishearings"),
    h("p", { class: "quiet" }, "Optional: words speech-to-text got wrong, from a Wepwawet house router, with their clips. ",
      guideMore("Mishearings from the house router (optional)")), body);
  load();
}

function drawMishearings(body, d, sort, reload) {
  const error = h("p", { class: "error", role: "alert" });
  const done = h("p", { class: "ok", role: "status" });
  const act = async (fn, okText) => {
    error.textContent = "";
    done.textContent = "";
    try {
      await fn();
      await reload();
    } catch (e) {
      error.textContent = e.message;
      return;
    }
    if (okText) body.querySelector("[role=status]").textContent = okText;
  };
  const conn = h("section", { class: "card panel", id: "router" }, h("h2", {}, "The house router"),
    h("p", { class: "quiet small" }, d.url ? ["From ", h("span", { class: "mono" }, d.url),
      d.enabled === false ? " (switched off)" : "", d.nightly_pull ? ", pulled every night at " + d.pull_hour + ":00" : ""] : "Not set up: ",
    " The router's address, its token and the nightly pull are on the ", h("a", { href: "#/wepwawet" }, "Wepwawet"), " page."));
  const pull = h("button", { type: "button", class: "primary", disabled: d.ready ? null : "",
    onclick: () => {
      pull.disabled = true;
      pull.textContent = "Pulling…";
      act(() => api("/mishearings/pull", { method: "POST" }), "");
    } }, "Pull from the router");
  const last = d.last_pull;
  conn.append(h("div", { class: "toolbar gap-top" }, can("mishearings", true) ? pull : null,
    h("span", { class: "quiet small" }, last ? "Last pull " + when(last.time) + ": " + last.lines + " lines (" + last.new +
      " new, " + last.changed + " changed, " + last.gone + " gone), " + last.clips_new + " new clips; " + last.clips_found +
      " clips found here, " + last.clips_missing + " not (gone before the pull, or another Oread's)." : "Not pulled yet.")),
    error, done);
  const rows = d.lines || [];
  const lines = h("section", { class: "card panel" }, h("h2", {}, "Lines (" + rows.length + ")"),
    rows.length ? sortTable(MISHEARD_COLUMNS.map(([label, by]) => [label, by, (l) => misheardCell(label, l)]), rows, sort,
      (l) => ({ class: l.gone ? "gone" : null }))
      : h("p", { class: "quiet" }, "Nothing pulled yet."));
  body.replaceChildren(conn, lines);
}

function misheardCell(label, l) {
  if (label === "Really said") return l.meant || h("span", { class: "quiet" }, "not given yet");
  if (label === "Heard") return l.said;
  if (label === "Times") return String(l.count);
  if (label === "Devices") return devicesOf(l).join(", ") || h("span", { class: "quiet" }, "-");
  if (label === "Speech model") return modelsOf(l).join(", ") || h("span", { class: "quiet" }, "unknown");
  if (label === "Clips") {
    const clips = l.clips || [];
    if (!clips.length) return h("span", { class: "quiet" }, "none (typed, or before clips were kept)");
    return h("span", {}, clips.map((c) => c.playable
      ? playButton("/clips/" + encodeURIComponent(c.clip) + "/audio", c.audio_s || 0)
      : h("span", { class: "quiet small", title: c.clip }, c.found ? "gone " : "not here ")));
  }
  if (label === "Last heard") return l.last || "-";
  return l.gone ? h("span", { class: "quiet" }, "gone") : "yes";
}

// ---------- Learn: listen, read, and assign clips to people ----------

const PAGE_SIZE = 24;

function hashParams() {
  const at = location.hash.indexOf("?");
  return new URLSearchParams(at >= 0 ? location.hash.slice(at + 1) : "");
}

function renderLearn(main) {
  const person = hashParams().get("person") || "";
  const state = { status: person ? "assigned" : "unassigned", device: "", limit: PAGE_SIZE, person: person };
  const tabs = h("div", { class: "tabs", role: "tablist", "aria-label": "Which clips" });
  const deviceSelect = h("select", { id: "learn-device", "aria-label": "Device" },
    h("option", { value: "" }, "All devices"));
  const summary = h("p", { class: "quiet", role: "status" });
  const list = h("div", {});
  const more = h("button", { type: "button", class: "more", hidden: true }, "Show more");
  const sort = { col: 2, down: true };   // newest first until a heading is clicked
  const ticked = new Set();               // clips ticked to discard
  const discardTicked = h("button", { type: "button", class: "quiet-button", disabled: true,
    onclick: (e) => askFirst(e.currentTarget, "Discard " + ticked.size + (ticked.size === 1 ? " clip" : " clips") +
      "? They're deleted for good.", "Discard", async () => {
      const ids = Array.from(ticked);
      try {
        for (const id of ids) await api("/clips/" + encodeURIComponent(id), { method: "DELETE" });
        summary.textContent = "Discarded " + ids.length + (ids.length === 1 ? " clip." : " clips.");
      } catch (e) {
        summary.textContent = e.message;
      }
      ticked.clear();
      load(true);
    }) }, "Discard ticked");
  const tickOld = h("button", { type: "button", class: "quiet-button", hidden: true,
    title: "Clips heard before their device's last retrain, when it sounded different", onclick: async () => {
      try {
        const all = await api("/clips?status=unassigned&limit=100000" +
          (state.device ? "&device=" + encodeURIComponent(state.device) : ""));
        all.filter((c) => c.old_sound).forEach((c) => ticked.add(c.id));
        list.querySelectorAll("tr.clip").forEach((row) => {
          const box = row.querySelector("input[type=checkbox]");
          if (box) box.checked = ticked.has(row.getAttribute("data-clip"));
        });
        onTick();
      } catch (e) { summary.textContent = e.message; }
    } }, "Tick old sound");
  const onTick = () => {
    discardTicked.disabled = !ticked.size;
    discardTicked.textContent = ticked.size ? "Discard ticked (" + ticked.size + ")" : "Discard ticked";
  };
  let people = [];
  let voiceNames = [];
  let shown = [];

  function drawTable() {
    const [, key] = CLIP_COLUMNS[sort.col];
    const rows = shown.slice().sort((a, b) => {
      const x = key(a), y = key(b);
      const order = typeof x === "string" ? x.localeCompare(y) : x - y;
      return sort.down ? -order : order;
    });
    const heading = ([label, by], i) => {
      if (!by) return h("th", {}, label);
      const on = sort.col === i;
      return h("th", { "aria-sort": on ? (sort.down ? "descending" : "ascending") : "none" },
        h("button", { type: "button", class: "sort", onclick: () => {
          if (on) sort.down = !sort.down; else { sort.col = i; sort.down = false; }
          drawTable();
        } }, label, on ? (sort.down ? " \u25BE" : " \u25B4") : h("span", { class: "sortable", "aria-hidden": "true" }, " \u21C5")));
    };
    list.replaceChildren(h("div", { class: "table-wrap" }, h("table", { class: "results clips-table" },
      h("thead", {}, h("tr", {}, CLIP_COLUMNS.map(heading))),
      h("tbody", {}, rows.map((c) => clipRow(c, () => ({ people, voices: voiceNames }), load, ticked, onTick))))));
  }

  const tab = (status, label) => h("button", { type: "button", role: "tab", "data-status": status,
    "aria-selected": state.status === status ? "true" : "false",
    onclick: () => { state.status = status; state.limit = PAGE_SIZE; if (status === "unassigned") state.person = ""; load(); } }, label);

  async function load(keepSummary) {
    tabs.replaceChildren(tab("unassigned", "Waiting"), tab("assigned", "Assigned"));
    ticked.clear();
    onTick();
    const said = keepSummary === true ? summary.textContent : "";
    list.replaceChildren(h("p", { class: "quiet" }, "Loading…"));
    try {
      const query = "/clips?status=" + state.status + "&limit=" + (state.limit + 1) +
        (state.device ? "&device=" + encodeURIComponent(state.device) : "") +
        (state.person && state.status === "assigned" ? "&person=" + encodeURIComponent(state.person) : "");
      const [clips, profiles, status] = await Promise.all([api(query), api("/profiles?all=true"), api("/status")]);
      people = profiles.filter((p) => p.kind !== "assistant").map((p) => p.name);
      voiceNames = profiles.filter((p) => p.kind === "assistant").map((p) => p.name);   // never people: listed apart
      if (deviceSelect.options.length === 1) {
        status.devices.forEach((d) => deviceSelect.append(h("option", { value: d.name }, d.name)));
      }
      shown = clips.slice(0, state.limit);
      tickOld.hidden = state.status !== "unassigned";
      more.hidden = clips.length <= state.limit;
      if (state.status === "unassigned") {
        summary.replaceChildren((said ? said + " " : "") + status.review_list + " waiting to be learned (Oread keeps the newest " +
          status.review_list_max + ").");
      } else if (state.person) {
        summary.replaceChildren("Only " + state.person + "'s clips. ",
          h("a", { href: "#/learn", onclick: (e) => { e.preventDefault(); state.person = "";
            history.replaceState(null, "", "#/learn?tab=assigned"); load(); } }, "Show everyone's"));
      } else {
        summary.replaceChildren(status.assigned_clips + " assigned to " + people.length +
          (people.length === 1 ? " person." : " people."));
      }
      if (shown.length) drawTable();
      else list.replaceChildren(h("p", { class: "empty-state" }, state.status === "unassigned"
        ? "Nothing waiting. Speak to a listening device, or use Try it, and clips appear here."
        : "No clips assigned yet."));
    } catch (e) {
      list.replaceChildren(h("p", { class: "error" }, e.message));
    }
  }

  deviceSelect.addEventListener("change", () => { state.device = deviceSelect.value; state.limit = PAGE_SIZE; load(); });
  more.addEventListener("click", () => { state.limit += PAGE_SIZE; load(); });
  main.append(
    h("h1", {}, "Learn"),
    h("p", { class: "quiet" }, "Listen, then tell Oread who was speaking: each clip teaches it that voice. ",
      guideMore("11. Teach Oread voices")),
    teachingTips(),
    h("div", { class: "toolbar" }, tabs, deviceSelect, tickOld, discardTicked),
    summary, list, more);
  load();
}

// what's worth assigning, in the spirit of Frigate's advice for teaching faces
function teachingTips() {
  return h("details", { class: "tips card" },
    h("summary", {}, "What's worth teaching?"),
    h("ul", {},
      h("li", {}, h("strong", {}, "Teach the clips Oread was unsure about. "),
        "A \u201Cmaybe\u201D, or a voice you know that it called unknown, helps it most."),
      h("li", {}, h("strong", {}, "Skip the ones it already names with a high score "),
        "(about 0.75 or more). They add little; leave them or discard them."),
      h("li", {}, h("strong", {}, "Only clear clips. "),
        "One person, no TV, music or other voices. If you can't tell who it is, neither can Oread."),
      h("li", {}, h("strong", {}, "A few at a time, and varied. "),
        "Different devices, times and moods: 3 to 5 clips start a person, 10 to 20 make them solid."),
      h("li", {}, h("strong", {}, "When in doubt, leave it out. "),
        "One wrong clip blurs that person's voice. Undo or Take back fixes a mistake.")));
}

function when(iso) {
  const d = new Date(iso);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay ? "Today " + d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
                 : d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

// a small round play button (the browser's full audio bar is too wide for a tile)
let playing = null;
function playButton(src, seconds) {
  const button = h("button", { type: "button", class: "play", "aria-label": "Play the clip (" + seconds.toFixed(1) + " seconds)" }, "\u25B6");
  let audio = null;
  const reset = () => { button.textContent = "\u25B6"; button.classList.remove("on"); };
  button.addEventListener("click", () => {
    if (audio && !audio.paused) { audio.pause(); audio.currentTime = 0; reset(); return; }
    if (playing && playing !== audio) { playing.pause(); playing.dispatchEvent(new Event("ended")); }
    if (!audio) {
      audio = new Audio(src);
      audio.addEventListener("ended", reset);
      audio.addEventListener("error", () => { reset(); button.title = "Couldn't play this clip"; });
    }
    audio.currentTime = 0;
    audio.play().then(() => { button.textContent = "\u25A0"; button.classList.add("on"); playing = audio; })
      .catch(() => reset());
  });
  return button;
}

function guessChip(result, prefix) {
  const r = result || {};
  const by = prefix === undefined ? "Oread: " : prefix;
  const score = typeof r.score === "number" ? " " + r.score.toFixed(2) : "";
  if (r.label === "known") return h("span", { class: "status known" }, by + r.speaker + score);
  if (r.label === "maybe") return h("span", { class: "status maybe" }, by + "maybe " + r.guess + score);
  if (r.label === "too short") return h("span", { class: "status unknown" }, by + "too short to tell");
  return h("span", { class: "status unknown" }, by + "unknown" + (r.guess ? " (closest " + r.guess + score + ")" : ""));
}

// a table whose columns sort on a click (again to reverse). columns: [heading, sort key or null,
// cell]; sort: {col, down}, kept by the caller so a redraw keeps the order
function sortTable(columns, rows, sort, rowAttrs) {
  const wrap = h("div", { class: "table-wrap" });
  function draw() {
    const key = columns[sort.col][1];
    const sorted = rows.slice().sort((a, b) => {
      const x = key(a), y = key(b);
      const order = typeof x === "string" ? x.localeCompare(y) : x - y;
      return sort.down ? -order : order;
    });
    const heading = ([label, by], i) => {
      if (!by) return h("th", {}, label);
      const on = sort.col === i;
      return h("th", { "aria-sort": on ? (sort.down ? "descending" : "ascending") : "none" },
        h("button", { type: "button", class: "sort", onclick: () => {
          if (on) sort.down = !sort.down; else { sort.col = i; sort.down = false; }
          draw();
        } }, label, on ? (sort.down ? " \u25BE" : " \u25B4") : h("span", { class: "sortable", "aria-hidden": "true" }, " \u21C5")));
    };
    wrap.replaceChildren(h("table", { class: "results clips-table" },
      h("thead", {}, h("tr", {}, columns.map(heading))),
      h("tbody", {}, sorted.map((row) => h("tr", rowAttrs ? rowAttrs(row) : {},
        columns.map((c) => h("td", {}, c[2](row))))))));
  }
  draw();
  return wrap;
}

const num = (x) => (typeof x === "number" ? x : -1);

// a person's score in a call: from every score kept (clips since Oct 16), else the closest three
function scoreFor(result, person) {
  const r = result || {};
  if (r.scores && typeof r.scores[person] === "number") return r.scores[person];
  const near = (r.close || []).find((c) => c.name === person);
  if (near) return near.score;
  return r.guess === person && typeof r.score === "number" ? r.score : null;
}

// a score with an arrow against an earlier one: up, down, or flat (moved less than 0.02)
function moved(now, before) {
  if (typeof now !== "number") return "\u2014";
  if (typeof before !== "number") return now.toFixed(2);
  const d = now - before;
  const [mark, kind] = d >= 0.02 ? ["\u2191", "up"] : (d <= -0.02 ? ["\u2193", "down"] : ["\u2192", "flat"]);
  return h("span", { class: "moved " + kind, title: (d >= 0 ? "+" : "") + d.toFixed(2) + " from " + before.toFixed(2) },
    now.toFixed(2) + " " + mark);
}
const shift = (now, before) => (typeof now === "number" && typeof before === "number" ? now - before : -9);

// the Learn table's columns: heading, and what a clip sorts by (null: not sortable)
const CLIP_COLUMNS = [
  ["", null],
  ["", null],
  ["When", (c) => c.time],
  ["Device", (c) => c.device],
  ["Words", (c) => c.transcript.toLowerCase()],
  ["Oread's call", (c) => (c.result && typeof c.result.score === "number" ? c.result.score : -1)],
  ["Length", (c) => c.audio_s],
  ["Can teach", (c) => (c.old_sound ? -1 : (c.trainable ? 1 : 0))],
  ["Who spoke", (c) => (c.profile || "").toLowerCase()],
];

function clipRow(clip, getPeople, reload, ticked, onTick) {
  const card = h("tr", { class: "clip", "data-clip": clip.id });
  const error = h("p", { class: "error", role: "alert" });
  const body = h("div", {});

  const player = playButton("/clips/" + encodeURIComponent(clip.id) + "/audio", clip.audio_s);
  const tick = h("input", { type: "checkbox", "aria-label": "Tick to discard", checked: ticked.has(clip.id),
    onchange: () => { if (tick.checked) ticked.add(clip.id); else ticked.delete(clip.id); onTick(); } });
  // long transcripts are cut to three lines; a click shows the rest
  const words = h("p", { class: "words", title: "Show all", tabindex: "0" }, "\u201C" + clip.transcript + "\u201D");
  const expand = () => words.classList.toggle("open");
  words.addEventListener("click", expand);
  words.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); expand(); } });

  function actions() {
    const people = getPeople();
    const parts = [];
    if (clip.profile) {
      parts.push(h("p", { class: "assigned" }, "\u2713 Assigned to ", h("strong", {}, clip.profile)));
    }
    if (clip.old_sound) {
      parts.push(h("p", { class: "quiet small", title: "Heard before " + clip.device + "'s last retrain, when it " +
        "sounded different" }, "Before the last retrain: not for teaching."));
    } else if (!clip.trainable) {
      parts.push(h("p", { class: "quiet small" }, "Too short to teach a voice; keep it or discard it."));
    } else {
      const guess = clip.profile || (clip.result && (clip.result.speaker || clip.result.guess));
      const select = h("select", { "aria-label": "Who was speaking" },
        h("option", { value: "" }, "Who spoke?"),
        people.people.map((name) => h("option", { value: name, selected: name === guess }, name)),
        h("option", { value: "__new__" }, "New person\u2026"),
        people.voices.length ? h("optgroup", { label: "An assistant's own voice (not a person)" },
          people.voices.map((name) => h("option", { value: name, selected: name === guess }, name))) : null);
      const newName = h("input", { type: "text", placeholder: "Their name", "aria-label": "New person's name",
        hidden: true, autocomplete: "off" });
      select.addEventListener("change", () => {
        newName.hidden = select.value !== "__new__";
        if (!newName.hidden) newName.focus();
      });
      const assign = h("button", { class: "primary", type: "button" }, clip.profile ? "Move" : "Assign");
      assign.addEventListener("click", async () => {
        error.textContent = "";
        const name = select.value === "__new__" ? newName.value.trim() : select.value;
        if (!name) { error.textContent = "Pick who was speaking first."; return; }
        await act(async () => {
          const before = clip.profile;
          Object.assign(clip, await api("/clips/" + encodeURIComponent(clip.id) + "/assign",
            { method: "POST", body: { profile: name } }));
          done("Assigned to " + name + ".", async () => {
            if (before) await api("/clips/" + encodeURIComponent(clip.id) + "/assign", { method: "POST", body: { profile: before } });
            else await api("/clips/" + encodeURIComponent(clip.id) + "/unassign", { method: "POST" });
          });
        });
      });
      parts.push(h("div", { class: "row actions" }, select, newName, assign));
    }
    const side = h("div", { class: "row actions-2" });
    if (clip.profile) {
      side.append(h("button", { type: "button", onclick: () => act(async () => {
        const before = clip.profile;
        Object.assign(clip, await api("/clips/" + encodeURIComponent(clip.id) + "/unassign", { method: "POST" }));
        done("Taken back from " + before + "; it's waiting again.", async () => {
          await api("/clips/" + encodeURIComponent(clip.id) + "/assign", { method: "POST", body: { profile: before } });
        });
      }) }, "Take back"));
    }
    if (side.childNodes.length) parts.push(side);
    body.replaceChildren(...parts);
  }

  async function act(fn) {
    card.classList.add("busy");
    try { await fn(); } catch (e) { error.textContent = e.message; } finally { card.classList.remove("busy"); }
  }

  // after a change: say what happened, with Undo, in place of the controls
  function done(message, undo) {
    const undoButton = h("button", { type: "button" }, "Undo");
    undoButton.addEventListener("click", () => act(async () => { await undo(); reload(); }));
    body.replaceChildren(h("div", { class: "row done", role: "status" }, h("span", {}, "\u2713 " + message), undoButton));
  }

  actions();
  card.append(h("td", {}, tick), h("td", {}, player), h("td", {}, when(clip.time)), h("td", {}, clip.device),
    h("td", { class: "words-cell" }, words), h("td", {}, guessChip(clip.result)),
    h("td", {}, clip.audio_s.toFixed(1) + " s"), h("td", {}, clip.old_sound ? "old sound" : (clip.trainable ? "yes" : "too short")),
    h("td", { class: "act-cell" }, h("div", {}, body, error)));
  return card;
}

// ---------- People: everyone Oread knows by voice ----------

const ENOUGH_CLIPS = 3;   // about where Oread starts naming someone reliably

function renderPeople(main) {
  const tabsAllowed = [["people", "People"], ["retrain", "Retrain"]];
  let current = hashParams().get("tab") === "retrain" ? "retrain" : "people";
  const tabs = h("div", { class: "tabs", role: "tablist", "aria-label": "People or retraining" });
  const body = h("div", {});
  const draw = () => {
    tabs.replaceChildren(...tabsAllowed.map(([id, label]) => h("button", { type: "button", role: "tab",
      "aria-selected": id === current ? "true" : "false",
      onclick: () => { current = id; history.replaceState(null, "", "#/people?tab=" + id); draw(); } }, label)));
    body.replaceChildren();
    if (current === "retrain") drawRetrain(body);
    else drawPeople(body);
  };
  main.append(h("h1", {}, "People"), h("div", { class: "toolbar" }, tabs), body);
  draw();
}

let syncedNote = "";     // what the house router was told about a person just deleted, said after the list reloads

function drawPeople(main) {
  const canChange = can("profiles", true);
  const list = h("div", { class: "clips people" }, h("p", { class: "quiet" }, "Loading…"));
  const error = h("p", { class: "error", role: "alert" });
  const synced = h("p", { class: "ok", role: "status" });     // what the house router was told (people in step)

  async function load() {
    try {
      const everyone = await api("/profiles?all=true");
      if (syncedNote) { synced.textContent = syncedNote; syncedNote = ""; }
      const people = everyone.filter((p) => (p.kind || "person") === "person");
      if (!people.length) {
        list.replaceChildren(h("p", { class: "empty-state" }, "Nobody yet. People are added here, or " +
          "on the Learn page when you assign a clip to someone new."));
        return;
      }
      list.replaceChildren(...people.map((person) => personCard(person, canChange, load)));
    } catch (e) {
      list.replaceChildren(h("p", { class: "error" }, e.message));
    }
  }

  const parts = [
    h("p", { class: "quiet" }, "Everyone Oread knows by voice, learned from their clips on Learn (about " +
      ENOUGH_CLIPS + " to start).")];
  if (canChange) {
    const box = h("input", { id: "new-person", type: "text", autocomplete: "off", placeholder: "Their name" });
    parts.push(h("form", { class: "inline add-person", novalidate: true, onsubmit: async (event) => {
      event.preventDefault();
      error.textContent = "";
      const name = box.value.trim();
      if (!name) return;
      try {
        const made = await api("/profiles", { method: "POST", body: { name: name } });
        box.value = "";
        synced.textContent = made.wepwawet ? "The house router: " + made.wepwawet + "." : "";
        load();
      } catch (e) {
        error.textContent = e.message;
      }
    } }, h("label", { for: "new-person" }, "Add a person"),
      h("div", { class: "row" }, box, h("button", { class: "primary", type: "submit" }, "Add"))), error);
  }
  parts.push(synced, list);
  main.append(...parts);
  load();
}

// The patch for a device that hears its own speaker: the assistant's own voice, on the device's card (Settings,
// Devices), never on People (it's never a person). Learned from the text-to-speech voice the device answers in,
// then from her real voice as the device hears it (the router's echoes); or added by hand. voices: the
// assistants' profiles; learning: GET /assistant-voices (null: not in this version).
function herVoice(device, voices, learning, canChange, reload) {
  const error = h("p", { class: "error", role: "alert" });
  const learnNow = (again) => async () => {
    error.textContent = "";
    try {
      await api("/assistant-voices/learn", { method: "POST", body: { again } });
      const wait = async () => {
        const now = await api("/assistant-voices");
        if (now.learning) { setTimeout(wait, 2000); return; }
        reload();
      };
      setTimeout(wait, 2000);
      error.textContent = "";
      box.querySelectorAll("button.learn").forEach((b) => { b.disabled = true; });
      busy.hidden = false;
    } catch (e) {
      error.textContent = e.message;
    }
  };
  const remove = (v) => (event) => askFirst(event.currentTarget,
    "Delete " + v.name + "? " + (v.voice ? "Its lines go with it; the echoes go back to waiting." : "Its clips go back to waiting."),
    "Delete " + v.name, async () => {
      try { await api("/profiles/" + encodeURIComponent(v.name), { method: "DELETE" }); reload(); } catch (e) { error.textContent = e.message; }
    });
  const busy = h("p", { class: "status maybe", role: "status", hidden: !(learning && learning.learning) },
    "Learning now: Home Assistant is saying the lines\u2026");
  const first = (learning && learning.real_clips_first) || 5;
  const mine = voices.filter((v) => v.voice && (v.voice.devices || []).includes(device));
  const last = learning && learning.last;
  const learned = mine.map((v) => {
    const heard = v.clips - (v.made || 0);
    return h("li", {}, h("strong", {}, v.name), " ",
      heard >= first ? h("span", { class: "status known" }, "Knows its voice as this device hears it")
        : h("span", { class: "status maybe" }, "From the clean lines until " + first + " echoes (" + heard + " so far)"),
      h("span", { class: "quiet small" }, " " + (v.made || 0) + " lines from " + v.voice.engine + ", " + heard + " heard here"), " ",
      heard ? h("a", { class: "button-link", href: "#/learn?person=" + encodeURIComponent(v.name) }, "See clips") : null, " ",
      canChange ? h("button", { type: "button", class: "quiet-button", onclick: remove(v) }, "Delete") : null);
  });
  const byHand = voices.filter((v) => !v.voice);
  const name = h("input", { id: "new-voice-" + device, type: "text", autocomplete: "off", placeholder: "For example: Kitchen assistant" });
  const add = canChange ? h("form", { class: "inline", novalidate: true, onsubmit: async (event) => {
    event.preventDefault();
    error.textContent = "";
    if (!name.value.trim()) return;
    try {
      await api("/profiles", { method: "POST", body: { name: name.value.trim(), kind: "assistant" } });
      reload();
    } catch (e) {
      error.textContent = e.message;
    }
  } }, h("label", { for: "new-voice-" + device }, "Add an assistant's voice by hand"),
    h("div", { class: "row" }, name, h("button", { type: "submit" }, "Add the voice"))) : null;
  const box = h("div", { class: "her-voice" },
    h("h4", {}, "Assistant's voice"),
    learning ? h("p", { class: "quiet" }, "Learned for you while the switch is on (" + learning.lines + " lines from " +
      learning.lines_file + ", then its real voice through this device). ", guideMore("Patch: a device that hears itself")) : null,
    learned.length ? h("ul", { class: "rows" }, learned)
      : h("p", { class: "quiet" }, "Not learned for this device yet (the switch on, its Home Assistant device matched on Devices)."),
    last && last.error ? h("p", { class: "error" }, "The last try (" + when(last.at) + "): " + last.error) : null,
    busy,
    learning && canChange ? h("div", { class: "row" },
      h("button", { type: "button", class: "learn", disabled: learning.learning, onclick: learnNow(false) }, "Learn now"),
      h("button", { type: "button", class: "learn quiet-button", disabled: learning.learning, onclick: learnNow(true) }, "Learn them over")) : null,
    h("details", { class: "by-hand" }, h("summary", {}, "By hand (" + byHand.length + ")"),
      h("p", { class: "quiet" }, "A voice that isn't Home Assistant's text-to-speech: add it, then assign its clips to it on Learn."),
      byHand.length ? h("ul", { class: "rows" }, byHand.map((v) => h("li", {}, h("strong", {}, v.name), " ", learnedBadge(v.clips), " ",
        v.clips ? h("a", { class: "button-link", href: "#/learn?person=" + encodeURIComponent(v.name) }, "See clips") : null, " ",
        canChange ? h("button", { type: "button", class: "quiet-button", onclick: remove(v) }, "Delete") : null))) : null,
      add),
    error);
  return box;
}

function learnedBadge(clips) {
  if (clips === 0) return h("span", { class: "status unknown" }, "Not learned yet");
  if (clips < ENOUGH_CLIPS) return h("span", { class: "status maybe" }, "Learning: " + clips + " of " + ENOUGH_CLIPS);
  return h("span", { class: "status known" }, "Knows their voice");
}

function personCard(person, canChange, reload) {
  const card = h("article", { class: "card clip person", "data-person": person.name });
  const error = h("p", { class: "error", role: "alert" });
  const devicesLine = Object.entries(person.clips_by_device || {})
    .map(([d, n]) => d + " " + n).join(", ");
  const habits = h("div", { class: "habits" });

  function view() {
    const parts = [
      h("div", { class: "person-head" }, h("h2", {}, person.name), learnedBadge(person.clips)),
      h("p", { class: "quiet" }, person.clips === 1 ? "1 clip" : person.clips + " clips",
        devicesLine ? " \u00B7 " + devicesLine : ""),
      habits,
    ];
    const actions = h("div", { class: "row person-actions" });
    if (person.clips) {
      actions.append(h("a", { class: "button-link", href: "#/learn?person=" + encodeURIComponent(person.name) }, "See clips"));
    }
    if (canChange) {
      actions.append(h("button", { type: "button", onclick: rename }, "Rename"));
      actions.append(h("button", { type: "button", class: "quiet-button", onclick: remove }, "Delete"));
    }
    parts.push(actions, error);
    card.replaceChildren(...parts);
  }

  function rename() {
    const box = h("input", { type: "text", value: person.name, "aria-label": "New name for " + person.name, autocomplete: "off" });
    const save = h("button", { class: "primary", type: "submit" }, "Save");
    const cancel = h("button", { type: "button", onclick: view }, "Cancel");
    card.replaceChildren(h("form", { novalidate: true, onsubmit: async (event) => {
      event.preventDefault();
      error.textContent = "";
      try {
        const result = await api("/profiles/" + encodeURIComponent(person.name), { method: "PATCH", body: { new_name: box.value } });
        person.name = result.name;
        view();
        if (result.wepwawet) card.append(h("p", { class: "ok" }, "The house router: " + result.wepwawet + "."));
      } catch (e) {
        error.textContent = e.message;
      }
    } }, h("label", {}, "Rename " + person.name, box), h("div", { class: "row" }, save, cancel)), error);
    box.focus();
    box.select();
  }

  function remove(event) {
    const clips = person.clips === 1 ? "their 1 clip goes" : "their " + person.clips + " clips go";
    askFirst(event.currentTarget, "Delete " + person.name + "? Oread forgets their voice, and " + clips +
        " back to waiting on the Learn page.", "Delete " + person.name, async () => {
      try {
        const gone = await api("/profiles/" + encodeURIComponent(person.name), { method: "DELETE" });
        syncedNote = gone.wepwawet ? "The house router: " + gone.wepwawet + "." : "";
        reload();
      } catch (e) {
        error.textContent = e.message;
      }
    });
  }

  view();
  if (person.clips && can("phrases", false)) {
    api("/profiles/" + encodeURIComponent(person.name) + "/phrases?top=5").then((data) => {
      const top = (data.habits && data.habits.length ? data.habits : data.phrases).slice(0, 3);
      if (!top.length) return;
      habits.replaceChildren(h("p", { class: "quiet" }, data.habits && data.habits.length ? "Habit phrases: " : "Often says: ",
        top.map((x, i) => [i ? ", " : "", "\u201C" + x.phrase + "\u201D"])));
    }).catch(() => { /* phrases are a nice-to-have */ });
  }
  return card;
}

// ---------- People, Retrain: one person's voice on one device, after the device's sound changed ----------

function drawRetrain(main) {
  const canChange = can("profiles", true);
  const state = { person: "", device: "", ticked: new Set(), view: null, voices: false, people: [] };
  const sorts = { clips: { col: 2, down: true }, blind: { col: 1, down: true }, waiting: { col: 4, down: true } };
  const personSel = h("select", { id: "rt-person" }, h("option", { value: "" }, "Pick a person"));
  const deviceSel = h("select", { id: "rt-device" }, h("option", { value: "" }, "Pick a device"));
  const why = h("input", { id: "rt-why", type: "text", autocomplete: "off", maxlength: 500,
    placeholder: "For example: microphone gain up, noise suppression on", disabled: !canChange });
  const error = h("p", { class: "error", role: "alert" });
  const status = h("p", { class: "quiet", role: "status" });
  const record = h("div", {});
  const table = h("div", {});
  const waiting = h("div", {});
  const trial = h("div", {});

  Promise.all([api("/profiles"), api("/status")]).then(([people, st]) => {
    state.people = people.map((p) => p.name);
    people.forEach((p) => personSel.append(h("option", { value: p.name }, p.name)));
    st.devices.forEach((d) => deviceSel.append(h("option", { value: d.name }, d.name)));
    const q = hashParams();
    if (q.get("person")) personSel.value = q.get("person");
    if (q.get("device")) deviceSel.value = q.get("device");
    pick();
  }).catch((e) => { error.textContent = e.message; });

  function pick() {
    state.person = personSel.value;
    state.device = deviceSel.value;
    state.ticked = new Set();
    state.view = null;
    load();
  }
  personSel.addEventListener("change", pick);
  deviceSel.addEventListener("change", pick);

  async function load() {
    error.textContent = "";
    record.replaceChildren();
    trial.replaceChildren();
    waiting.replaceChildren();
    if (!state.person || !state.device) {
      table.replaceChildren(h("p", { class: "quiet" }, "Pick a person and a device to see the clips that train them there."));
      return;
    }
    table.replaceChildren(h("p", { class: "quiet" }, "Loading…"));
    try {
      const view = await api("/retrain?device=" + encodeURIComponent(state.device) + "&person=" + encodeURIComponent(state.person));
      state.view = view;
      if (view.pending && !state.ticked.size) view.pending.clips.forEach((id) => state.ticked.add(id));
      if (view.pending && !why.value) why.value = view.pending.why || "";
      drawRecord();
      drawClips();
      drawWaiting();
      if (view.pending) await drawTrial();
    } catch (e) {
      table.replaceChildren();
      error.textContent = e.message;
    }
  }

  function drawRecord() {
    const v = state.view;
    const parts = [];
    if (v.accepted) {
      parts.push(h("p", {}, h("span", { class: "status known" }, "In use"), " " + v.person + "'s own voiceprint on " +
        v.device + " since " + when(v.accepted.at) + ", from " + v.accepted.clips.length +
        " ticked clips plus any of theirs assigned there since.", v.accepted.why ? " Why: " + v.accepted.why : ""));
    } else {
      parts.push(h("p", { class: "quiet" }, v.device + " uses " + v.person + "'s voiceprint from every device: no " +
        "retrain accepted here yet." + (v.pending ? " A trial is waiting below: Accept or Reject." : "")));
    }
    if (v.period) parts.push(h("p", { class: "quiet small" }, v.device + "'s current settings period began " + when(v.period) + "."));
    record.replaceChildren(...parts);
  }

  function drawClips() {
    const v = state.view;
    if (!v.clips.length) {
      table.replaceChildren(h("p", { class: "empty-state" }, "No clips of " + v.person + " from " + v.device +
        " yet. Assign some from the waiting clips below."));
      return;
    }
    const count = h("span", { class: "quiet" });
    const recount = () => { count.textContent = state.ticked.size + " of " + v.clips.length + " ticked"; };
    const tick = (c) => {
      const box = h("input", { type: "checkbox", "aria-label": "Use this clip", checked: state.ticked.has(c.id),
        disabled: !canChange || !c.hand, title: c.hand ? null : "Assigned by a program, not a person",
        onchange: () => { if (box.checked) state.ticked.add(c.id); else state.ticked.delete(c.id); recount(); } });
      return box;
    };
    const takeBack = (c) => can("clips", true) ? h("button", { type: "button", onclick: (e) =>
      askFirst(e.currentTarget, "Back to waiting on Learn?", "Take back", async () => {
        try {
          await api("/clips/" + encodeURIComponent(c.id) + "/unassign", { method: "POST" });
          state.ticked.delete(c.id);
          load();
        } catch (err) { error.textContent = err.message; }
      }) }, "Take back") : "";
    const columns = [
      ["Use", (c) => (state.ticked.has(c.id) ? 1 : 0), tick],
      ["Play", (c) => c.audio_s, (c) => playButton("/clips/" + encodeURIComponent(c.id) + "/audio", c.audio_s)],
      ["When", (c) => c.time, (c) => when(c.time)],
      ["Words", (c) => c.transcript.toLowerCase(), (c) => h("p", { class: "words" }, "“" + c.transcript + "”")],
      ["Original", (c) => num(c.result && c.result.score), (c) => guessChip(c.result, "")],
    ];
    // the arrows compare with the person's own score when the clip was heard; they sort by how far it moved
    const then = (c) => scoreFor(c.result, v.person);
    if (v.pending) columns.push(["Trial", (c) => shift(c.trial_score, then(c)), (c) => moved(c.trial_score, then(c))]);
    columns.push(["New score", (c) => shift(c.new_score, then(c)), (c) => moved(c.new_score, then(c))], ["", null, takeBack]);
    const setAll = (fn) => { v.clips.forEach((c) => { if (c.hand && fn(c)) state.ticked.add(c.id); else state.ticked.delete(c.id); }); drawClips(); };
    const tools = canChange ? h("div", { class: "row person-actions" },
      h("button", { type: "button", onclick: () => setAll(() => true) }, "Tick all"),
      h("button", { type: "button", onclick: () => setAll(() => false) }, "Tick none"),
      v.period ? h("button", { type: "button", onclick: () => setAll((c) => c.time > v.period) }, "Tick since the last retrain") : "",
      count) : "";
    recount();
    const run = canChange ? h("button", { class: "primary", type: "button", onclick: async () => {
      error.textContent = "";
      if (!state.ticked.size) { error.textContent = "Tick the clips to retrain from first."; return; }
      status.textContent = "Retraining…";
      try {
        await api("/retrain", { method: "POST", body: { device: v.device, person: v.person,
          clips: Array.from(state.ticked), why: why.value } });
        status.textContent = "";
        await load();
      } catch (e) { status.textContent = ""; error.textContent = e.message; }
    } }, v.pending ? "Retrain again" : "Retrain") : "";
    table.replaceChildren(foldable(h("details", { class: "fold retrain-clips" },
      h("summary", {}, h("h3", {}, v.person + "'s clips on " + v.device + " (" + v.clips.length + ")")),
      tools, sortTable(columns, v.clips, sorts.clips, (c) => ({ class: "clip", "data-clip": c.id }))), "retrain:clips"),
      canChange ? h("div", { class: "row person-actions" }, run) : "");
  }

  // the device's clips nobody is assigned to, closest to the person first (#6): assigned here, without the
  // Learn page. The assistants' own voices crowd the women's (Nora's clips and Wren's voice are close), so a
  // clip whose closest voice is an assistant's is hidden unless the person is one of its two closest
  function drawWaiting() {
    const v = state.view;
    const voices = new Set(v.assistants || []);
    const named = (n) => (voices.has(n) ? n + " (assistant's voice)" : n);
    const near = (c) => (c.closest || []).some((x) => x.name === v.person);
    const herVoice = (c) => voices.has(((c.closest || [])[0] || {}).name) && !near(c);
    const rows = (v.waiting || []).filter((c) => state.voices || !herVoice(c));
    const hidden = (v.waiting || []).length - rows.length;
    const assign = (c) => {
      if (!can("clips", true)) return "";
      // the choice, not always the person being retrained: the closest first, then the assistants' voices,
      // everyone else, and not a person (noise, the TV: discarded)
      const order = [v.person].concat((c.closest || []).map((x) => x.name), Array.from(voices), state.people);
      const pick = h("select", { "aria-label": "Assign this clip to" },
        Array.from(new Set(order)).map((n) => h("option", { value: n }, named(n))),
        h("option", { value: "" }, "Not a person (discard it)"));
      const go = h("button", { type: "button", onclick: (e) => {
        const who = pick.value;
        const run = async () => {
          try {
            if (who) await api("/clips/" + encodeURIComponent(c.id) + "/assign", { method: "POST", body: { profile: who } });
            else await api("/clips/" + encodeURIComponent(c.id), { method: "DELETE" });
            load();
          } catch (err) { error.textContent = err.message; }
        };
        if (who) run(); else askFirst(e.currentTarget, "Discard this clip?", "Discard", run);
      } }, "Assign");
      return h("span", { class: "row assign" }, pick, go);
    };
    const columns = [
      ["Play", (c) => c.audio_s, (c) => playButton("/clips/" + encodeURIComponent(c.id) + "/audio", c.audio_s)],
      ["When", (c) => c.time, (c) => when(c.time)],
      ["Words", (c) => c.transcript.toLowerCase(), (c) => h("p", { class: "words" }, "\u201C" + c.transcript + "\u201D")],
      ["When heard", (c) => num(c.result && c.result.score), (c) => guessChip(c.result, "")],
      [v.person + "'s score", (c) => (c.person_score === null ? -1 : c.person_score),
        (c) => (c.person_score === null ? "" : c.person_score.toFixed(2))],
      ["Closest now", (c) => ((c.closest || [])[0] || {}).name || "",
        (c) => (c.closest || []).map((x) => named(x.name) + " " + x.score.toFixed(2)).join(", ")],
      ["", null, assign],
    ];
    const show = h("label", { class: "check" }, h("input", { type: "checkbox", checked: state.voices,
      onchange: (e) => { state.voices = e.target.checked; drawWaiting(); } }),
      " Show the clips closest to an assistant's own voice" + (hidden ? " (" + hidden + " hidden)" : ""));
    waiting.replaceChildren(foldable(h("details", { class: "fold retrain-waiting" },
      h("summary", {}, h("h3", {}, "Waiting on " + v.device + ", closest to " + v.person + " first (" + rows.length + ")")),
      h("p", { class: "quiet" }, "Clips nobody is assigned to yet. Play one, pick who it is, and Assign: it joins " +
        "that person's clips above when it's " + v.person + ". A clip close to an assistant's voice may be an echo of her, " +
        "or someone whose voice is near hers."),
      voices.size ? show : "",
      rows.length ? sortTable(columns, rows, sorts.waiting, (c) => ({ class: "clip", "data-clip": c.id }))
        : h("p", { class: "empty-state" }, "Nothing waiting on " + v.device + ".")), "retrain:waiting"));
  }

  // the trial in one word, judged on the new sound only, with the numbers behind it
  function overall(b, person) {
    const t = b.counts.since;
    const ve = b.verdict;
    const words = { "better": "Better", "worse": "Worse", "mixed": "Mixed", "no change": "No change" };
    const pair = (a, z) => a + " \u2192 " + z;
    return h("div", { class: "verdict " + ve.verdict.replace(" ", "-") },
      h("p", {}, h("strong", {}, "Overall: " + words[ve.verdict]), " (on the new sound, today \u2192 with the trial)"),
      h("ul", {},
        h("li", {}, person + "'s own clips named " + person + ": " + pair(t.theirs_today, t.theirs_trial) + " of " + t.theirs_all),
        h("li", {}, "Other people's clips named " + person + " (wrongly): " + pair(t.others_today, t.others_trial)),
        h("li", {}, "Waiting clips named " + person + ": " + pair(t.waiting_today, t.waiting_trial)),
        ve.average_today === null ? null : h("li", {}, person + "'s average score on their own clips: ",
          ve.average_today.toFixed(2) + " \u2192 ", moved(ve.average_trial, ve.average_today))));
  }

  async function drawTrial() {
    const v = state.view;
    const b = await api("/retrain/blind?device=" + encodeURIComponent(v.device) + "&person=" + encodeURIComponent(v.person));
    const c = b.counts;
    const named = (t, group) => t[group + "_today"] + " of " + t[group + "_all"] + " today, " +
      t[group + "_trial"] + " with the trial";
    const tally = (title, t) => h("div", {}, h("h3", {}, title), h("ul", {},
      h("li", {}, v.person + "'s clips named " + v.person + ": " + named(t, "theirs")),
      h("li", {}, "Other people's clips named " + v.person + ": " + named(t, "others")),
      h("li", {}, "Waiting clips named " + v.person + ": " + named(t, "waiting"))));
    const changed = (r) => (r.today.speaker || "") !== (r.trial.speaker || "");
    // how the trial changes who a clip names: only a named person counts (maybe and unknown name nobody)
    const change = (r) => {
      if (!changed(r)) return "";
      if (!r.today.speaker) return "now names " + r.trial.speaker;
      if (!r.trial.speaker) return "no longer names " + r.today.speaker;
      return r.today.speaker + " \u2192 " + r.trial.speaker;
    };
    const kinds = { now: 0, gone: 0, other: 0 };
    b.clips.filter(changed).forEach((r) => {
      kinds[!r.today.speaker ? "now" : (!r.trial.speaker ? "gone" : "other")] += 1;
    });
    const columns = [
      ["Play", (r) => r.audio_s, (r) => playButton("/clips/" + encodeURIComponent(r.id) + "/audio", r.audio_s)],
      ["When", (r) => r.time, (r) => when(r.time)],
      ["Words", (r) => r.transcript.toLowerCase(), (r) => h("p", { class: "words" }, "“" + r.transcript + "”")],
      ["Assigned to", (r) => (r.profile || "").toLowerCase(), (r) => r.profile || h("span", { class: "quiet" }, "waiting")],
      ["Original", (r) => num(r.result && r.result.score), (r) => guessChip(r.result, "")],
      ["Today", (r) => num(r.today.score), (r) => guessChip(r.today, "")],
      ["With the trial", (r) => num(r.trial.score), (r) => guessChip(r.trial, "")],
      [v.person + "'s score", (r) => shift(r.trial.person_score, r.today.person_score),
        (r) => moved(r.trial.person_score, r.today.person_score)],
      ["Change", (r) => change(r), change],
    ];
    const accept = h("button", { class: "primary", type: "button", onclick: async () => {
      error.textContent = "";
      try {
        await api("/retrain/accept", { method: "POST", body: { device: v.device, person: v.person } });
        state.ticked = new Set();
        why.value = "";
        await load();
        status.textContent = "Accepted: " + v.person + "'s own voiceprint decides on " + v.device + " now.";
      } catch (e) { error.textContent = e.message; }
    } }, "Accept");
    const reject = h("button", { type: "button", onclick: (e) =>
      askFirst(e.currentTarget, "Reject the trial? Nothing of it is kept.", "Reject", async () => {
        try {
          await api("/retrain/reject", { method: "POST", body: { device: v.device, person: v.person } });
          state.ticked = new Set();
          await load();
          status.textContent = "Rejected; nothing changed.";
        } catch (err) { error.textContent = err.message; }
      }) }, "Reject");
    trial.replaceChildren(h("section", { class: "card panel trial" },
      h("h2", {}, "Blind test"),
      h("p", { class: "quiet" }, "A trial from " + v.pending.clips.length + " clips, made " + when(v.pending.at) +
        (v.pending.by ? " by " + v.pending.by : "") + (v.pending.why ? ". Why: " + v.pending.why : "") +
        ". Until you accept, today's voice ID decides; live requests on " + v.device + " note what the trial would say. " +
        "Every clip " + v.device + " heard, whoever it's assigned to, is scored as today and with the trial " +
        "(a ticked clip without itself)."),
      overall(b, v.person),
      tally("Since " + when(b.since) + " (the oldest ticked clip): the new sound", c.since),
      tally("Before that: the old sound, which a trial for the new sound is expected to lose", c.before),
      canChange ? h("div", { class: "row person-actions" }, accept, reject) : "",
      foldable(h("details", { class: "fold blind-clips" },
        h("summary", {}, h("h3", {}, "All " + b.clips.length + " clips " + v.device + " heard")),
        h("p", { class: "quiet" }, "A clip names a person when Oread calls them known; maybe and unknown name nobody. " +
          "With the trial, " + kinds.now + " would name someone they don't name today, " + kinds.gone +
          " would no longer name anyone, and " + kinds.other + " would name someone else. Those rows are marked; " +
          "the rest name the same as today (their scores may still move)."),
        sortTable(columns, b.clips, sorts.blind, (r) => ({ class: changed(r) ? "clip changed" : "clip", "data-clip": r.id }))),
      "retrain:blind")));
  }

  main.append(
    h("p", { class: "quiet" }, "A device's sound changed and a voice stopped matching? Retrain it there from the clips heard since. ",
      guideMore("When a device's sound changes: Retrain")),
    h("div", { class: "knobs retrain-pick" },
      field("Person", personSel), field("Device", deviceSel),
      field("Why (optional)", why, "Kept with the retrain, as the record of what changed.")),
    error, status, record, table, waiting, trial);
}

// ---------- Devices: what listens, and on which port ----------

function renderDevices(main) {
  const canChange = can("devices", true);
  const server = location.hostname;
  const intro = h("div", {});
  const list = h("div", { class: "clips devices" }, h("p", { class: "quiet" }, "Loading…"));
  const addArea = h("div", {});
  const typesArea = h("div", {});
  let addForm = null;

  async function load() {
    try {
      const [data, choices] = await Promise.all([api("/devices"), api("/models")]);
      data.choices = choices;
      intro.replaceChildren(
        h("p", { class: "quiet" }, "Each listening device has its own port: that's how Oread knows which one it's hearing. ",
          guideMore("9. Connect a client")),
        h("div", { class: "card panel where" },
          h("h2", {}, "Where the ports go"),
          h("p", {}, "In your client's speech-to-text settings (Home Assistant's Wyoming integration, for " +
            "example), use this server's address, ", h("strong", { class: "mono" }, server),
            ", and the port of the device that will be listening. One connection per device."),
          h("p", { class: "quiet" }, h("small", {}, "Oread can use ports " + data.port_range[0] + " to " +
            data.port_range[1] + " (" + (location.port || "443") + " is its pages). Remember to permit each client on Connections."))));
      list.replaceChildren(...data.devices.map((d) => deviceCard(d, data, server, canChange, load)));
      if (canChange && !addForm) {   // once, so its message stays; its type list is refreshed below
        addForm = addDeviceForm(data, load);
        addArea.append(addForm.el);
      }
      if (addForm) addForm.setTypes(data.types);
      typesArea.replaceChildren(typesPanel(data, canChange, load));

    } catch (e) {
      list.replaceChildren(h("p", { class: "error" }, e.message));
    }
  }
  const comparePanel = h("section", { class: "card panel compare", id: "compare", hidden: true });
  main.append(h("h1", {}, "Devices"), intro, comparePanel, list, addArea, typesArea);
  load();
  if (can("compare", false)) {
    api("/compare").then((job) => {
      if (job.state !== "none") showCompare(comparePanel, job.device, null, job, load);
    }).catch(() => { /* nothing to show */ });
  }
  window.oreadCompare = (device, data) => showCompare(comparePanel, device, data, null, load);
}

function copyButton(text, label) {
  const button = h("button", { type: "button", class: "copy", "aria-label": "Copy " + text }, label || "Copy");
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = "Copied";
    } catch (e) {
      button.textContent = text;   // no clipboard: show it to copy by hand
    }
    setTimeout(() => { button.textContent = label || "Copy"; }, 2000);
  });
  return button;
}

function deviceCard(device, data, server, canChange, reload) {
  const card = h("article", { class: "card clip device", "data-device": device.name });
  const error = h("p", { class: "error", role: "alert" });

  function view() {
    const parts = [
      h("div", { class: "person-head" }, h("h2", {}, device.name),
        device.type ? h("span", { class: "badge", title: "Type: " + device.type }, typeLabel(data.types, device.type)) : null),
      h("div", { class: "port-line" },
        h("span", { class: "quiet" }, "Port"), h("strong", { class: "port mono" }, String(device.port)),
        copyButton(server + ":" + device.port, "Copy address")),
      h("p", { class: "quiet small" }, "Speech: " + modelLabel(data.choices.speech, device.stt_model, device.stt_from) +
        " \u00B7 Voice: " + modelLabel(data.choices.voice, device.speaker_model, device.speaker_from)),
      h("p", { class: "quiet small" }, device.publish_speaker
        ? "Tells your voice assistant who spoke (if one is set up on Connections)."
        : "Doesn't report who spoke (the intent router, if used, does that)."),
    ];
    if (canChange) {
      parts.push(h("div", { class: "row person-actions" },
        h("button", { type: "button", onclick: rename }, "Rename"),
        h("a", { class: "button-link", href: "#/settings?tab=devices&device=" + encodeURIComponent(device.name) }, "Settings"),
        can("compare", true) ? h("button", { type: "button", onclick: () => window.oreadCompare(device.name, data) }, "Compare") : null,
        data.devices.length > 1 ? h("button", { type: "button", class: "quiet-button", onclick: remove }, "Remove") : null));
    }
    parts.push(error);
    card.replaceChildren(...parts);
  }

  function rename() {
    const box = h("input", { type: "text", value: device.name, "aria-label": "New name for " + device.name,
      autocomplete: "off", autocapitalize: "none", spellcheck: "false" });
    card.replaceChildren(h("form", { novalidate: true, onsubmit: async (event) => {
      event.preventDefault();
      error.textContent = "";
      try {
        const result = await api("/devices/" + encodeURIComponent(device.name), { method: "PATCH", body: { new_name: box.value } });
        device.name = result.to;
        view();
      } catch (e) {
        error.textContent = e.message;
      }
    } }, h("label", {}, "Rename " + device.name, box),
      h("p", { class: "quiet small" }, "Lowercase letters, digits, - or _. The port stays the same, so " +
        "your client needs no change."),
      h("div", { class: "row" }, h("button", { class: "primary", type: "submit" }, "Save"),
        h("button", { type: "button", onclick: view }, "Cancel"))), error);
    box.focus();
    box.select();
  }

  function remove(event) {
    askFirst(event.currentTarget, "Remove " + device.name + "? Port " + device.port + " stops listening at once, so " +
        "anything still sending to it gets no answer. Its clips are kept.", "Remove " + device.name, async () => {
      try {
        await api("/devices/" + encodeURIComponent(device.name), { method: "DELETE" });
        reload();
      } catch (e) {
        error.textContent = e.message;
      }
    });
  }

  view();
  return card;
}

// ---------- Compare models on a device's own clips (only when asked) ----------

let comparePoll = null;

function showCompare(panel, deviceName, data, job, reloadDevices) {
  panel.hidden = false;
  if (comparePoll) { clearTimeout(comparePoll); comparePoll = null; }
  let running = false;
  // X: a running comparison is stopped (after asking); a finished one is put away for good
  const close = async (event) => {
    if (running) {
      // stopping: the results so far come back on the next check, ready to read or put away
      askFirst(event.currentTarget, "Stop this comparison? You'll see the clips it got through.", "Stop",
        () => api("/compare", { method: "DELETE" }).catch(() => {}));
      return;
    }
    if (comparePoll) { clearTimeout(comparePoll); comparePoll = null; }
    await api("/compare", { method: "DELETE" }).catch(() => {});
    panel.hidden = true;
    panel.replaceChildren();
  };
  const body = h("div", {});
  panel.replaceChildren(h("div", { class: "person-head" }, h("h2", {}, "Compare models: " + deviceName),
    h("button", { type: "button", class: "discard", "aria-label": "Close the comparison", onclick: close }, "\u2715")), body);
  panel.scrollIntoView({ behavior: "smooth", block: "start" });

  const setup = async () => {
    const devicesData = data || await api("/devices").then(async (d) => { d.choices = await api("/models"); return d; });
    const device = devicesData.devices.find((d) => d.name === deviceName);
    let kind = "speech";
    const modelBox = h("div", {});
    const drawModels = () => {
      const list = kind === "speech" ? devicesData.choices.speech : devicesData.choices.voice;
      const current = kind === "speech" ? device.stt_model : device.speaker_model;
      const options = list.filter((m) => kind === "voice" || m.name !== current);
      const select = h("select", { id: "compare-model" }, options.map((m) =>
        h("option", { value: m.name }, m.label + (m.name === current ? " (in use now)" : ""))));
      modelBox.replaceChildren(field("Model to try", select, kind === "speech"
        ? "It listens to " + deviceName + "'s newest clips; you'll see every clip where its words differ."
        : "Scored on the clips assigned to people, against " + deviceName + "'s current voice model."));
    };
    const kinds = h("div", { class: "choices", role: "radiogroup", "aria-label": "What to compare" },
      [["speech", "The words (speech model)"], ["voice", "Who spoke (voice model)"]].map(([v, label]) =>
        h("label", {}, h("input", { type: "radio", name: "compare-kind", value: v, checked: v === kind,
          onchange: () => { kind = v; drawModels(); } }), label)));
    const count = h("select", { id: "compare-limit" }, [25, 50, 100].map((n) => h("option", { value: n, selected: n === 50 }, n + " clips")));
    const error = h("p", { class: "error", role: "alert" });
    drawModels();
    body.replaceChildren(
      h("p", { class: "quiet" }, "Runs only now, on clips Oread already has, one at a time, leaving room for live requests."),
      kinds, modelBox, field("How many of the newest clips", count), error,
      h("button", { class: "primary", type: "button", onclick: async () => {
        error.textContent = "";
        try {
          const started = await api("/devices/" + encodeURIComponent(deviceName) + "/compare", { method: "POST",
            body: { kind: kind, model: document.getElementById("compare-model").value, limit: Number(count.value) } });
          follow(started);
        } catch (e) {
          error.textContent = e.message;
        }
      } }, "Start comparing"));
  };

  const follow = (state) => {
    running = ["starting", "loading", "running"].indexOf(state.state) >= 0;
    if (running) {
      const pct = state.total ? Math.round(100 * state.done / state.total) : 0;
      body.replaceChildren(
        h("p", {}, (state.state === "loading" ? "Loading " + state.model_label + "\u2026 " : "Comparing " +
          state.model_label + " with " + state.current_label + ": ") +
          (state.total ? state.done + " of " + state.total + " clips" : "")),
        state.note ? h("p", { class: "quiet" }, state.note) : "",
        h("div", { class: "meter wide", role: "progressbar", "aria-valuenow": pct, "aria-valuemin": 0, "aria-valuemax": 100 },
          h("span", { style: null })),
        h("button", { type: "button", onclick: close }, "Cancel"));
      body.querySelector(".meter span").setAttribute("data-pct", pct);
      body.querySelector(".meter span").style.width = pct + "%";
      comparePoll = setTimeout(() => api("/compare").then(follow).catch(() => {}), 1000);
      return;
    }
    drawResults(state);
  };

  const useIt = (state) => h("button", { class: "primary", type: "button", onclick: async () => {
    const change = {};
    change[state.kind === "speech" ? "stt_model" : "speaker_model"] = state.model;
    await api("/devices/" + encodeURIComponent(state.device), { method: "PATCH", body: change });
    await api("/compare", { method: "DELETE" }).catch(() => {});   // done with it: don't show it again
    reloadDevices();
    panel.hidden = true;
    panel.replaceChildren();
  } }, "Use " + state.model_label + " for " + state.device);

  const drawResults = (state) => {
    const again = h("button", { type: "button", onclick: () => { data = null; setup(); } }, "Compare again");
    const finished = h("button", { type: "button", class: "quiet-button", onclick: close }, "Done");
    if (state.state === "failed") {
      body.replaceChildren(h("p", { class: "error" }, state.note || "The comparison stopped."),
        h("div", { class: "row" }, again, finished));
      return;
    }
    const parts = [];
    if (state.state === "cancelled") parts.push(h("p", { class: "quiet" }, "Cancelled; results so far:"));
    if (state.kind === "voice") {
      parts.push(h("p", {}, "Tested on " + state.tested + " of " + state.device + "'s assigned clips, " +
        state.people + (state.people === 1 ? " person" : " people") + ". For each clip, the voices were learned " +
        "from every other assigned clip, then the model was asked who it was."));
      parts.push(h("div", { class: "table-wrap" }, h("table", { class: "results" },
        h("thead", {}, h("tr", {}, ["Model", "Right", "Maybe", "Unknown", "Wrong person", "Match: right person",
          "Match: closest other"].map((t) => h("th", {}, t)))),
        h("tbody", {}, state.results.map((r) => h("tr", {},
          h("td", {}, r.label), h("td", {}, String(r.right)), h("td", {}, String(r.maybe)),
          h("td", {}, String(r.unknown)), h("td", { class: r.wrong ? "bad" : "" }, String(r.wrong)),
          h("td", {}, r.average_right_score === null ? "-" : r.average_right_score.toFixed(2)),
          h("td", {}, r.average_closest_other === null ? "-" : r.average_closest_other.toFixed(2))))))));
      parts.push(h("p", { class: "quiet small" }, "\u201CWrong person\u201D is the one to avoid; the wider the gap between the " +
        "match columns, the better. ", guideMore("Choosing models (optional)")));
      const candidate = state.results.find((r) => r.model === state.model);
      if (candidate && state.model !== state.current) parts.push(h("div", { class: "row" }, useIt(state), again, finished));
      else parts.push(h("div", { class: "row" }, again, finished));
    } else {
      const different = state.different || [];
      parts.push(h("p", {}, state.model_label + " heard the same words as " + state.current_label + " on " +
        state.same + " of " + state.done + " clips, and different words on " + different.length + "."));
      if (state.seconds_per_second_of_speech) {
        parts.push(h("p", { class: "quiet small" }, state.model_label + " took about " +
          state.seconds_per_second_of_speech.toFixed(2) + " s per second of speech here, on one thread (in use it gets more)."));
      }
      const tally = h("p", { class: "tally", role: "status" });
      const drawTally = (j) => {
        const t = j.judged || { current: 0, candidate: 0, neither: 0 };
        tally.textContent = "Your verdicts so far: " + state.current_label + " right " + t.current + ", " +
          state.model_label + " right " + t.candidate + ", neither " + t.neither + ".";
      };
      drawTally(state);
      if (different.length) {
        parts.push(h("p", { class: "quiet" }, "Listen to each, then say which words were right."), tally);
        parts.push(h("div", { class: "clips compare-clips" }, different.map((d) => {
          const buttons = [["current", state.current_label + " was right"], ["candidate", state.model_label + " was right"],
            ["neither", "Neither"]].map(([v, label]) => h("button", { type: "button", "aria-pressed": d.judged === v ? "true" : "false",
            onclick: async (event) => {
              const choice = d.judged === v ? "" : v;
              const j = await api("/compare/judge", { method: "POST", body: { clip: d.clip, choice: choice } });
              d.judged = choice || null;
              event.target.parentNode.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
              if (choice) event.target.setAttribute("aria-pressed", "true");
              drawTally(j);
            } }, label));
          return h("article", { class: "card clip" },
            h("div", { class: "clip-head" }, playButton("/clips/" + encodeURIComponent(d.clip) + "/audio", d.audio_s),
              h("div", { class: "clip-meta" }, h("span", {}, when(d.time)), h("span", { class: "quiet" }, d.audio_s.toFixed(1) + " s"))),
            h("p", { class: "said" }, h("span", { class: "quiet small" }, state.current_label + " (at the time)"), h("br", {}), d.current),
            h("p", { class: "said" }, h("span", { class: "quiet small" }, state.model_label), h("br", {}), d.candidate || "(nothing)"),
            h("div", { class: "row verdict" }, buttons));
        })));
      }
      parts.push(h("div", { class: "row" }, useIt(state), again, finished));
    }
    body.replaceChildren(...parts);
  };

  if (job) follow(job); else setup();
}

// where a device's model comes from: chosen for the device, set by its type, or the default
function modelLabel(list, name, from) {
  const m = list.find((x) => x.name === name);
  const label = m ? m.label : name;
  if (from === "device") return label;
  return label + (from === "type" ? " (from its type)" : " (default)");
}

function typeLabel(types, name) {
  const t = types.find((x) => x.name === name);
  return t ? t.label : name;
}

// A model dropdown: the default first, then each model with what it costs. Under it, what
// the choice means: extra memory if no other device uses that model yet, a download the first time.
// fromType: the model the device's type starts it on, if any (then that is its default).
function modelSelect(label, list, current, fromType) {
  const typeModel = fromType ? list.find((m) => m.name === fromType) : null;
  const fallback = typeModel || list.find((m) => m.default);
  const select = h("select", {},
    h("option", { value: "", selected: current === "" }, (typeModel ? "From its type (" : "Default (") +
      (fallback ? fallback.label : "settings") + ")"),
    list.map((m) => h("option", { value: m.name, selected: m.name === current },
      m.label + " \u00B7 about " + m.memory_mb + " MB")));
  const note = h("p", { class: "quiet small model-note" });
  const explain = () => {
    const m = list.find((x) => x.name === select.value) || fallback;
    if (!m) { note.textContent = ""; return; }
    const parts = [m.notes];
    if (!m.used_by.length && !m.default) {
      parts.push("No device uses it yet, so it takes about " + m.memory_mb + " MB more memory.");
    }
    if (!m.downloaded) parts.push("It's downloaded the first time, which can take a few minutes.");
    note.textContent = parts.join(" ");
  };
  select.addEventListener("change", explain);
  explain();
  const id = "model-" + label.toLowerCase().replace(/[^a-z]+/g, "-") + "-" + Math.random().toString(36).slice(2, 7);
  select.id = id;
  return { select: select, field: h("div", { class: "field" }, h("label", { for: id }, label), select, note) };
}

function modelGuide() {
  return h("details", { class: "tips card", id: "model-guide" },
    h("summary", {}, "Choosing models"),
    h("ul", {},
      h("li", {}, h("strong", {}, "Most people keep the defaults. "),
        "They did best in our tests. A different microphone or room can change that, so other models are here to try."),
      h("li", {}, h("strong", {}, "Memory: each different model is loaded once. "),
        "Devices on the same model share it; each other model adds its size (in the list)."),
      h("li", {}, h("strong", {}, "Speed: slower models keep a slot busy longer. "),
        "A slow model makes other devices wait more often; Stats shows the waits."),
      h("li", {}, h("strong", {}, "Compare before you switch. "),
        "Compare, on each device, tests a model on that device's own clips."),
      h("li", {}, h("strong", {}, "Changing the voice model "),
        "makes Oread relearn every voice from the clips already assigned, by itself; nothing to redo.")));
}

function addDeviceForm(data, reload) {
  const name = h("input", { id: "new-device", type: "text", autocomplete: "off", autocapitalize: "none",
    spellcheck: "false", placeholder: "for example kitchen" });
  const type = h("select", { id: "new-device-type" });
  const setTypes = (types) => {
    const was = type.value;
    type.replaceChildren(h("option", { value: "" }, "No type"),
      ...types.map((t) => h("option", { value: t.name, selected: t.name === was }, t.label)));
  };
  setTypes(data.types);
  const error = h("p", { class: "error", role: "alert" });
  const done = h("p", { class: "ok", role: "status" });
  const el = h("section", { class: "card panel" }, h("h2", {}, "Add a device"),
    h("form", { novalidate: true, onsubmit: async (event) => {
      event.preventDefault();
      error.textContent = "";
      done.textContent = "";
      try {
        const added = await api("/devices", { method: "POST",
          body: { name: name.value, type: type.value || null } });
        done.textContent = added.name + " is listening on port " + added.port + ".";
        name.value = "";
        reload();
      } catch (e) {
        error.textContent = e.message;
      }
    } },
      field("Name", name, "Lowercase letters, digits, - or _. Usually where it is, or what it is."),
      field("Type", type, "Devices of one type start from the same models (all Voice PEs, for example). " +
        "Don't see yours? Add it under Device types below."),
      error, done,
      h("button", { class: "primary", type: "submit" }, "Add device")),
    h("p", { class: "quiet small" }, "It gets the next free port and listens at once; its models are on Settings, Devices."));
  return { el: el, setTypes: setTypes };
}

// ---------- Device types: kinds of device, and the models each starts on ----------

function typesPanel(data, canChange, reload) {
  const rows = h("ul", { class: "rows types" });
  const modelName = (list, name) => {
    if (!name) return "default";
    const m = list.find((x) => x.name === name);
    return m ? m.label : name;
  };
  data.types.forEach((t) => {
    const error = h("p", { class: "error", role: "alert" });
    const li = h("li", { "data-type": t.name });
    const view = () => {
      const used = t.used_by.length;
      li.replaceChildren(
        h("div", {},
          h("strong", {}, t.label), " ", h("span", { class: "quiet small mono" }, t.name),
          t.note ? h("p", { class: "quiet small" }, t.note) : null,
          h("p", { class: "quiet small" }, "Starts on speech: " + modelName(data.choices.speech, t.stt_model) +
            " \u00B7 voice: " + modelName(data.choices.voice, t.speaker_model) + " \u00B7 " +
            (used ? "used by " + t.used_by.join(", ") : "no device uses it")),
          error),
        canChange ? h("div", { class: "row person-actions" },
          h("button", { type: "button", onclick: relabel }, "Rename"),
          h("button", { type: "button", class: "quiet-button", disabled: used > 0,
            title: used ? "Still used by " + t.used_by.join(", ") : null, onclick: remove }, "Remove")) : "");
    };
    const relabel = () => {
      const label = h("input", { type: "text", value: t.label, "aria-label": "Label for " + t.name, maxlength: 60 });
      const note = h("input", { type: "text", value: t.note, "aria-label": "Note for " + t.name, maxlength: 200,
        placeholder: "Note (optional)" });
      li.replaceChildren(h("form", { novalidate: true, class: "wide", onsubmit: async (event) => {
        event.preventDefault();
        error.textContent = "";
        try {
          await api("/device-types/" + encodeURIComponent(t.name), { method: "PATCH",
            body: { label: label.value, note: note.value } });
          reload();
        } catch (e) {
          error.textContent = e.message;
        }
      } }, h("p", { class: "quiet small" }, "The short name, " + t.name + ", stays the same, so its devices keep it."),
        h("div", { class: "row" }, label), h("div", { class: "row" }, note), error,
        h("div", { class: "row" }, h("button", { class: "primary", type: "submit" }, "Save"),
          h("button", { type: "button", onclick: view }, "Cancel"))));
      label.focus();
      label.select();
    };
    const remove = (event) => askFirst(event.currentTarget, "Remove the type " + t.label + "? No device uses it.",
      "Remove", async () => {
        try {
          await api("/device-types/" + encodeURIComponent(t.name), { method: "DELETE" });
          reload();
        } catch (e) {
          error.textContent = e.message;
        }
      });
    view();
    rows.append(li);
  });
  return h("section", { class: "card panel", id: "device-types" },
    h("h2", {}, "Device types"),
    h("p", { class: "quiet" }, "Kinds of listening device: a type starts its devices on its models. ",
      guideMore("Device types (optional)")),
    data.types.length ? rows : h("p", { class: "empty-state" }, "No device types yet."),
    canChange ? addTypeForm(data, reload) : null);
}

function addTypeForm(data, reload) {
  const name = h("input", { id: "new-type-name", type: "text", autocomplete: "off", autocapitalize: "none",
    spellcheck: "false", placeholder: "for example kitchen-speaker" });
  const label = h("input", { id: "new-type-label", type: "text", maxlength: 60, placeholder: "for example Kitchen speaker" });
  const note = h("input", { id: "new-type-note", type: "text", maxlength: 200 });
  const speech = modelSelect("Speech model", data.choices.speech, "");
  const voice = modelSelect("Voice model", data.choices.voice, "");
  const error = h("p", { class: "error", role: "alert" });
  return h("details", { class: "add-type" }, h("summary", {}, "Add a type"),
    h("form", { novalidate: true, onsubmit: async (event) => {
      event.preventDefault();
      error.textContent = "";
      try {
        await api("/device-types", { method: "POST", body: { name: name.value, label: label.value, note: note.value,
          stt_model: speech.select.value || null, speaker_model: voice.select.value || null } });
        reload();
      } catch (e) {
        error.textContent = e.message;
      }
    } },
      field("Label", label, "What people see, like \u201CKitchen speaker\u201D or \u201CRaspberry Pi satellite\u201D."),
      field("Short name", name, "Lowercase letters, digits, - or _. Devices and the API use it; it can't change later."),
      field("Note", note, "Optional: what it is or where it's used."),
      speech.field, voice.field,
      error,
      h("button", { class: "primary", type: "submit" }, "Add type")));
}

// ---------- Settings: each model's own settings, and the defaults ----------

function renderSettings(main) {
  const tabsAllowed = [["models", "Models"], ["devices", "Devices"]];
  if (can("sample", false)) tabsAllowed.push(["sample", "Sample household"]);
  let current = hashParams().get("tab") || "models";
  const tabs = h("div", { class: "tabs", role: "tablist", "aria-label": "Which settings" });
  const body = h("div", {});
  const draw = () => {
    tabs.replaceChildren(...tabsAllowed.map(([id, label]) => h("button", { type: "button", role: "tab",
      "aria-selected": id === current ? "true" : "false",
      onclick: () => { current = id; history.replaceState(null, "", "#/settings?tab=" + id); draw(); } }, label)));
    body.replaceChildren(h("p", { class: "quiet" }, "Loading…"));
    const drawTab = { devices: drawDeviceSettings, sample: drawSample }[current] || drawModels;
    drawTab(body).catch((e) =>
      body.replaceChildren(h("p", { class: "error" }, e.message)));
  };
  main.append(h("h1", {}, "Settings"), h("div", { class: "toolbar" }, tabs), body);
  draw();
}

// ---------- Settings, Sample household: three volunteers' voices to try Oread on ----------

async function drawSample(body) {
  const d = await api("/sample");
  const error = h("p", { class: "error", role: "alert" });
  const canChange = can("sample", true);
  const run = async (button, busyText, method) => {
    error.textContent = "";
    button.disabled = true;
    button.textContent = busyText;
    try { await api("/sample", { method: method }); } catch (e) { error.textContent = e.message; }
    drawSample(body);
  };
  const buttons = [];
  if (canChange && !d.added) {
    const add = h("button", { type: "button", class: "primary", disabled: d.busy || !d.available,
      onclick: () => run(add, "Adding\u2026 (about a minute)", "POST") }, "Add the sample household");
    buttons.push(add);
  }
  if (canChange && d.added) {
    const remove = h("button", { type: "button", disabled: d.busy });
    remove.textContent = "Remove the sample household";
    remove.onclick = () => askFirst(remove, "Remove the sample's clips, people and log lines?", "Remove",
      () => run(remove, "Removing\u2026", "DELETE"));
    buttons.push(remove);
  }
  body.replaceChildren(
    h("p", { class: "quiet" }, "Three volunteers' voices to try Oread on; removing them takes nothing of yours. ",
      guideMore("A sample household to try")),
    h("section", { class: "card panel", id: "sample-household" }, h("h2", {}, "Sample household"),
      h("dl", { class: "kv" },
        h("dt", {}, "Here now"), h("dd", {}, d.added ? "yes" : "no"),
        h("dt", {}, "People"), h("dd", {}, d.people.length ? d.people.join(", ") : "none"),
        h("dt", {}, "Clips"), h("dd", {}, d.added ? d.clips + " on " + d.device : "none"),
        h("dt", {}, "Voices"), h("dd", {}, "LibriSpeech volunteers (CC BY 4.0)")),
      d.available ? null : h("p", { class: "error" }, "This Oread has no sample folder."),
      h("div", { class: "row" }, buttons), error));
}

// ---------- Settings, Devices: each device's models and speaker settings ----------

const SPEAKER_KNOBS = [
  ["unknown_below", "Person unknown below", "A best match below this is \u201cunknown\u201d."],
  ["match_above", "Person named at", "A best match at or above this names the person; in between is \u201cmaybe\u201d."],
  ["phrase_from", "Phrases from", "From this score up to the next, habit phrases may settle a \u201cmaybe\u201d."],
  ["phrase_to", "Phrases to", "The top of the phrase range (usually the same as Person named at)."],
];

async function drawDeviceSettings(body) {
  const [current, devicesData, choices] = await Promise.all([api("/settings"), api("/devices"), api("/models")]);
  // the voice assistant's devices, to match each device to one (its settings go with each clip)
  let assistantDevices = null;
  if (can("home assistant", false)) {
    try {
      const found = await api("/assistant/devices");
      assistantDevices = found.configured ? found.devices : null;
    } catch (e) { assistantDevices = null; }
  }
  // the assistants' own voices (the patch for a device that hears itself), on each device's card
  let voices = null;
  if (can("profiles", false)) {
    const [profiles, learning] = await Promise.all([api("/profiles?all=true"), api("/assistant-voices").catch(() => null)]);
    voices = { list: profiles.filter((p) => p.kind === "assistant"), learning, canChange: can("profiles", true) };
  }
  const canChange = can("settings", true);
  const cards = devicesData.devices.map((d) => deviceSettingsCard(d, current[d.name], devicesData.types, choices,
    canChange, () => drawDeviceSettings(body), assistantDevices, voices));
  body.replaceChildren(
    h("p", { class: "quiet" }, "Each device's models and how it decides who spoke; changes here are for that device only. ",
      guideMore("Choosing models (optional)")),
    modelGuide(),
    h("div", { class: "device-settings" }, cards));
  const wanted = hashParams().get("device");
  const target = wanted && body.querySelector(".device-set[data-device='" + wanted + "']");
  if (target) { target.open = true; target.scrollIntoView({ block: "start" }); }
}

function deviceSettingsCard(device, now, types, choices, canChange, reload, assistantDevices, voices) {
  const card = foldable(h("details", { class: "card panel device-set fold", "data-device": device.name }),
    "device-set:" + device.name);
  const error = h("p", { class: "error", role: "alert" });
  const done = h("p", { class: "ok", role: "status" });
  const own = now.set_for_this_device || [];
  const kind = types.find((t) => t.name === device.type);
  const voice = choices.voice.find((m) => m.name === device.speaker_model) || { settings: {}, label: device.speaker_model };
  const speech = modelSelect("Speech model", choices.speech, device.stt_from === "device" ? device.stt_model : "",
    kind && kind.stt_model);
  const voiceSel = modelSelect("Voice model", choices.voice, device.speaker_from === "device" ? device.speaker_model : "",
    kind && kind.speaker_model);
  const inputs = {};
  const save = h("button", { class: "primary", type: "button", disabled: true }, "Save");
  const changed = () => {
    const modelsChanged = speech.select.value !== (device.stt_from === "device" ? device.stt_model : "") ||
      voiceSel.select.value !== (device.speaker_from === "device" ? device.speaker_model : "");
    save.disabled = !canChange || (!modelsChanged && !assistantChanged() &&
      !Object.keys(inputs).some((k) => valueOf(k) !== now[k]));
  };
  const valueOf = (key) => {
    const el = inputs[key];
    if (el.type === "checkbox") return el.checked;
    if (el.tagName === "SELECT") return el.value;
    return Number(el.value);
  };
  [speech.select, voiceSel.select].forEach((sel) => { sel.disabled = !canChange; sel.addEventListener("change", changed); });
  const source = (key) => own.indexOf(key) >= 0 ? " Set for this device." :
    (voice.settings[key] !== undefined ? " From " + voice.label + "." : "");
  const id = (key) => "ds-" + device.name.replace(/[^a-z0-9]+/gi, "-") + "-" + key;
  const knobFields = SPEAKER_KNOBS.map(([key, label, help]) => {
    const out = h("output", { for: id(key), class: "mono" }, Number(now[key]).toFixed(2));
    const range = h("input", { id: id(key), type: "range", min: 0, max: 1, step: "0.01", value: now[key],
      disabled: !canChange, oninput: () => { out.textContent = Number(range.value).toFixed(2); changed(); } });
    inputs[key] = range;
    const f = field(label, range, help + source(key));
    const wrap = h("div", { class: "slider" });
    range.replaceWith(wrap);
    wrap.append(range, out);
    return f;
  });
  const mode = h("select", { id: id("phrase_mode"), disabled: !canChange, onchange: changed },
    [["off", "Off"], ["shadow", "Shadow (notes only)"], ["on", "On"]].map(([v, t]) =>
      h("option", { value: v, selected: now.phrase_mode === v }, t)));
  inputs.phrase_mode = mode;
  const minimum = h("input", { id: id("min_training_seconds"), type: "number", min: 0.5, max: 10, step: 0.5,
    value: now.min_training_seconds, disabled: !canChange, oninput: changed });
  inputs.min_training_seconds = minimum;
  const report = h("input", { id: id("publish_speaker"), type: "checkbox", checked: now.publish_speaker,
    disabled: !canChange, onchange: changed });
  inputs.publish_speaker = report;
  const trim = h("input", { id: id("trim_silence"), type: "checkbox", checked: now.trim_silence,
    disabled: !canChange, onchange: changed });
  inputs.trim_silence = trim;
  const ownSpeaker = h("input", { id: id("hears_own_speaker"), type: "checkbox", checked: Boolean(now.hears_own_speaker),
    disabled: !canChange, onchange: changed });
  inputs.hears_own_speaker = ownSpeaker;
  const assistantSel = h("select", { id: id("assistant_device"), disabled: !canChange || !assistantDevices, onchange: changed },
    h("option", { value: "" }, "None"),
    (assistantDevices || []).map((d) => h("option", { value: d.id, selected: d.id === device.assistant_device }, d.name)));
  if (device.assistant_device && !(assistantDevices || []).some((d) => d.id === device.assistant_device)) {
    assistantSel.append(h("option", { value: device.assistant_device, selected: true }, device.assistant_device + " (not found now)"));
  }
  const assistantChanged = () => assistantSel.value !== (device.assistant_device || "");
  save.addEventListener("click", async () => {
    error.textContent = "";
    done.textContent = "Saving\u2026";
    save.disabled = true;
    try {
      const sttWas = device.stt_from === "device" ? device.stt_model : "";
      const vpWas = device.speaker_from === "device" ? device.speaker_model : "";
      if (speech.select.value !== sttWas || voiceSel.select.value !== vpWas) {
        done.textContent = "Loading the model\u2026 port " + device.port + " pauses for a moment.";
        await api("/devices/" + encodeURIComponent(device.name), { method: "PATCH",
          body: { stt_model: speech.select.value, speaker_model: voiceSel.select.value } });
      }
      if (assistantChanged()) {
        await api("/devices/" + encodeURIComponent(device.name), { method: "PATCH", body: { assistant_device: assistantSel.value } });
      }
      const knobs = {};
      Object.keys(inputs).forEach((k) => { if (valueOf(k) !== now[k]) knobs[k] = valueOf(k); });
      if (Object.keys(knobs).length) {
        await api("/settings/speaker?device=" + encodeURIComponent(device.name), { method: "PATCH", body: knobs });
      }
      await reload();
      const fresh = document.querySelector(".device-set[data-device='" + device.name + "'] .ok");
      if (fresh) fresh.textContent = "Saved; in use now.";
    } catch (e) {
      done.textContent = "";
      error.textContent = e.message;
      changed();
    }
  });
  const back = own.length && canChange ? h("button", { type: "button", class: "quiet-button", onclick: async () => {
    error.textContent = "";
    try {
      await api("/settings/speaker?device=" + encodeURIComponent(device.name), { method: "DELETE" });
      await reload();
      const fresh = document.querySelector(".device-set[data-device='" + device.name + "'] .ok");
      if (fresh) fresh.textContent = "Back to the models' and type's values.";
    } catch (e) {
      error.textContent = e.message;
    }
  } }, "Back to defaults") : "";
  card.append(
    h("summary", {}, h("div", { class: "person-head" }, h("h2", {}, device.name),
      device.type ? h("span", { class: "badge" }, typeLabel(types, device.type)) : null)),
    h("h3", {}, "Models"),
    h("div", { class: "knobs" }, speech.field, voiceSel.field,
      h("div", { class: "field" }, h("label", { class: "check" }, trim, " Trim the quiet after speech"),
        h("span", { class: "hint" }, "Skips clips with no speech and cuts the quiet after it; who spoke still uses the whole clip." +
          source("trim_silence"))),
      field("Voice assistant device", assistantSel, assistantDevices
        ? "Its device in your voice assistant, so each clip records that device's settings (microphone volume\u2026)."
        : "Set up a voice assistant (home_assistant: in data/settings.yaml) to record each clip's device settings.")),
    h("h3", {}, "Who spoke"),
    h("div", { class: "knobs" }, knobFields,
      field("Phrase habits", mode, "Whether a person's habit phrases may settle a \u201cmaybe\u201d." + source("phrase_mode")),
      field("Shortest clip to learn from (s)", minimum, "Shorter clips are still matched, but can't be assigned." +
        source("min_training_seconds")),
      h("div", { class: "field" }, h("label", { class: "check" }, report, " Report who spoke"),
        h("span", { class: "hint" }, "Sets the who-spoke sensor in Home Assistant (if set up on Connections). Turn off " +
          "for devices the intent router serves." + source("publish_speaker")))),
    h("h3", {}, "Patch: a device that hears itself"),
    h("div", { class: "knobs" }, h("div", { class: "field" }, h("label", { class: "check" }, ownSpeaker, " It hears its own speaker"),
      h("span", { class: "hint" }, "Only if the device answers itself: Oread learns the assistant's voice and marks its echoes." +
        source("hears_own_speaker"), " ", guideMore("Patch: a device that hears itself")))),
    voices ? herVoice(device.name, voices.list, voices.learning, voices.canChange, reload) : null,
    error, done,
    canChange ? h("div", { class: "row person-actions" }, save, back) : "");
  return card;
}

const KIND_TITLES = {
  speech: ["Speech models", "Turn speech into words."],
  voice: ["Voice models", "Tell voices apart. The thresholds depend on how each model scores voices, so each model keeps its own."],
  vad: ["Voice detectors", "Tell speech from silence, for devices that trim the quiet (and tools/client.py)."],
};

async function drawModels(body) {
  const data = await api("/models");
  const canChange = can("settings", true);
  const sections = ["speech", "voice", "vad"].filter((k) => data[k]).map((kind) => {
    const [title, about] = KIND_TITLES[kind];
    return foldable(h("details", { class: "models-section fold" }, h("summary", {}, h("h2", {}, title)),
      h("p", { class: "quiet" }, about),
      h("div", { class: "clips models" }, data[kind].map((m) => modelCard(kind, m, data.knobs[kind], canChange,
        () => drawModels(body))))), "models:" + kind);
  });
  body.replaceChildren(
    h("p", { class: "quiet" }, "Each model's settings, and the default model; yours are kept in data/models.yaml. ",
      guideMore("Choosing models (optional)")),
    ...sections);
}

function knobLabel(key) {
  return { num_threads: "Threads", language: "Language", unknown_below: "Person unknown below",
    match_above: "Person named at",
    phrase_from: "Phrases from", phrase_to: "Phrases to", threshold: "Sure at", min_silence_duration: "Pause (s)",
    min_speech_duration: "Speech (s)", keep_after_speech: "Kept after speech (s)" }[key] || key;
}

function modelCard(kind, m, knobs, canChange, reload) {
  const card = h("article", { class: "card clip model", "data-model": m.name, "data-kind": kind });
  const error = h("p", { class: "error", role: "alert" });
  const done = h("p", { class: "ok", role: "status" });
  const inputs = {};
  const save = h("button", { class: "primary", type: "button", disabled: true }, "Save");
  const changed = () => {
    save.disabled = !Object.keys(inputs).some((key) => String(inputs[key].value) !== String(m.settings[key]));
  };
  const fields = Object.keys(m.settings).filter((key) => knobs[key]).map((key) => {
    const k = knobs[key];
    const value = m.settings[key];
    const shipped = m.shipped_settings[key];
    const hint = k.help + (shipped !== undefined && shipped !== value ? " Shipped: " + shipped + "." : "");
    const id = "ms-" + kind + "-" + m.name.replace(/[^a-z0-9]+/gi, "-") + "-" + key;
    if (k.kind === "float" && k.max <= 1) {
      const out = h("output", { for: id, class: "mono" }, Number(value).toFixed(2));
      const range = h("input", { id: id, type: "range", min: k.min, max: k.max, step: "0.01", value: value,
        disabled: !canChange, oninput: () => { out.textContent = Number(range.value).toFixed(2); changed(); } });
      inputs[key] = range;
      const f = field(knobLabel(key), range, hint);
      const wrap = h("div", { class: "slider" });
      range.replaceWith(wrap);
      wrap.append(range, out);
      return f;
    }
    const box = h("input", { id: id, type: k.kind === "text" ? "text" : "number", value: value, disabled: !canChange,
      min: k.min === null ? null : k.min, max: k.max === null ? null : k.max,
      step: k.kind === "int" ? "1" : "0.05", oninput: changed });
    inputs[key] = box;
    return field(knobLabel(key), box, hint);
  });
  const message = (result, what) => {
    const reloaded = Object.keys(result.devices || {}).filter((d) => result.devices[d] === "reloaded");
    return what + (reloaded.length ? " Reloaded on " + reloaded.join(", ") + "." : "");
  };
  const act = async (fn, what) => {
    error.textContent = "";
    done.textContent = "";
    card.querySelectorAll("button, input").forEach((b) => { b.disabled = true; });
    done.textContent = "Saving\u2026";
    try {
      const result = await fn();
      await reload();
      const fresh = document.querySelector("article.model[data-kind='" + kind + "'][data-model='" + m.name + "'] .ok");
      if (fresh) fresh.textContent = message(result, what);
    } catch (e) {
      done.textContent = "";
      error.textContent = e.message;
      card.querySelectorAll("button, input").forEach((b) => { b.disabled = false; });
      changed();
    }
  };
  save.addEventListener("click", () => act(() => {
    const values = {};
    Object.keys(inputs).forEach((key) => {
      values[key] = knobs[key].kind === "text" ? inputs[key].value : Number(inputs[key].value);
    });
    return api("/models/" + kind + "/" + encodeURIComponent(m.name), { method: "PATCH", body: { settings: values } });
  }, "Saved; in use now."));
  const path = "/models/" + kind + "/" + encodeURIComponent(m.name);
  const buttons = canChange ? h("div", { class: "row person-actions" }, save,
    m.default ? null : h("button", { type: "button", onclick: () => act(() => api(path + "/default", { method: "POST" }),
      m.label + " is the default now.") }, "Make default"),
    m.changed ? h("button", { type: "button", class: "quiet-button", onclick: () => act(() => api(path + "/settings",
      { method: "DELETE" }), "Back to the shipped settings.") }, "Back to shipped") : null) : "";
  const facts = [];
  if (m.memory_mb) facts.push("about " + m.memory_mb + " MB");
  if (kind !== "vad") facts.push(m.used_by.length ? "used by " + m.used_by.join(", ") : "no device uses it");
  else if (m.used_by.length) facts.push("trims for " + m.used_by.join(", "));
  if (m.changed) facts.push("your settings");
  card.append(
    h("div", { class: "person-head" }, h("h2", {}, m.label), m.default ? h("span", { class: "badge" }, "Default") : null),
    m.notes ? h("p", { class: "quiet small" }, m.notes) : "",
    h("p", { class: "quiet small" }, facts.join(" \u00B7 ")),
    h("div", { class: "knobs" }, fields),
    error, done, buttons);
  return card;
}

// ---------- Try it: speak into this device, see what Oread hears ----------

const MAX_SECONDS = 15;

function renderTry(main) {
  main.append(
    h("h1", {}, "Try it"),
    h("p", { class: "quiet" }, "Speak into this computer's or phone's microphone: see what Oread hears and who it thinks spoke. ",
      guideMore("8. Try Oread from your computer")));
  const card = h("section", { class: "card panel" }, h("p", { class: "quiet" }, "Loading…"));
  main.append(card);
  api("/devices").then((data) => drawTry(card, data.devices))
    .catch((e) => card.replaceChildren(h("p", { class: "error" }, e.message)));
}

function drawTry(card, deviceList) {
  if (!deviceList.length) {
    card.replaceChildren(h("p", {}, "There are no listening devices yet."));
    return;
  }
  const preferred = deviceList.find((d) => d.type === "laptop") || deviceList[0];
  const select = h("select", { id: "try-device" }, deviceList.map((d) =>
    h("option", { value: d.name, selected: d.name === preferred.name }, d.name + " (port " + d.port + ")")));
  const button = h("button", { class: "primary big", type: "button" }, "\u25CF Start speaking");
  const meter = h("div", { class: "meter", "aria-hidden": "true" }, h("span", {}));
  const status = h("p", { class: "quiet", role: "status" }, "Up to " + MAX_SECONDS + " seconds. Press Stop when you're done.");
  const result = h("div", { class: "result", "aria-live": "polite" });
  let recording = null;

  button.addEventListener("click", async () => {
    if (recording) { recording.stop(); return; }
    result.replaceChildren();
    try {
      recording = await startRecording(meter.firstChild, (seconds) => {
        status.textContent = "Listening… " + seconds.toFixed(1) + " s";
      }, MAX_SECONDS);
    } catch (e) {
      status.textContent = "";
      result.replaceChildren(h("p", { class: "error" }, micProblem(e)));
      recording = null;
      return;
    }
    button.textContent = "\u25A0 Stop";
    button.classList.add("stop");
    const audio = await recording.done;
    recording = null;
    button.textContent = "\u25CF Start speaking";
    button.classList.remove("stop");
    meter.firstChild.style.width = "0%";
    status.textContent = "Working it out…";
    button.disabled = true;
    try {
      const answer = await sendAudio(select.value, audio);
      status.textContent = "";
      result.replaceChildren(...describeAnswer(answer));
    } catch (e) {
      status.textContent = "";
      result.replaceChildren(h("p", { class: "error" }, e.message));
    } finally {
      button.disabled = false;
    }
  });

  card.replaceChildren(
    field("Test as", select, "Oread uses this device's settings, as if the audio came from it."),
    h("div", { class: "try-row" }, button, meter),
    status, result);
}

function micProblem(e) {
  if (e && e.name === "NotAllowedError") {
    return "The browser wasn't allowed to use the microphone. Allow it for this page " +
      "(usually the microphone or lock icon in the address bar) and try again.";
  }
  if (e && e.name === "NotFoundError") return "No microphone was found on this device.";
  if (!window.isSecureContext) return "Browsers only allow the microphone on https:// pages.";
  return "Couldn't start the microphone: " + (e && e.message ? e.message : e);
}

// Record from the microphone until stop() or the time limit. Resolves `done` with
// {samples: Float32Array, rate}.
async function startRecording(bar, onTick, maxSeconds) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: true },
  });
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  const context = new AudioCtx();
  await context.audioWorklet.addModule("recorder.js");
  const source = context.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(context, "oread-recorder");
  const chunks = [];
  let count = 0;
  let finish;
  const done = new Promise((resolve) => { finish = resolve; });
  let stopped = false;

  const stop = () => {
    if (stopped) return;
    stopped = true;
    node.port.onmessage = null;
    source.disconnect();
    node.disconnect();
    stream.getTracks().forEach((t) => t.stop());
    context.close();
    const samples = new Float32Array(count);
    let at = 0;
    for (const c of chunks) { samples.set(c, at); at += c.length; }
    finish({ samples: samples, rate: context.sampleRate });
  };

  node.port.onmessage = (event) => {
    const block = event.data;
    chunks.push(block);
    count += block.length;
    let peak = 0;
    for (let i = 0; i < block.length; i++) peak = Math.max(peak, Math.abs(block[i]));
    bar.style.width = Math.min(100, Math.round(peak * 140)) + "%";
    const seconds = count / context.sampleRate;
    onTick(seconds);
    if (seconds >= maxSeconds) stop();
  };
  source.connect(node);
  // the worklet must reach the output to run in every browser; it passes on silence
  node.connect(context.destination);
  return { stop: stop, done: done };
}

async function sendAudio(device, audio) {
  const pcm = new Int16Array(audio.samples.length);
  for (let i = 0; i < pcm.length; i++) {
    const s = Math.max(-1, Math.min(1, audio.samples[i]));
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }
  const response = await fetch("/api/try?device=" + encodeURIComponent(device) + "&rate=" + audio.rate, {
    method: "POST", credentials: "same-origin",
    headers: { "X-Requested-With": "oread", "Content-Type": "application/octet-stream" },
    body: pcm.buffer,
  });
  let data = null;
  try { data = await response.json(); } catch (e) { data = null; }
  if (!response.ok) throw new Error(messageOf(data) || "Oread answered " + response.status);
  return data;
}

function describeAnswer(a) {
  const out = [];
  out.push(a.text
    ? h("p", { class: "heard" }, "\u201C" + a.text + "\u201D")
    : h("p", { class: "heard none" }, "No words heard. Try again a little closer to the microphone."));
  let who;
  const score = a.score === null || a.score === undefined ? "" : " (score " + a.score.toFixed(2) + ")";
  if (a.label === "known") {
    who = h("p", {}, h("span", { class: "status known" }, "Known"), " ", h("strong", {}, a.speaker), score,
      a.by === "voice+phrase" ? h("span", { class: "quiet" }, ", helped by a habit phrase") : null);
  } else if (a.label === "maybe") {
    who = h("p", {}, h("span", { class: "status maybe" }, "Maybe"), " closest is ", h("strong", {}, a.guess), score,
      h("span", { class: "quiet" }, ", not sure enough to name"));
  } else if (a.label === "too short") {
    who = h("p", {}, h("span", { class: "status unknown" }, "Too short"), " to tell who's speaking");
  } else {
    who = h("p", {}, h("span", { class: "status unknown" }, "Unknown"),
      a.guess ? h("span", {}, " voice (closest is ", h("strong", {}, a.guess), score, ")")
              : " voice. Nobody has been taught yet.");
  }
  out.push(who);
  if (a.clip) {
    out.push(h("p", { class: "quiet" }, a.audio_s.toFixed(1) + " seconds. " + (a.trainable
      ? "Saved to Learn, where it can be assigned to a person to teach Oread their voice."
      : "Saved to Learn, but too short to teach Oread a voice (speak a little longer).")));
  }
  return out;
}

// ---------- Connections: who may connect, and the certificate ----------

function can(area, change) {
  const c = session.can[area];
  return Boolean(c && (change ? c.change : c.read));
}

function renderConnections(main) {
  main.append(h("h1", {}, "Connections"));
  if (can("access", false)) main.append(permittedPanel());
  main.append(certificatePanel());
  main.append(h("section", { class: "card panel" }, h("h2", {}, "Reporting who spoke"),
    h("p", { class: "quiet" }, "Coming next: the address and key of the system Oread tells who spoke " +
      "(Home Assistant, for example), with a Test button.")));
}

function permittedPanel() {
  const panel = h("section", { class: "card panel", id: "permitted" },
    h("h2", {}, "Permitted clients"),
    h("p", { class: "quiet" }, "Only these may send audio: your voice assistant, a router if you use one, test computers. ",
      guideMore("7. Who may connect: permitted clients")),
    h("p", { class: "quiet" }, h("small", {}, "Give each client a fixed address (a reservation in " +
      "your router), or it will be turned away when its address changes.")));
  const body = h("div", {}, h("p", { class: "quiet" }, "Loading…"));
  panel.append(body);
  const load = async () => {
    try {
      drawPermitted(body, await api("/access"), load);
    } catch (e) {
      body.replaceChildren(h("p", { class: "error" }, e.message));
    }
  };
  load();
  return panel;
}

function drawPermitted(body, view, reload) {
  const error = h("p", { class: "error", role: "alert" });
  const save = async (list) => {
    error.textContent = "";
    try {
      await api("/access", { method: "PUT", body: { allowed_clients: list } });
      reload();
    } catch (e) {
      error.textContent = e.message;
    }
  };
  const list = view.allowed_clients;
  const parts = [];
  if (view.local_network_only) {
    parts.push(h("p", { class: "warn" }, "\u26A0 Open to your whole network: any address on your local " +
      "network can send audio to Oread (nothing from the internet). Add your voice assistant's address to " +
      "allow only it."));
  }
  parts.push(list.length
    ? h("ul", { class: "rows" }, list.map((entry) => h("li", {},
        h("span", { class: "mono" }, entry),
        h("button", { type: "button", onclick: () => save(list.filter((x) => x !== entry)),
          "aria-label": "Remove " + entry }, "Remove"))))
    : h("p", { class: "quiet" }, "No addresses yet."));

  const box = h("input", { id: "new-address", type: "text", autocomplete: "off", spellcheck: "false",
    placeholder: "for example 192.168.1.50 or 192.168.1.0/24", inputmode: "decimal" });
  const add = h("form", { class: "inline", novalidate: true, onsubmit: (event) => {
    event.preventDefault();
    const entry = box.value.trim();
    if (!entry) return;
    if (list.indexOf(entry) >= 0) { error.textContent = entry + " is already on the list"; return; }
    save(list.concat([entry]));
  } },
    h("label", { for: "new-address" }, "Add an address or range"),
    h("div", { class: "row" }, box, h("button", { class: "primary", type: "submit" }, "Add")));
  parts.push(add);
  if (view.your_address && list.indexOf(view.your_address) < 0) {
    parts.push(h("p", {}, h("button", { type: "button", onclick: () => save(list.concat([view.your_address])) },
      "Add this computer (" + view.your_address + ")")));
  }
  parts.push(error);

  const refused = view.recently_refused || [];
  parts.push(h("h3", {}, "Recently refused"));
  parts.push(refused.length
    ? h("ul", { class: "rows" }, refused.map((r) => h("li", {},
        h("span", {}, h("span", { class: "mono" }, r.address || "unknown"), " ",
          h("span", { class: "quiet" }, "on " + r.device + ", " + new Date(r.time).toLocaleString())),
        r.address && list.indexOf(r.address) < 0
          ? h("button", { type: "button", onclick: () => save(list.concat([r.address])) }, "Allow")
          : null)))
    : h("p", { class: "quiet" }, "Nobody has been turned away."));
  if (!can("access", true)) {
    parts.push(h("p", { class: "quiet" }, "Only a super user can change this list."));
  }
  body.replaceChildren(...parts);
}

function certificatePanel() {
  const panel = h("section", { class: "card panel", id: "certificate" }, h("h2", {}, "Certificate"));
  const body = h("div", {}, h("p", { class: "quiet" }, "Loading…"));
  panel.append(body);
  api("/status").then((status) => {
    const https = status.https || {};
    const parts = [];
    if (!https.https) {
      parts.push(h("p", {}, "Oread is serving plain HTTP (behind a reverse proxy)."));
    } else {
      if (https.expires) {
        parts.push(h("p", {}, "Runs out " + new Date(https.expires).toLocaleDateString() +
          " (" + https.days_left + " days)."));
      }
      if (https.names) {
        parts.push(h("p", { class: "quiet" }, "Covers: ", h("span", { class: "mono" }, https.names.join(", "))));
      }
      if (https.household) {
        parts.push(h("p", {}, "Oread's own household certificate: install it on each device to stop the browser warning. ",
          guideMore("A. Install Oread's household certificate")));
        parts.push(h("div", { class: "links" },
          h("a", { href: "/ca.crt", download: "oread-household-ca.crt" }, "Download the certificate")));
      }
    }
    body.replaceChildren(...parts);
  }).catch((e) => body.replaceChildren(h("p", { class: "error" }, e.message)));
  return panel;
}

// ---------- Stats: what Oread costs to run, and phrase habits (in the page) ----------

function renderStats(main) {
  const tabsAllowed = [["resources", "Resources"], ["time", "Where the time goes"]];
  if (can("phrases", false)) tabsAllowed.push(["phrases", "Phrase habits"]);
  let current = hashParams().get("tab") || "resources";
  const tabs = h("div", { class: "tabs", role: "tablist", "aria-label": "Which report" });
  const body = h("div", {});
  const draw = () => {
    tabs.replaceChildren(...tabsAllowed.map(([id, label]) => h("button", { type: "button", role: "tab",
      "aria-selected": id === current ? "true" : "false",
      onclick: () => { current = id; history.replaceState(null, "", "#/stats?tab=" + id); draw(); } }, label)));
    body.replaceChildren(h("p", { class: "quiet" }, "Loading…"));
    (current === "phrases" ? drawPhrases(body) : current === "time" ? drawTimeGoes(body) : drawResources(body)).catch((e) =>
      body.replaceChildren(h("p", { class: "error" }, e.message)));
  };
  main.append(h("h1", {}, "Stats"), h("div", { class: "toolbar" }, tabs,
    h("button", { type: "button", onclick: () => draw() }, "Refresh")), body);
  draw();
}

// Where the time goes: each request's steps, by period; whose time each is (Oread's code or a model's)
const TIME_STEPS = [
  ["speaking", "Speaking", "the audio arriving from the device: the person talking, not Oread's time"],
  ["time_in", "Time in", "waiting in line for a free slot (Oread)"],
  ["stt", "Speech to text", "the speech model's own time"],
  ["voice_beyond", "Voice ID beyond", "voice ID's time past speech to text (they run side by side)"],
  ["ospri", "OSPRI", "applying the correction parameters (Oread); not built yet"],
  ["time_out", "Time to out", "matching the voice, saving the clip, Home Assistant, the reply (Oread)"],
];

async function drawTimeGoes(body) {
  let tz = "";
  try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (e) { tz = ""; }
  const data = await api("/stats/time" + (tz ? "?tz=" + encodeURIComponent(tz) : ""));
  const devices = Array.from(new Set([].concat(...["last_24_hours", "day", "week", "month"].map((p) =>
    data[p].map((b) => Object.keys(b.by_device)))))).sort();
  const choose = (id, label, options, start) => {
    const select = h("select", { id }, options.map(([v, t]) => h("option", { value: v, selected: v === start }, t)));
    select.addEventListener("change", draw);
    return { select, field: h("div", { class: "field" }, h("label", { for: id }, label), select) };
  };
  const period = choose("tg-period", "Period", [["last_24_hours", "Last 24 hours"], ["day", "By day"], ["week", "By week"],
    ["month", "By month"]], "day");
  const device = choose("tg-device", "Device", [["", "All devices"]].concat(devices.map((d) => [d, d])), "");
  const measure = choose("tg-measure", "Show", [["median", "Median"], ["p95", "Slowest 5%"], ["average", "Average"]], "median");
  const out = h("div", {});
  function draw() {
    const rows = data[period.select.value].map((b) => {
      const part = device.select.value ? b.by_device[device.select.value] || { count: 0 } : b;
      return [b.label, part.count].concat(TIME_STEPS.map(([key]) => {
        if (key === "ospri" && !part.ospri) return "not built yet";
        if (!part.count) return "";
        return part[key] ? ms(part[key][measure.select.value]) : "-";
      }));
    });
    out.replaceChildren(table(["", "Requests"].concat(TIME_STEPS.map(([, label]) => label)), rows));
  }
  body.replaceChildren(
    h("p", { class: "quiet" }, "Each request's time, step by step, in the order it goes through them. Days, weeks (from Monday) " +
      "and months are this browser's (" + data.time_zone + "); each request's steps are kept " + data.keep_days +
      " days (stats: keep_days)."),
    h("ul", { class: "quiet small" }, TIME_STEPS.map(([, label, about]) => h("li", {}, h("strong", {}, label), ": " + about))),
    h("div", { class: "row filters" }, period.field, device.field, measure.field),
    out);
  draw();
}

function statTile(label, value, sub) {
  return h("div", { class: "stat card" }, h("span", { class: "stat-label" }, label),
    h("span", { class: "stat-value" }, value), sub ? h("span", { class: "stat-sub" }, sub) : null);
}

function mb(v) { return v === undefined || v === null ? "-" : v >= 1024 ? (v / 1024).toFixed(1) + " GB" : Math.round(v) + " MB"; }
function ms(v) { return v === undefined || v === null ? "-" : v >= 1000 ? (v / 1000).toFixed(1) + " s" : Math.round(v) + " ms"; }
function pct(v) { return v === undefined || v === null ? "-" : Math.round(v) + "%"; }

function table(headers, rows) {
  return h("div", { class: "table-wrap" }, h("table", { class: "results" },
    h("thead", {}, h("tr", {}, headers.map((x) => h("th", {}, x)))),
    h("tbody", {}, rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, c === undefined || c === null ? "-" : String(c))))))));
}

function section(title, ...content) {
  return foldable(h("details", { class: "card panel fold" }, h("summary", {}, h("h2", {}, title)), content),
    "stats:" + title);
}

// a box that folds: open unless the viewer closed it last time (remembered in this browser)
function foldable(box, key) {
  let closed = false;
  try { closed = localStorage.getItem("oread-fold:" + key) === "closed"; } catch (e) { /* storage off */ }
  box.open = !closed;
  box.addEventListener("toggle", () => {
    try { localStorage.setItem("oread-fold:" + key, box.open ? "open" : "closed"); } catch (e) { /* storage off */ }
  });
  return box;
}

async function drawResources(body) {
  const r = await api("/resources");
  const recent = (r.requests && r.requests.last_requests) || {};
  const cpu = r.cpu || {};
  const mem = r.memory || {};
  const disk = r.disk || {};
  const parts = [];
  parts.push(h("div", { class: "stats-row" },
    statTile("Memory", mb(mem.oread_now_mb), "peak " + mb(mem.oread_peak_mb)),
    statTile("CPU", pct(cpu.last_5_minutes_percent_of_one_core !== undefined
      ? cpu.last_5_minutes_percent_of_one_core : cpu.average_percent_of_one_core_since_start),
      "of one core \u00B7 " + cpu.cores_available + " cores, shared"),
    statTile("Disk", mb(disk.models_in_use_mb), "models in use \u00B7 " + disk.free_gb + " GB free"),
    statTile("Reply", ms(recent.median_reply_ms), recent.count ? "typical \u00B7 slowest " + ms(recent.slowest_5_percent_ms) : "no requests yet")));

  const hist = r.history || {};
  const periods = [["last_hour", "Last hour"], ["last_24_hours", "Last 24 hours"], ["last_30_days", "Last 30 days"]]
    .filter(([k]) => hist[k]);
  parts.push(section("Over time",
    periods.length ? table(["", "CPU average", "Busiest minute", "Memory average", "Memory highest", "Requests", "Waited", "Longest wait"],
      periods.map(([k, label]) => {
        const x = hist[k];
        return [label, pct(x.cpu_average_percent_of_one_core), pct(x.cpu_busiest_minute_percent),
          mb(x.memory_average_mb), mb(x.memory_highest_mb), x.requests, x.requests_that_waited,
          x.longest_queue_wait_ms === undefined ? undefined : ms(x.longest_queue_wait_ms)];
      }))
      : h("p", { class: "quiet" }, "Oread measures itself once a minute; check back shortly."),
    h("p", { class: "quiet small" }, "CPU is shown as a share of one core, so 150% means one and a half cores busy.")));

  const byDevice = (r.requests && r.requests.by_device) || {};
  const devices = Object.keys(byDevice);
  parts.push(section("Speed by device",
    devices.length ? table(["Device", "Requests", "Typical reply", "Slowest 5%", "Typical clip", "Work per second of speech", "Longest wait"],
      devices.map((d) => {
        const x = byDevice[d];
        return [d, x.count, ms(x.median_reply_ms), ms(x.slowest_5_percent_ms),
          x.median_audio_s === undefined ? undefined : x.median_audio_s.toFixed(1) + " s",
          x.median_work_per_second_of_speech === undefined ? undefined : x.median_work_per_second_of_speech.toFixed(2) + " s",
          ms(x.longest_queue_wait_ms)];
      }))
      : h("p", { class: "quiet" }, "No requests yet."),
    h("p", { class: "quiet small" }, "Over the last 200 requests. Work per second of speech: 0.25 means a 4-second command took 1 second.")));

  const cap = r.capacity || {};
  const q = r.queue || {};
  const ever = q.longest_wait_ever;
  parts.push(section("Waiting in line",
    h("p", {}, "Oread works on " + cap.max_concurrent + " requests at once; more wait their turn. " +
      "When everything is busy it uses " + cap.threads_when_all_busy + " threads on " + cap.cores_available + " cores."),
    h("p", {}, typeof ever === "object" && ever
      ? "Longest wait ever: " + ms(ever.wait_ms) + " (" + ever.device + ", " + new Date(ever.time).toLocaleString() + ")."
      : "No request has had to wait yet."),
    h("p", { class: "quiet small" }, "If waits show up often, raise server.max_concurrent in data/settings.yaml and " +
      "restart, with the cores to back it.")));

  parts.push(section("Processor and disk",
    table(["", ""], [
      ["Processor", cpu.processor],
      ["AVX2 / AVX-512", (cpu.has_avx2 ? "yes" : "no") + " / " + (cpu.has_avx512 ? "yes" : "no")],
      ["Machine memory (shared)", mb(mem.machine_total_mb) + " (" + mb(mem.machine_available_mb) + " available)"],
      ["Models in use / all downloaded", mb(disk.models_in_use_mb) + " / " + mb(disk.models_mb)],
      ["Voice data and logs", mb(disk.data_mb) + " and " + mb(disk.logs_mb) + " (" + disk.clips_saved + " clips)"],
      ["Disk free", disk.free_gb + " GB"],
      ["Models loaded", ((r.models_loaded || {}).speech_to_text || []).concat((r.models_loaded || {}).voiceprints || []).join(", ")],
      ["Running for", r.uptime_hours < 1 ? Math.round(r.uptime_hours * 60) + " minutes" : r.uptime_hours.toFixed(1) + " hours"],
    ])));
  body.replaceChildren(...parts);
}

function bars(rows, total) {
  if (!rows.length) return h("p", { class: "quiet small" }, "Nothing used twice yet.");
  const most = Math.max(...rows.map((r) => r[1]));
  return h("div", { class: "bars" }, rows.map(([label, n]) => h("div", { class: "bar-row" },
    h("span", { class: "bar-label", title: label }, label),
    h("span", { class: "bar-track" }, h("span", { class: "bar-fill", "data-w": Math.round(100 * n / most) })),
    h("span", { class: "bar-count" }, n + " of " + total))));
}

async function drawPhrases(body) {
  const people = await api("/profiles");
  const withClips = people.filter((p) => p.clips);
  if (!withClips.length) {
    body.replaceChildren(h("p", { class: "empty-state" }, "No phrases yet: they come from clips assigned to people on the Learn page."));
    return;
  }
  const data = await Promise.all(withClips.map((p) => api("/profiles/" + encodeURIComponent(p.name) + "/phrases?top=10")));
  body.replaceChildren(
    h("p", { class: "quiet" }, "Each person's most-used phrases, from their clips; habit phrases help tell people apart."),
    ...data.map((d) => section(d.profile + " \u00B7 " + d.clips + (d.clips === 1 ? " clip" : " clips"),
      d.habits && d.habits.length ? h("p", { class: "small" }, h("strong", {}, "Habit phrases: "),
        d.habits.slice(0, 8).map((x, i) => [i ? ", " : "", "\u201C" + x.phrase + "\u201D"])) : null,
      h("div", { class: "cols" },
        h("div", {}, h("h3", {}, "Phrases"), bars(d.phrases.map((x) => [x.phrase, x.clips]), d.clips)),
        h("div", {}, h("h3", {}, "Words"), bars(d.words.map((x) => [x.word, x.clips]), d.clips))))));
  // widths set from data after building (no inline styles in the markup)
  body.querySelectorAll(".bar-fill").forEach((el) => { el.style.width = el.getAttribute("data-w") + "%"; });
}

// ---------- Users: who may sign in, their roles, and the audit log ----------

const ROLE_INFO = {
  super: "Everything, including stored keys, permitted clients and other super users.",
  administrator: "Devices, settings, device types, API tokens, Home Assistant; adds reviewers and viewers.",
  reviewer: "Listens to clips on Learn, assigns them to people, adds and renames people.",
  viewer: "Looks only: Stats, People, Devices and Settings.",
};

function renderUsers(main) {
  const tabsAllowed = [["accounts", "Accounts"]];
  if (can("audit", false)) tabsAllowed.push(["audit", "Audit log"]);
  let current = hashParams().get("tab") || "accounts";
  const tabs = h("div", { class: "tabs", role: "tablist", "aria-label": "Which list" });
  const body = h("div", {});
  const draw = () => {
    tabs.replaceChildren(...tabsAllowed.map(([id, label]) => h("button", { type: "button", role: "tab",
      "aria-selected": id === current ? "true" : "false",
      onclick: () => { current = id; history.replaceState(null, "", "#/users?tab=" + id); draw(); } }, label)));
    body.replaceChildren(h("p", { class: "quiet" }, "Loading…"));
    (current === "audit" ? drawAudit(body) : drawAccounts(body)).catch((e) =>
      body.replaceChildren(h("p", { class: "error" }, e.message)));
  };
  main.append(h("h1", {}, "Users"),
    h("p", { class: "quiet" }, "The people who sign in to these pages, and what each may do. (The voices " +
      "Oread recognises are on People.)"),
    h("div", { class: "toolbar" }, tabs), body);
  draw();
}

async function drawAccounts(body) {
  const data = await api("/users");
  const me = session.user;
  const mayManage = (u) => u.name !== me.name && (me.role === "super" || data.you_can_grant.indexOf(u.role) >= 0);
  const reload = () => drawAccounts(body);
  const rows = h("ul", { class: "rows users" }, data.users.map((u) => userRow(u, me, mayManage(u), data.you_can_grant, reload)));
  body.replaceChildren(
    h("section", { class: "card panel" }, h("h2", {}, "Accounts"), rows),
    addUserForm(data.you_can_grant, reload),
    h("details", { class: "tips card" }, h("summary", {}, "What each role may do"),
      h("ul", {}, ["super", "administrator", "reviewer", "viewer"].map((r) =>
        h("li", {}, h("strong", {}, r + ": "), ROLE_INFO[r]))),
      h("p", { class: "quiet small" }, "Each role manages only the roles below it; changing a role or password signs that person out. ",
        guideMore("6. People and roles"))));
}

function userRow(u, me, manageable, grantable, reload) {
  const li = h("li", { "data-user": u.name });
  const error = h("p", { class: "error", role: "alert" });
  const facts = [u.last_sign_in ? "last signed in " + when(u.last_sign_in) : "never signed in"];
  if (u.locked) facts.push("locked after wrong passwords (a password reset unlocks it)");
  const view = () => {
    li.replaceChildren(
      h("div", {},
        h("strong", {}, u.name), " ", h("span", { class: "badge" }, u.role),
        u.name === me.name ? h("span", { class: "quiet small" }, " (you)") : null,
        h("p", { class: "quiet small" }, facts.join(" \u00B7 ")),
        u.name === me.name ? h("p", { class: "quiet small" }, "Change your own password on Account.") : null,
        error),
      manageable ? h("div", { class: "row person-actions" },
        h("button", { type: "button", onclick: changeRole }, "Role"),
        h("button", { type: "button", onclick: resetPassword }, "Reset password"),
        h("button", { type: "button", class: "quiet-button", onclick: remove }, "Remove")) : "");
  };
  const changeRole = () => {
    const select = h("select", { "aria-label": "Role for " + u.name },
      grantable.map((r) => h("option", { value: r, selected: r === u.role }, r)));
    const note = h("p", { class: "quiet small" }, ROLE_INFO[u.role]);
    select.addEventListener("change", () => { note.textContent = ROLE_INFO[select.value]; });
    li.replaceChildren(h("form", { novalidate: true, class: "wide", onsubmit: async (event) => {
      event.preventDefault();
      error.textContent = "";
      try {
        await api("/users/" + encodeURIComponent(u.name), { method: "PATCH", body: { role: select.value } });
        reload();
      } catch (e) {
        error.textContent = e.message;
      }
    } }, h("p", {}, h("strong", {}, u.name), " \u2014 signed out when the role changes."), select, note, error,
      h("div", { class: "row" }, h("button", { class: "primary", type: "submit" }, "Save"),
        h("button", { type: "button", onclick: view }, "Cancel"))));
    select.focus();
  };
  const resetPassword = () => {
    const id = "pw-" + u.name.replace(/[^a-z0-9]+/gi, "-");
    const f = form([
      field("New password for " + u.name, input(id, "password", { autocomplete: "new-password" }), "At least 10 characters."),
      field("New password again", input(id + "-2", "password", { autocomplete: "new-password" })),
    ], "Reset password", async (el) => {
      if (value(el, id) !== value(el, id + "-2")) throw new Error("The two passwords don't match");
      await api("/users/" + encodeURIComponent(u.name), { method: "PATCH", body: { password: value(el, id) } });
      reload();
    });
    checkPasswords(f, id, id + "-2");
    li.replaceChildren(h("div", { class: "wide" },
      h("p", { class: "quiet small" }, "Tell " + u.name + " the new password yourself; they're signed out now " +
        "and can change it on Account after signing in."),
      f, h("button", { type: "button", onclick: view }, "Cancel")));
    li.querySelector("input").focus();
  };
  const remove = (event) => askFirst(event.currentTarget, "Remove " + u.name + "? They're signed out at once and " +
    "can't sign in again.", "Remove " + u.name, async () => {
    try {
      await api("/users/" + encodeURIComponent(u.name), { method: "DELETE" });
      reload();
    } catch (e) {
      error.textContent = e.message;
    }
  });
  view();
  return li;
}

function addUserForm(grantable, reload) {
  const role = h("select", { id: "new-user-role" }, grantable.map((r) =>
    h("option", { value: r, selected: r === "reviewer" }, r)));
  const roleNote = h("span", { class: "hint", id: "new-user-role-hint" }, ROLE_INFO[role.value] || "");
  role.setAttribute("aria-describedby", roleNote.id);
  role.addEventListener("change", () => { roleNote.textContent = ROLE_INFO[role.value]; });
  const done = h("p", { class: "ok", role: "status" });
  const f = form([
    field("Username", input("new-user-name", "text", { autocomplete: "off", autocapitalize: "none", spellcheck: "false" }),
      "2-32 letters, digits, . _ or -. They sign in with it."),
    h("div", { class: "field" }, h("label", { for: "new-user-role" }, "Role"), role, roleNote),
    field("Password", input("new-user-pass", "password", { autocomplete: "new-password" }),
      "At least 10 characters. Give it to them yourself; they can change it on Account."),
    field("Password again", input("new-user-pass2", "password", { autocomplete: "new-password" })),
  ], "Add user", async (el) => {
    done.textContent = "";
    if (value(el, "new-user-pass") !== value(el, "new-user-pass2")) throw new Error("The two passwords don't match");
    const added = await api("/users", { method: "POST", body: {
      username: value(el, "new-user-name"), password: value(el, "new-user-pass"), role: role.value } });
    el.reset();
    await reload();
    const status = document.querySelector("#add-user .ok");
    if (status) status.textContent = added.name + " can sign in now, as a " + added.role + ".";
  });
  checkPasswords(f, "new-user-pass", "new-user-pass2");
  return h("section", { class: "card panel", id: "add-user" }, h("h2", {}, "Add a user"),
    h("p", { class: "quiet" }, "You can give roles below your own" +
      (session.user.role === "super" ? " (or super, as a super user)." : ".")), f, done);
}

async function drawAudit(body) {
  const data = await api("/audit?limit=300");
  const rows = data.events.map((e) => h("tr", {},
    h("td", {}, when(e.time)), h("td", {}, e.who || "-"), h("td", {}, e.action),
    h("td", {}, [e.target, e.detail].filter(Boolean).join(" \u00B7 ") || ""),
    h("td", { class: e.status && e.status >= 400 ? "bad" : "" }, e.status ? String(e.status) : ""),
    h("td", { class: "mono small" }, e.client || "")));
  body.replaceChildren(h("section", { class: "card panel" },
    h("h2", {}, "Who changed what"),
    h("p", { class: "quiet" }, "Newest first: every change and sign-in (logs/audit.jsonl). No passwords or keys are written."),
    data.events.length ? h("div", { class: "table-wrap" }, h("table", { class: "results audit" },
      h("thead", {}, h("tr", {}, ["When", "Who", "What", "Details", "Result", "From"].map((t) => h("th", {}, t)))),
      h("tbody", {}, rows))) : h("p", { class: "empty-state" }, "Nothing recorded yet.")));
}

// ---------- Imports: where each model comes from (download address, files, license) ----------

const IMPORT_KINDS = [["speech", "Speech models"], ["voice", "Voice models"], ["vad", "Voice detectors"]];
const IMPORT_FIELDS = {
  label: ["Name shown on the pages", "Short, like \u201cParakeet\u201d."],
  kind: ["How it's loaded", "The kind of model, which tells sherpa-onnx how to run it."],
  url: ["Download address", "Where Oread downloads it the first time it's used (https://)."],
  folder: ["Folder inside the archive", "Speech models come as a .tar.bz2 archive; this is the folder it unpacks to."],
  files: ["Files inside that folder", "Which file plays each part."],
  file: ["File name", "Saved under models/ with this name."],
  languages: ["Languages", "Two-letter codes, separated by commas."],
  author: ["Author", ""],
  license: ["License", "Check it before using a model."],
  card: ["Model card", "The page with the model's details and license (https://)."],
  memory_mb: ["Memory once loaded (MB)", "Measured or estimated; shown when choosing models."],
  notes: ["What to expect", "Shown when choosing models."],
};

function renderImports(main) {
  const params = hashParams();
  const state = { kind: params.get("kind") || "speech", model: params.get("model") || "" };
  const tabs = h("div", { class: "tabs", role: "tablist", "aria-label": "Which kind of model" });
  const pills = h("div", { class: "pills", role: "group", "aria-label": "Models" });
  const body = h("div", {});
  let data = null;
  const canChange = can("settings", true);
  const remember = () => history.replaceState(null, "", "#/imports?kind=" + state.kind +
    (state.model ? "&model=" + encodeURIComponent(state.model) : ""));
  const draw = () => {
    tabs.replaceChildren(...IMPORT_KINDS.map(([id, label]) => h("button", { type: "button", role: "tab",
      "aria-selected": id === state.kind ? "true" : "false",
      onclick: () => { state.kind = id; state.model = ""; remember(); draw(); } }, label)));
    const rows = data[state.kind];
    if (state.model !== "+new" && !rows.find((r) => r.name === state.model)) {
      const fallback = rows.find((r) => r.default) || rows[0];
      state.model = fallback ? fallback.name : "+new";
    }
    pills.replaceChildren(...rows.map((r) => h("button", { type: "button", class: "pill",
      "aria-pressed": r.name === state.model ? "true" : "false", "data-model": r.name,
      onclick: () => { state.model = r.name; remember(); draw(); } }, r.label || r.name)),
      canChange ? h("button", { type: "button", class: "pill add", "aria-pressed": state.model === "+new" ? "true" : "false",
        onclick: () => { state.model = "+new"; remember(); draw(); } }, "+ Add a model") : "");
    body.replaceChildren(importCard(state.kind, state.model === "+new" ? null :
      rows.find((r) => r.name === state.model), data, canChange, async (fresh, pick, message) => {
      data = fresh || await api("/imports");
      if (pick) state.model = pick;
      remember();
      draw();
      const ok = body.querySelector(".ok");
      if (ok && message) ok.textContent = message;
    }));
  };
  main.append(h("h1", {}, "Imports"),
    h("p", { class: "quiet" }, "Where each model comes from: download address, files and license; yours are kept in data/models.yaml. ",
      guideMore("Choosing models (optional)")),
    h("div", { class: "toolbar" }, tabs), pills, body);
  api("/imports").then((d) => { data = d; draw(); }).catch((e) => body.replaceChildren(h("p", { class: "error" }, e.message)));
}

function importCard(kind, row, data, canChange, done) {
  const isNew = !row;
  const entry = row || {};
  const shipped = (row && row.shipped_entry) || {};
  const fields = data.fields[kind];
  const inputs = {};
  const error = h("p", { class: "error", role: "alert" });
  const ok = h("p", { class: "ok", role: "status" });
  const id = (k) => "imp-" + kind + "-" + k;
  const nameBox = isNew ? h("input", { id: id("name"), type: "text", autocomplete: "off", autocapitalize: "none",
    spellcheck: "false", placeholder: "for example whisper-base-en-int8" }) : null;
  const filesBox = h("div", { class: "file-roles" });
  const drawFiles = () => {
    const kindNow = inputs.kind ? inputs.kind.value : entry.kind;
    const roles = data.file_roles[kindNow] || [];
    const was = {};
    filesBox.querySelectorAll("input").forEach((i) => { was[i.dataset.role] = i.value; });
    filesBox.replaceChildren(...roles.map((role) => {
      const box = h("input", { id: id("file-" + role), type: "text", "data-role": role, disabled: !canChange,
        value: was[role] !== undefined ? was[role] : ((entry.files || {})[role] || "") });
      return h("div", { class: "field" }, h("label", { for: box.id }, role.replace(/_/g, " ")), box);
    }));
  };
  const hint = (k) => {
    const base = IMPORT_FIELDS[k][1];
    const was = shipped[k];
    const now = entry[k];
    if (!isNew && row.shipped && was !== undefined && JSON.stringify(was) !== JSON.stringify(now)) {
      return base + " Shipped: " + (typeof was === "object" ? JSON.stringify(was) : was) + ".";
    }
    return base;
  };
  const parts = fields.filter((k) => k !== "files").map((k) => {
    let control;
    if (k === "kind") {
      const options = kind === "speech" ? data.speech_kinds : data.vad_kinds;
      control = h("select", { id: id(k), disabled: !canChange },
        options.map((o) => h("option", { value: o, selected: o === entry.kind }, o)));
      if (kind === "speech") control.addEventListener("change", drawFiles);
    } else if (k === "notes") {
      control = h("textarea", { id: id(k), rows: 2, disabled: !canChange }, entry.notes || "");
    } else {
      const value = k === "languages" ? (entry.languages || ["en"]).join(", ") : (entry[k] === undefined ? "" : entry[k]);
      control = h("input", { id: id(k), type: k === "memory_mb" ? "number" : "text", min: k === "memory_mb" ? 0 : null,
        value: value, disabled: !canChange, autocomplete: "off", spellcheck: "false" });
    }
    inputs[k] = control;
    const f = field(IMPORT_FIELDS[k][0], control, hint(k));
    if (k === "url" || k === "card" || k === "notes") f.classList.add("wide-field");   // long values get the full row
    return f;
  });
  if (fields.indexOf("files") >= 0) {
    drawFiles();
    parts.splice(fields.indexOf("folder") + 1, 0, h("div", { class: "field" },
      h("span", { class: "label" }, IMPORT_FIELDS.files[0]), filesBox,
      h("span", { class: "hint" }, hint("files"))));
  }
  const collect = () => {
    const out = {};
    Object.keys(inputs).forEach((k) => {
      out[k] = k === "memory_mb" ? Number(inputs[k].value || 0) : inputs[k].value;
    });
    if (fields.indexOf("files") >= 0) {
      out.files = {};
      filesBox.querySelectorAll("input").forEach((i) => { out.files[i.dataset.role] = i.value; });
    }
    return out;
  };
  const path = "/imports/" + kind + (isNew ? "" : "/" + encodeURIComponent(entry.name));
  const act = async (fn, pick, message) => {
    error.textContent = "";
    ok.textContent = "Saving\u2026";
    try {
      const result = await fn();
      const reloaded = result && result.reloaded && result.reloaded.length ?
        " Loaded again on " + result.reloaded.join(", ") + "." : "";
      await done(result, pick, message + reloaded);
    } catch (e) {
      ok.textContent = "";
      error.textContent = e.message;
    }
  };
  const buttons = [];
  if (canChange) {
    buttons.push(h("button", { class: "primary", type: "button", onclick: () => isNew
      ? act(() => api(path, { method: "POST", body: { name: nameBox.value, fields: collect() } }), nameBox.value.trim(),
        "Added. It's downloaded the first time a device uses it; choose it on Settings, Devices.")
      : act(() => api(path, { method: "PUT", body: { fields: collect() } }), null, "Saved.") }, isNew ? "Add model" : "Save"));
    if (!isNew) {
      buttons.push(h("button", { type: "button", onclick: async () => {
        error.textContent = "";
        ok.textContent = "Checking\u2026";
        try {
          const r = await api(path + "/check", { method: "POST" });
          ok.textContent = r.ok ? "The address answers" + (r.size_mb ? " (about " + r.size_mb + " MB)." : ".") : "";
          if (!r.ok) error.textContent = r.note;
        } catch (e) { ok.textContent = ""; error.textContent = e.message; }
      } }, "Check the link"));
      if (row.shipped && row.changed) {
        buttons.push(h("button", { type: "button", class: "quiet-button", onclick: () =>
          act(() => api(path, { method: "DELETE" }), null, "Back to the shipped entry.") }, "Back to shipped"));
      } else if (!row.shipped) {
        buttons.push(h("button", { type: "button", class: "quiet-button", disabled: row.in_use.length > 0 || row.default,
          title: row.default ? "It's the default; make another the default first" :
            (row.in_use.length ? "Used by " + row.in_use.join(", ") : null),
          onclick: (e) => askFirst(e.currentTarget, "Take " + (row.label || row.name) + " off the list? Its downloaded " +
            "files stay in models/.", "Remove", () => act(() => api(path, { method: "DELETE" }), "", "Taken off the list.")) },
          "Remove"));
      }
    }
  }
  const facts = [];
  if (!isNew) {
    facts.push(row.shipped ? (row.changed ? "Shipped, changed by you" : "Shipped with Oread") : "Added by you");
    if (kind !== "vad") facts.push(row.in_use.length ? "used by " + row.in_use.join(", ") : "not used");
    else facts.push("used by tools/client.py on the computer it runs on");
    facts.push(row.downloaded ? "downloaded" : "not downloaded yet");
  }
  return h("section", { class: "card panel import", "data-model": entry.name || "" },
    h("div", { class: "person-head" }, h("h2", {}, isNew ? "Add a model" : (entry.label || entry.name)),
      row && row.default ? h("span", { class: "badge" }, "Default") : null),
    isNew ? field("Short name", nameBox, "Lowercase letters, digits, . _ or -. Settings and devices use it; it can't change later.")
      : h("p", { class: "quiet small" }, h("span", { class: "mono" }, entry.name), " \u00B7 ", facts.join(" \u00B7 ")),
    !isNew && (fields.indexOf("url") >= 0) ? h("p", { class: "quiet small" },
      "A changed model reloads on its devices; a changed voice model relearns every voice from the saved clips.") : "",
    h("div", { class: "knobs import-fields" }, parts),
    error, ok,
    buttons.length ? h("div", { class: "row person-actions" }, buttons) : "");
}

// ---------- Setup guide: docs/user-guide.md, shown in the page ----------
// A small Markdown reader for the guide's own Markdown (headings, paragraphs, lists, tables,
// code, quotes, links). Everything goes in as text through h(), never as HTML.

function renderGuide(main) {
  const body = h("article", { class: "guide card" }, h("p", { class: "quiet" }, "Loading…"));
  main.append(body);
  fetch("/guide", { credentials: "same-origin" }).then(async (response) => {
    if (!response.ok) throw new Error("Couldn't load the guide (" + response.status + ")");
    body.replaceChildren(...markdownBlocks((await response.text()).split("\n")));
    const at = hashParams().get("at");
    if (at) guideJump(at);
  }).catch((e) => body.replaceChildren(h("p", { class: "error" }, e.message)));
}

// A "More ›" link to a heading of the Setup guide: the page says it short, the guide says the rest.
function guideMore(heading) {
  return h("a", { class: "guide-more", href: "#/guide?at=" + encodeURIComponent(guideSlug(heading)) }, "More ›");
}

function guideSlug(text) {
  return text.toLowerCase().replace(/[^a-z0-9 -]/g, "").replace(/ /g, "-");
}

function guideJump(slug) {
  const target = document.getElementById("g-" + slug);
  if (target) {
    target.scrollIntoView({ block: "start" });
    target.focus({ preventScroll: true });
  }
}

function markdownInline(text) {
  const out = [];
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\([^)\s]+\))/;
  let rest = text;
  while (rest) {
    const m = rest.match(pattern);
    if (!m) { out.push(rest); break; }
    if (m.index > 0) out.push(rest.slice(0, m.index));
    const token = m[0];
    if (m[1]) out.push(h("code", {}, token.slice(1, -1)));
    else if (m[2]) out.push(h("strong", {}, markdownInline(token.slice(2, -2))));
    else if (m[3]) out.push(h("em", {}, markdownInline(token.slice(1, -1))));
    else {
      const link = token.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
      const href = link[2];
      if (href.charAt(0) === "#") {
        const slug = href.slice(1);
        out.push(h("a", { href: "#/guide?at=" + encodeURIComponent(slug), onclick: (event) => {
          event.preventDefault();
          history.replaceState(null, "", "#/guide?at=" + encodeURIComponent(slug));
          guideJump(slug);
        } }, markdownInline(link[1])));
      } else if (/^https?:\/\//.test(href)) {
        out.push(h("a", { href: href, target: "_blank", rel: "noopener noreferrer" }, markdownInline(link[1])));
      } else {
        out.push(markdownInline(link[1]));
      }
    }
    rest = rest.slice(m.index + token.length);
  }
  return out;
}

function indentOf(line) {
  return line.length - line.replace(/^ +/, "").length;
}

function markdownTable(rows) {
  // no look-behind here (Safari 14 lacks it): park escaped bars, split, put them back
  const cells = (row) => row.trim().replace(/^\|/, "").replace(/\|$/, "").replace(/\\\|/g, "\u0000")
    .split("|").map((c) => c.trim().replace(/\u0000/g, "|"));
  const head = cells(rows[0]);
  return h("div", { class: "table-wrap" }, h("table", { class: "results" },
    h("thead", {}, h("tr", {}, head.map((c) => h("th", {}, markdownInline(c))))),
    h("tbody", {}, rows.slice(2).map((r) => h("tr", {}, cells(r).map((c) => h("td", {}, markdownInline(c))))))));
}

const LIST_ITEM = /^( *)([-*]|\d+\.) +(.*)$/;

function markdownBlocks(lines) {
  const out = [];
  let i = 0;
  const isBlank = (line) => line === undefined || !line.trim();
  while (i < lines.length) {
    const line = lines[i];
    if (isBlank(line)) { i++; continue; }
    const trimmed = line.trim();
    const fence = trimmed.match(/^```(\w*)/);
    if (fence) {
      const indent = indentOf(line);
      const code = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
        code.push(lines[i].slice(Math.min(indent, indentOf(lines[i]))));
        i++;
      }
      i++;
      out.push(h("pre", { class: "code" }, h("code", { "data-lang": fence[1] || null }, code.join("\n"))));
      continue;
    }
    if (/^<!--.*-->$/.test(trimmed)) { i++; continue; }
    if (/^---+$/.test(trimmed)) { out.push(h("hr", {})); i++; continue; }
    const heading = trimmed.match(/^(#{1,6}) +(.*)$/);
    if (heading) {
      const level = heading[1].length;
      out.push(h("h" + Math.min(level, 4), { id: "g-" + guideSlug(heading[2]), tabindex: "-1" },
        markdownInline(heading[2])));
      i++;
      continue;
    }
    if (trimmed.charAt(0) === ">") {
      const quoted = [];
      while (i < lines.length && lines[i].trim().charAt(0) === ">") {
        quoted.push(lines[i].trim().replace(/^> ?/, ""));
        i++;
      }
      out.push(h("blockquote", {}, markdownBlocks(quoted)));
      continue;
    }
    if (trimmed.charAt(0) === "|" && lines[i + 1] && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
      const rows = [];
      while (i < lines.length && lines[i].trim().charAt(0) === "|") { rows.push(lines[i]); i++; }
      out.push(markdownTable(rows));
      continue;
    }
    const item = line.match(LIST_ITEM);
    if (item) {
      const base = item[1].length;
      const ordered = /\d/.test(item[2]);
      const list = h(ordered ? "ol" : "ul", {});
      if (ordered && item[2] !== "1.") list.setAttribute("start", parseInt(item[2], 10));
      while (i < lines.length) {
        const m = lines[i].match(LIST_ITEM);
        if (!m || m[1].length !== base) break;
        const offset = base + m[2].length + 1;
        const content = [m[3]];
        i++;
        while (i < lines.length) {
          const next = lines[i];
          if (isBlank(next)) {
            // a blank line ends the item unless the next text is indented under it
            let j = i + 1;
            while (j < lines.length && isBlank(lines[j])) j++;
            if (j < lines.length && indentOf(lines[j]) > base) { content.push(""); i++; continue; }
            break;
          }
          const nextItem = next.match(LIST_ITEM);
          if (nextItem && nextItem[1].length <= base) break;
          if (!nextItem && indentOf(next) <= base && content.length && !isBlank(content[content.length - 1]) &&
              indentOf(next) === 0 && /^(#|\||>|```)/.test(next.trim())) break;
          content.push(next.slice(Math.min(offset, indentOf(next))));
          i++;
        }
        const inner = markdownBlocks(content);
        const li = h("li", {}, inner.length === 1 && inner[0].tagName === "P" ? Array.from(inner[0].childNodes) : inner);
        list.append(li);
        while (i < lines.length && isBlank(lines[i])) {
          let j = i;
          while (j < lines.length && isBlank(lines[j])) j++;
          const again = lines[j] && lines[j].match(LIST_ITEM);
          if (again && again[1].length === base) { i = j; } else break;
        }
      }
      out.push(list);
      continue;
    }
    const para = [];
    while (i < lines.length && !isBlank(lines[i])) {
      const t = lines[i].trim();
      if (para.length && (/^(#{1,6} |```|>|\|)/.test(t) || LIST_ITEM.test(lines[i]))) break;
      para.push(t);
      i++;
    }
    out.push(h("p", {}, markdownInline(para.join(" "))));
  }
  return out;
}

// ---------- Account: password, theme, sign out ----------

function renderAccount(main) {
  const passwordForm = form([
    field("Current password", input("current", "password", { autocomplete: "current-password" })),
    field("New password", input("new1", "password", { autocomplete: "new-password" }), "At least 10 characters."),
    field("New password again", input("new2", "password", { autocomplete: "new-password" })),
  ], "Change password", async (el, error) => {
    if (value(el, "new1") !== value(el, "new2")) throw new Error("The two new passwords don't match");
    await api("/api/account/password", { method: "POST",
      body: { current: value(el, "current"), new: value(el, "new1") } });
    el.reset();
    error.textContent = "";
    done.textContent = "Password changed. Your other sessions were signed out.";
  });
  checkPasswords(passwordForm, "new1", "new2");
  const done = h("p", { class: "ok", role: "status" });

  main.append(
    h("h1", {}, "Account"),
    h("p", { class: "quiet" }, "Signed in as ", h("strong", {}, session.user.name), " ",
      h("span", { class: "badge" }, session.user.role)),
    h("section", { class: "card panel" }, h("h2", {}, "Password"), passwordForm, done),
    h("section", { class: "card panel" }, h("h2", {}, "Theme"), themeChoices(),
      h("p", { class: "quiet" }, h("small", {}, "Remembered in this browser."))),
    h("section", { class: "card panel" }, h("h2", {}, "Sign out"),
      h("button", { type: "button", onclick: signOut }, "Sign out")));
}

function themeChoices() {
  let current = "device";
  try { current = localStorage.getItem("oread-theme") || "device"; } catch (e) { /* private window */ }
  const options = [["device", "Follow this device"], ["light", "Light"], ["dark", "Dark"]];
  return h("div", { class: "choices", role: "radiogroup", "aria-label": "Theme" },
    options.map(([id, label]) => h("label", {},
      h("input", { type: "radio", name: "theme", value: id, checked: id === current,
        onchange: () => setTheme(id) }), label)));
}

function setTheme(id) {
  const root = document.documentElement;
  if (id === "device") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", id);
  try {
    if (id === "device") localStorage.removeItem("oread-theme");
    else localStorage.setItem("oread-theme", id);
  } catch (e) { /* private window: applies until the page closes */ }
}

async function signOut() {
  try { await api("/api/session", { method: "DELETE" }); } catch (e) { /* signed out anyway */ }
  session = null;
  location.hash = "";
  showSignIn("You're signed out.");
}

window.addEventListener("hashchange", () => { if (session) showFrame(); });
start();
