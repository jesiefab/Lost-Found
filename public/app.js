"use strict";

const OWNER_KEY = "lf-owner-token";
const RENDER_LIMIT = 50; // 275 cards is an INP problem; the count stays exact
const DEBOUNCE_MS = 250;

const $ = (id) => document.getElementById(id);

const els = {
  badge: $("store-badge"),
  detail: $("store-detail"),
  retry: $("retry-db"),
  count: $("item-count"),
  clear: $("clear-samples"),
  openReport: $("open-report"),
  search: $("search"),
  category: $("category"),
  status: $("status"),
  from: $("from"),
  to: $("to"),
  chips: $("chips"),
  suggestions: $("suggestions"),
  results: $("results"),
  resultsCount: $("results-count"),
  resultsNote: $("results-note"),
  equal: $("panel-equal"),
  index: $("panel-index"),
  diagnostics: $("panel-diagnostics"),
  roundTrip: $("round-trip"),
  dialog: $("report-dialog"),
  form: $("report-form"),
  reportError: $("report-error"),
  toast: $("toast"),
};

let controller = null;
let timer = null;
let toastTimer = null;

// --------------------------------------------------------------- helpers
class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body || {};
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  let body = {};
  try {
    body = await response.json();
  } catch {
    body = {};
  }
  if (!response.ok) {
    throw new ApiError(body.error || `HTTP ${response.status}`, response.status, body);
  }
  return body;
}

function ownerToken() {
  let token = localStorage.getItem(OWNER_KEY);
  if (!token) {
    token =
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : `t-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    localStorage.setItem(OWNER_KEY, token);
  }
  return token;
}

// Seed rows are written with a predictable token (sample-001 …) so the demo can
// exercise update and delete on them; they have no real owner.
function tokenFor(item) {
  return item.is_sample ? `sample-${String(item.id).padStart(3, "0")}` : ownerToken();
}

function showToast(message, kind = "info") {
  els.toast.textContent = message;
  els.toast.className =
    "fixed bottom-4 left-1/2 z-50 max-w-xl -translate-x-1/2 rounded-lg px-4 py-2 text-sm shadow-lg " +
    (kind === "error" ? "bg-red-600 text-white" : "bg-slate-900 text-white");
  els.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    els.toast.hidden = true;
  }, 4500);
}

function setText(id, value) {
  const node = $(id);
  if (node) node.textContent = value;
}

// ---------------------------------------------------------------- search
function scheduleSearch() {
  clearTimeout(timer);
  timer = setTimeout(runSearch, DEBOUNCE_MS);
}

async function runSearch() {
  if (controller) controller.abort();
  controller = new AbortController();

  const params = new URLSearchParams();
  const query = els.search.value.trim();
  if (query) params.set("q", query);
  if (els.category.value) params.set("category", els.category.value);
  if (els.status.value) params.set("status", els.status.value);
  if (els.from.value) params.set("from", els.from.value);
  if (els.to.value) params.set("to", els.to.value);

  const started = performance.now();
  try {
    const payload = await api(`/api/search?${params}`, { signal: controller.signal });
    const roundTrip = performance.now() - started;
    renderStore(payload.store);
    renderResults(payload);
    renderPanel(payload, roundTrip);
    loadSuggestions(query);
  } catch (error) {
    if (error.name === "AbortError") return;
    showToast(error.message, "error");
  }
}

async function loadSuggestions(query) {
  const token = (query.split(/\s+/)[0] || "").toLowerCase();
  if (token.length < 2) {
    els.suggestions.textContent = "type to see suggestions";
    return;
  }
  try {
    const data = await api(`/api/suggest?prefix=${encodeURIComponent(token.slice(0, 16))}`);
    els.suggestions.replaceChildren();
    if (!data.suggestions.length) {
      els.suggestions.textContent = "no terms under that prefix";
      return;
    }
    for (const suggestion of data.suggestions) {
      const row = document.createElement("button");
      row.type = "button";
      row.className =
        "flex w-full items-baseline justify-between gap-2 rounded px-1 py-0.5 text-left hover:bg-slate-100";
      const term = document.createElement("span");
      term.className = "truncate text-sm text-slate-700";
      term.textContent = suggestion.term;
      const df = document.createElement("span");
      df.className = "font-mono text-[11px] tabular-nums text-slate-500";
      df.textContent = suggestion.df;
      row.append(term, df);
      row.addEventListener("click", () => {
        els.search.value = suggestion.term;
        runSearch();
      });
      els.suggestions.append(row);
    }
  } catch {
    els.suggestions.textContent = "suggestions unavailable";
  }
}

// --------------------------------------------------------------- renders
function renderStore(store) {
  if (!store) return;
  const degraded = Boolean(store.degraded);
  els.badge.textContent = `source: ${degraded ? "snapshot — database unreachable" : store.source}`;
  els.badge.className = degraded
    ? "rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-900"
    : "rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-800";
  els.detail.textContent = store.reason || (store.writable ? "read-write" : "read-only");
  els.retry.classList.toggle("hidden", !degraded);
}

function renderResults(payload) {
  els.results.replaceChildren();
  els.count.textContent = payload.count;
  els.resultsCount.textContent = `${payload.count} ${payload.count === 1 ? "result" : "results"}`;

  if (!payload.count) {
    const empty = document.createElement("p");
    empty.className = "rounded-lg border border-dashed border-slate-300 px-3 py-6 text-sm text-slate-500";
    empty.textContent =
      payload.mode === "browse"
        ? "The board is empty. Clear sample rows removed everything — report an item to start again."
        : "Nothing matches. Prefix matching means “payo” finds “payong”, but “yong” does not.";
    els.results.append(empty);
    els.resultsNote.textContent = "";
    return;
  }

  const shown = payload.items.slice(0, RENDER_LIMIT);
  els.resultsNote.textContent =
    payload.count > shown.length
      ? `showing ${shown.length} of ${payload.count} — the panel's numbers describe all ${payload.count}`
      : payload.mode === "browse"
        ? "browse order, newest first"
        : "";

  for (const item of shown) els.results.append(card(item));
}

function action(label, onClick, danger = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.className = danger
    ? "rounded border border-red-200 px-2 py-0.5 text-[11px] font-medium text-red-700 hover:bg-red-50"
    : "rounded border border-slate-300 px-2 py-0.5 text-[11px] font-medium text-slate-700 hover:bg-slate-100";
  button.addEventListener("click", onClick);
  return button;
}

function card(item) {
  const article = document.createElement("article");
  article.className = "rounded-lg border border-slate-200 bg-white p-3 shadow-sm";

  const head = document.createElement("div");
  head.className = "flex flex-wrap items-start gap-2";

  const kind = document.createElement("span");
  kind.textContent = item.kind;
  kind.className =
    item.kind === "lost"
      ? "rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-800"
      : "rounded bg-emerald-100 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-emerald-800";

  const title = document.createElement("h3");
  title.className = "min-w-0 flex-1 text-sm font-semibold leading-snug";
  title.textContent = item.title;

  const status = document.createElement("span");
  status.textContent = `${item.status} · #${item.id}`;
  status.className = "rounded-full border border-slate-200 px-2 py-0.5 text-[11px] text-slate-600";

  head.append(kind, title, status);

  const meta = document.createElement("p");
  meta.className = "mt-1 text-xs text-slate-500";
  meta.textContent = [
    item.category,
    item.location,
    item.date_iso,
    item.reporter ? `by ${item.reporter}` : "",
  ]
    .filter(Boolean)
    .join(" · ");

  article.append(head, meta);

  if (item.description) {
    const body = document.createElement("p");
    body.className = "mt-1 line-clamp-2 text-sm text-slate-700";
    body.textContent = item.description;
    article.append(body);
  }

  if (item.tags && item.tags.length) {
    const tags = document.createElement("p");
    tags.className = "mt-1 flex flex-wrap gap-1";
    for (const tag of item.tags) {
      const pill = document.createElement("span");
      pill.className = "rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600";
      pill.textContent = tag;
      tags.append(pill);
    }
    article.append(tags);
  }

  const actions = document.createElement("div");
  actions.className = "mt-2 flex flex-wrap gap-1.5";
  actions.append(
    action("I think this is mine", () => setStatus(item, "claimed")),
    action("Returned", () => setStatus(item, "returned")),
    action("Delete", () => removeItem(item), true),
  );
  article.append(actions);
  return article;
}

function renderPanel(payload, roundTrip) {
  const indexed = payload.indexed;
  const linear = payload.linear;

  setText("panel-indexed-exam", indexed ? indexed.items_examined : "—");
  setText("panel-indexed-ms", indexed ? `${indexed.compute_ms.toFixed(2)} ms` : "—");
  setText("panel-linear-exam", linear ? linear.items_examined : "—");
  setText("panel-linear-ms", linear ? `${linear.compute_ms.toFixed(2)} ms` : "—");
  setText(
    "panel-ratio-items",
    payload.ratio && payload.ratio.items ? `${payload.ratio.items.toFixed(1)}×` : "—",
  );
  setText(
    "panel-ratio-time",
    payload.ratio && payload.ratio.time ? `${payload.ratio.time.toFixed(1)}×` : "—",
  );

  if (payload.equal === null) {
    els.equal.textContent = payload.note || "no query tokens — browse, not search results";
    els.equal.className = "mt-3 rounded-md bg-slate-100 px-2.5 py-1.5 text-xs text-slate-600";
  } else if (payload.equal) {
    els.equal.textContent = `OK — same ${payload.count} result${payload.count === 1 ? "" : "s"}`;
    els.equal.className =
      "mt-3 rounded-md bg-emerald-50 px-2.5 py-1.5 text-xs font-medium text-emerald-800";
  } else {
    const onlyIndexed = payload.mismatch.only_indexed.join(", ") || "none";
    const onlyLinear = payload.mismatch.only_linear.join(", ") || "none";
    els.equal.textContent = `MISMATCH — only indexed: ${onlyIndexed} · only linear: ${onlyLinear}`;
    els.equal.className =
      "mt-3 rounded-md bg-red-50 px-2.5 py-1.5 text-xs font-semibold text-red-800";
  }

  const stats = payload.index_stats || {};
  els.index.textContent =
    `index: ${stats.terms ?? "—"} terms · ${stats.postings ?? "—"} postings · ` +
    `${stats.trie_nodes ?? "—"} trie nodes · rebuild ${Number(stats.build_ms ?? 0).toFixed(0)} ms ` +
    `for ${stats.documents ?? payload.corpus_size} rows`;

  els.diagnostics.replaceChildren();
  for (const [name, values] of [
    ["indexed", indexed && indexed.diagnostics],
    ["linear", linear && linear.diagnostics],
  ]) {
    if (!values) continue;
    const row = document.createElement("div");
    row.className = "flex flex-wrap gap-x-2 gap-y-0.5 font-mono text-[11px] text-slate-500";
    const label = document.createElement("span");
    label.className = "text-slate-400";
    label.textContent = name;
    row.append(label);
    for (const [key, value] of Object.entries(values)) {
      const item = document.createElement("span");
      item.textContent = `${key.replace(/_/g, " ")} ${value}`;
      row.append(item);
    }
    els.diagnostics.append(row);
  }

  els.roundTrip.textContent = `round trip ${roundTrip.toFixed(0)} ms (this browser, network included)`;
}

// --------------------------------------------------------------- actions
async function setStatus(item, status) {
  try {
    await api(`/api/items/${item.id}`, {
      method: "PATCH",
      body: JSON.stringify({ status, owner_token: tokenFor(item) }),
    });
    showToast(`#${item.id} marked ${status}`);
    runSearch();
  } catch (error) {
    const unknown = error.body && error.body.outcome_unknown;
    showToast(
      unknown
        ? `${error.message} — the write may have landed; reload when the database answers`
        : error.message,
      "error",
    );
  }
}

async function removeItem(item) {
  if (!window.confirm(`Delete #${item.id} “${item.title}”?`)) return;
  try {
    await api(`/api/items/${item.id}?token=${encodeURIComponent(tokenFor(item))}`, {
      method: "DELETE",
    });
    showToast(`#${item.id} deleted`);
    runSearch();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function retryDatabase() {
  try {
    const data = await api("/api/health?force=1");
    renderStore(data.store);
    showToast(data.store.degraded ? "Still unreachable — staying on the snapshot" : "Back on the database");
    runSearch();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function clearSamples() {
  if (!window.confirm("Delete all 500 sample rows? Real rows are kept.")) return;
  try {
    const data = await api("/api/samples/clear", { method: "POST" });
    showToast(`Removed ${data.removed} sample rows`);
    runSearch();
  } catch (error) {
    showToast(error.message, "error");
  }
}

// ----------------------------------------------------------------- wiring
function openReport() {
  els.reportError.classList.add("hidden");
  els.form.reset();
  els.form.elements.date_iso.value = new Date().toISOString().slice(0, 10);
  els.dialog.showModal();
  els.form.elements.title.focus();
}

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(els.form));
  data.tags = String(data.tags || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
  data.owner_token = ownerToken();

  try {
    const created = await api("/api/items", { method: "POST", body: JSON.stringify(data) });
    els.dialog.close();
    showToast(`Reported #${created.item.id}`);
    runSearch();
  } catch (error) {
    els.reportError.textContent = error.message;
    els.reportError.classList.remove("hidden");
  }
});

els.search.addEventListener("input", scheduleSearch);
for (const filter of [els.category, els.status, els.from, els.to]) {
  filter.addEventListener("change", runSearch);
}
els.chips.addEventListener("click", (event) => {
  const chip = event.target.closest("button[data-q]");
  if (!chip) return;
  for (const other of els.chips.querySelectorAll("button")) {
    other.classList.remove("chip-active");
  }
  chip.classList.add("chip-active");
  els.search.value = chip.dataset.q;
  runSearch();
});
els.openReport.addEventListener("click", openReport);
$("close-report").addEventListener("click", () => els.dialog.close());
$("cancel-report").addEventListener("click", () => els.dialog.close());
els.retry.addEventListener("click", retryDatabase);
els.clear.addEventListener("click", clearSamples);

ownerToken();
runSearch();
