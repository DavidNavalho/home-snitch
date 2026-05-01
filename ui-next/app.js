// Flashy console UI for Home Wiki. Reuses the existing API client and fixtures
// from /ui/src/* so the API contract stays identical to the original UI.
import {
  DEFAULT_API_BASE,
  createApiClient,
  normalizeApiBase,
  normalizeApiError,
  probeApiStatus
} from "/ui/src/api.js";
import { buildCreateDevicePayload } from "/ui/src/device.js";

const CONFIG_KEY = "homeWikiUiNextConfig";

const DEVICE_ICONS = {
  dishwasher: "🫧",
  router: "📡",
  oven: "🔥",
  fridge: "❄️",
  washer: "🧺",
  tv: "📺",
  thermostat: "🌡️",
  vacuum: "🤖"
};

function deviceIcon(type) {
  return DEVICE_ICONS[(type || "").toLowerCase()] || "🔌";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function jsonBlock(value) {
  return `<pre class="json-block">${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
}

function timeNow() {
  const d = new Date();
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

async function loadRuntimeDefaults() {
  try {
    const r = await fetch("/ui-config.json", { headers: { accept: "application/json" } });
    if (!r.ok) return {};
    return await r.json();
  } catch {
    return {};
  }
}

function loadConfig(runtime = {}) {
  const params = new URLSearchParams(globalThis.location?.search ?? "");
  let saved = {};
  try { saved = JSON.parse(globalThis.localStorage?.getItem(CONFIG_KEY) ?? "{}"); } catch {}
  return {
    mode: params.get("mode") || saved.mode || "mock",
    apiBase: normalizeApiBase(params.get("apiBase") || saved.apiBase || runtime.apiBase || DEFAULT_API_BASE)
  };
}
function saveConfig(cfg) {
  globalThis.localStorage?.setItem(CONFIG_KEY, JSON.stringify(cfg));
}

const state = {
  config: loadConfig(),
  status: { available: null, message: "Checking…", counts: null },
  mode: "ask", // ask | search | manuals
  selectedAssetId: "",
  devices: [],
  thread: [], // {kind, ...}
  lastResolution: null
};

let api = createApiClient(state.config);

// ---- DOM helpers ---------------------------------------------------------
const $ = (sel) => document.querySelector(sel);
const threadEl = () => $("#thread");
const inspectorEl = () => $("#inspector-body");

function toast(message, tone = "") {
  const wrap = $("#toasts");
  const el = document.createElement("div");
  el.className = `toast ${tone}`;
  el.innerHTML = `<span>${escapeHtml(message)}</span><span class="x" data-action="dismiss-toast">×</span>`;
  wrap.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

// ---- Status & devices ----------------------------------------------------
function renderStatus() {
  const modeEl = $("#status-mode");
  const apiEl = $("#status-api");
  const countsEl = $("#status-counts");
  modeEl.textContent = state.config.mode === "live" ? "live" : "mock";
  modeEl.parentElement.querySelector(".dot").className =
    "dot " + (state.config.mode === "live" ? "" : "dot-amber");

  const tone =
    state.status.available === false ? "dot-red" :
    state.status.available ? "" : "dot-amber";
  apiEl.innerHTML = `<span class="dot ${tone}"></span>${escapeHtml(state.status.message)}`;
  if (state.status.counts) {
    const { devices, indexed } = state.status.counts;
    countsEl.textContent = `${devices ?? "—"} devices · ${indexed ?? "—"} indexed`;
  } else {
    countsEl.textContent = `${state.devices.length || "—"} devices`;
  }
}

function renderDevices() {
  const list = $("#device-list");
  if (!state.devices.length) {
    list.innerHTML = `<div class="empty-soft">No devices yet.</div>`;
    return;
  }
  list.innerHTML = state.devices.map((d) => {
    const selected = d.asset_id === state.selectedAssetId ? " selected" : "";
    return `<button class="device-card${selected}" data-action="select-device" data-asset-id="${escapeHtml(d.asset_id)}">
      <div class="dev-icon">${deviceIcon(d.device_type)}</div>
      <div>
        <div class="dev-name">${escapeHtml(d.brand)} ${escapeHtml(d.model)}</div>
        <div class="dev-meta">${escapeHtml(d.device_type)} · ${escapeHtml(d.room || "—")}</div>
        <div class="dev-id">${escapeHtml(d.asset_id)}</div>
      </div>
    </button>`;
  }).join("");
}

function renderScopeTag() {
  const tag = $("#scope-tag");
  const label = $("#scope-tag-label");
  if (!state.selectedAssetId) {
    tag.hidden = true;
    return;
  }
  const dev = state.devices.find((d) => d.asset_id === state.selectedAssetId);
  label.textContent = dev ? `${dev.brand} ${dev.model}` : state.selectedAssetId;
  tag.hidden = false;
}

function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll(".mode-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.mode === mode);
  });
  const input = $("#hero-input");
  if (mode === "ask") input.placeholder = "Ask anything about a device — e.g. What does E15 mean?";
  if (mode === "search") input.placeholder = "Search the wiki — e.g. dishwasher error codes";
  if (mode === "manuals") input.placeholder = "Find a manual — e.g. Bosch SMS6ZCW00G";
}

// ---- Thread rendering ----------------------------------------------------
function clearThreadEmpty() {
  const empty = $("#thread-empty");
  if (empty) empty.remove();
}

function pushUserCard(query, modeLabel) {
  clearThreadEmpty();
  const el = document.createElement("article");
  el.className = "card user-card";
  el.innerHTML = `
    <div class="card-head">
      <span class="who">You</span>
      <span class="chip info">${escapeHtml(modeLabel)}</span>
      <span class="when">${timeNow()}</span>
    </div>
    <div class="query">${escapeHtml(query)}</div>
  `;
  threadEl().appendChild(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
}

function pendingAnswerCard(label) {
  clearThreadEmpty();
  const el = document.createElement("article");
  el.className = "card answer-card";
  el.innerHTML = `
    <div class="card-head">
      <span class="who">${escapeHtml(label)}</span>
      <span class="chip">running…</span>
      <span class="when">${timeNow()}</span>
    </div>
    <p class="answer"><span class="cursor"></span></p>
  `;
  threadEl().appendChild(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
  return el;
}

function typewrite(targetEl, text, speed = 14) {
  return new Promise((resolve) => {
    let i = 0;
    const step = () => {
      if (i > text.length) return resolve();
      targetEl.innerHTML = `${escapeHtml(text.slice(0, i))}<span class="cursor"></span>`;
      i += Math.max(1, Math.round(text.length / 240));
      requestAnimationFrame(() => setTimeout(step, speed));
    };
    step();
  });
}

function scopeChips(resolution, scope) {
  if (!resolution) return "";
  const tone =
    resolution.status === "exact" ? "ok" :
    resolution.status === "ambiguous" ? "warn" :
    resolution.status === "none" ? "bad" : "info";
  const scopeTone = scope === "device" ? "ok" : scope === "global" ? "info" : "";
  const conf = typeof resolution.confidence === "number"
    ? `${Math.round(resolution.confidence * 100)}%` : "—";
  const filters = resolution.filters || {};
  const filterText = Object.entries(filters)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${k}: ${v}`).join(" · ");
  return `
    <div class="chips">
      <span class="chip ${tone}">resolution · ${escapeHtml(resolution.status)}</span>
      ${scope ? `<span class="chip ${scopeTone}">scope · ${escapeHtml(scope)}</span>` : ""}
      <span class="chip">confidence · ${escapeHtml(conf)}</span>
      ${resolution.asset_id ? `<span class="chip"><code>${escapeHtml(resolution.asset_id)}</code></span>` : ""}
      ${(resolution.matched_on || []).length ? `<span class="chip">matched · ${escapeHtml(resolution.matched_on.join(", "))}</span>` : ""}
      ${filterText ? `<span class="chip">filters · ${escapeHtml(filterText)}</span>` : ""}
    </div>`;
}

function candidateButtons(candidates, target) {
  if (!candidates?.length) return "";
  const items = candidates.map((c) => {
    const conf = typeof c.confidence === "number" ? `${Math.round(c.confidence * 100)}%` : "?";
    return `<button class="candidate-btn" data-action="choose-candidate" data-target="${escapeHtml(target)}" data-asset-id="${escapeHtml(c.asset_id)}">
      <div class="dev-icon">${deviceIcon(c.device_type)}</div>
      <div>
        <div class="dev-name">${escapeHtml(c.brand || "Unknown")} ${escapeHtml(c.model || "")}</div>
        <div class="dev-meta">${escapeHtml(c.device_type || "")} · ${escapeHtml(c.room || "—")} · <code>${escapeHtml(c.asset_id)}</code></div>
      </div>
      <span class="conf">${escapeHtml(conf)}</span>
    </button>`;
  }).join("");
  return `<div class="candidates">${items}</div>`;
}

function evidenceList(evidence) {
  if (!evidence?.length) return "";
  return `<div class="evidence">
    <h4>Evidence</h4>
    ${evidence.map((e) => `
      <div class="evidence-item">
        <div class="card-head" style="margin:0">
          <span class="who">${escapeHtml(e.section_title || "section")}</span>
          <span class="chip">${escapeHtml(e.source_type || "source")}</span>
          ${typeof e.score === "number" ? `<span class="score-bar"><span class="bar"><span style="width:${Math.min(100, Math.round(e.score * 100))}%"></span></span><code>${e.score.toFixed(2)}</code></span>` : ""}
        </div>
        <div class="path">${escapeHtml(e.markdown_path || e.source_path || "")}</div>
        <div class="snip">${escapeHtml(e.text || "")}</div>
      </div>
    `).join("")}
  </div>`;
}

function searchResultsBlock(results, scope) {
  if (!results?.length) return `<div class="empty-soft" style="margin-top:10px">No results.</div>`;
  return `<div class="result-grid">
    ${results.map((r) => `
      <div class="result-row">
        <div>
          <div class="title">${escapeHtml(r.section_title || "section")}</div>
          <div class="meta"><code>${escapeHtml(r.asset_id || "global")}</code> · ${escapeHtml(r.source_type || "source")}${typeof r.score === "number" ? ` · score ${r.score.toFixed(2)}` : ""}</div>
          <div class="text">${escapeHtml(r.text || "")}</div>
        </div>
        <div>
          <span class="chip ${scope === "device" ? "ok" : "info"}">${escapeHtml(scope || "scope")}</span>
        </div>
      </div>
    `).join("")}
  </div>`;
}

// ---- Inspector -----------------------------------------------------------
function renderInspector(payload) {
  const body = inspectorEl();
  if (!payload) {
    body.innerHTML = `<div class="empty-soft">No request yet.</div>`;
    return;
  }
  const r = payload.resolution || {};
  const conf = typeof r.confidence === "number" ? r.confidence : 0;
  body.innerHTML = `
    <div class="scope-viz">
      <span class="label">Resolution confidence</span>
      <div class="bar"><span style="width:${Math.round(conf * 100)}%"></span></div>
      <div class="kvs">
        <div class="kv"><span class="k">status</span><span class="v">${escapeHtml(r.status || "—")}</span></div>
        <div class="kv"><span class="k">scope</span><span class="v">${escapeHtml(payload.scope || "—")}</span></div>
        <div class="kv"><span class="k">asset</span><span class="v">${escapeHtml(r.asset_id || "—")}</span></div>
        <div class="kv"><span class="k">matched</span><span class="v">${escapeHtml((r.matched_on || []).join(", ") || "—")}</span></div>
      </div>
    </div>
    ${jsonBlock(payload)}
  `;
}

// ---- Status & devices loaders -------------------------------------------
async function refreshClient() { api = createApiClient(state.config); }

async function checkStatus() {
  state.status = { available: null, message: "Checking…", counts: null };
  renderStatus();
  if (state.config.mode === "mock") {
    try {
      await probeApiStatus({ baseUrl: state.config.apiBase });
      state.status = { available: true, message: `mock · live API up` };
    } catch (err) {
      const n = normalizeApiError(err);
      state.status = { available: false, message: `mock · ${n.code}` };
    }
    renderStatus();
    return;
  }
  try {
    const status = await api.status();
    state.status = {
      available: true,
      message: "live API up",
      counts: { devices: status.devices, indexed: status.indexed }
    };
  } catch (err) {
    const n = normalizeApiError(err);
    state.status = { available: false, message: n.message };
  }
  renderStatus();
}

async function refreshDevices() {
  try {
    const payload = await api.getDevices();
    state.devices = payload.devices ?? [];
  } catch (err) {
    const n = normalizeApiError(err);
    toast(n.message, "bad");
  }
  renderDevices();
  renderStatus();
}

// ---- Actions -------------------------------------------------------------
async function runAsk(question) {
  pushUserCard(question, "ASK");
  const card = pendingAnswerCard("Wiki");
  try {
    const response = await api.ask({
      question,
      asset_id: state.selectedAssetId || null,
      limit: 8,
      allow_global_fallback: !state.selectedAssetId
    });
    state.lastResolution = response;
    renderInspector(response);
    finalizeAskCard(card, response);
  } catch (err) {
    const n = normalizeApiError(err);
    failCard(card, n);
  }
}

async function runSearch(query) {
  pushUserCard(query, "SEARCH");
  const card = pendingAnswerCard("Search");
  try {
    const response = await api.search({
      query,
      asset_id: state.selectedAssetId || null,
      filters: null,
      limit: 8,
      allow_global_fallback: true
    });
    state.lastResolution = response;
    renderInspector(response);
    finalizeSearchCard(card, response);
  } catch (err) {
    const n = normalizeApiError(err);
    failCard(card, n);
  }
}

async function runManuals(query) {
  pushUserCard(query, "MANUALS");
  const card = pendingAnswerCard("Manuals");
  try {
    const response = await api.findManuals({
      asset_id: state.selectedAssetId || null,
      query
    });
    finalizeManualsCard(card, response);
  } catch (err) {
    const n = normalizeApiError(err);
    failCard(card, n);
  }
}

async function finalizeAskCard(card, response) {
  const head = card.querySelector(".card-head");
  const body = card.querySelector(".answer");
  const ambiguous = response.resolution?.status === "ambiguous";
  const generated = response.generated;

  head.innerHTML = `
    <span class="who">Wiki</span>
    <span class="chip ${generated ? "info" : "ok"}">${generated ? "generated" : "evidence-only"}</span>
    <span class="chip">confidence · ${escapeHtml(response.confidence ?? 0)}/10</span>
    <span class="when">${timeNow()}</span>
  `;

  if (ambiguous) {
    body.innerHTML = `<em style="color:var(--warn)">Multiple devices match — pick one to scope the answer.</em>`;
    card.insertAdjacentHTML("beforeend", scopeChips(response.resolution));
    card.insertAdjacentHTML("beforeend", candidateButtons(response.resolution.candidates, "ask"));
    return;
  }
  await typewrite(body, response.answer || "(no answer)", 12);
  body.innerHTML = escapeHtml(response.answer || "(no answer)");
  card.insertAdjacentHTML("beforeend", scopeChips(response.resolution));
  if (response.missing_information?.length) {
    card.insertAdjacentHTML("beforeend", `<div class="chip warn" style="margin-top:8px">missing · ${escapeHtml(response.missing_information.join("; "))}</div>`);
  }
  card.insertAdjacentHTML("beforeend", evidenceList(response.evidence));
}

function finalizeSearchCard(card, response) {
  const head = card.querySelector(".card-head");
  const body = card.querySelector(".answer");
  const scope = response.scope;
  head.innerHTML = `
    <span class="who">Search</span>
    <span class="chip ${scope === "device" ? "ok" : "info"}">scope · ${escapeHtml(scope || "—")}</span>
    <span class="chip">${response.results?.length ?? 0} hits</span>
    <span class="when">${timeNow()}</span>
  `;
  body.outerHTML = "";

  let html = scopeChips(response.resolution, scope);
  if (response.resolution?.status === "ambiguous") {
    html += `<div class="chip warn" style="margin:8px 0">choose a device to scope the search</div>`;
    html += candidateButtons(response.resolution.candidates, "search");
  } else {
    html += searchResultsBlock(response.results, scope);
  }
  card.insertAdjacentHTML("beforeend", html);
}

function finalizeManualsCard(card, response) {
  const head = card.querySelector(".card-head");
  const body = card.querySelector(".answer");
  head.innerHTML = `
    <span class="who">Manuals</span>
    <span class="chip">${(response.candidates || []).length} candidates</span>
    <span class="when">${timeNow()}</span>
  `;
  body.outerHTML = "";
  const items = (response.candidates || []).map((c) => `
    <div class="manual-row">
      <div>
        <div class="title">${escapeHtml(c.title || "manual")}</div>
        <div class="url">${escapeHtml(c.url)}</div>
        <div class="meta" style="color:var(--muted);font-size:12px;margin-top:2px">rank ${escapeHtml(c.rank ?? "?")} · host ${escapeHtml(c.source_host || "—")} · <code>${escapeHtml(c.asset_id || "—")}</code></div>
      </div>
      <button class="ghost" data-action="download-manual" data-asset-id="${escapeHtml(c.asset_id || state.selectedAssetId)}" data-url="${escapeHtml(c.url)}">⬇ Download</button>
    </div>
  `).join("");
  card.insertAdjacentHTML("beforeend", items || `<div class="empty-soft">No candidates returned.</div>`);
}

function failCard(card, err) {
  card.classList.add("error-card");
  const head = card.querySelector(".card-head");
  const body = card.querySelector(".answer");
  head.innerHTML = `<span class="who">Error</span><span class="chip bad">${escapeHtml(err.code || "api_error")}</span><span class="when">${timeNow()}</span>`;
  body.innerHTML = escapeHtml(err.message || "Request failed.");
  if (err.details) card.insertAdjacentHTML("beforeend", jsonBlock(err.details));
}

// ---- Modal helpers -------------------------------------------------------
function openSettings() {
  $("#mode-select").value = state.config.mode;
  $("#api-base-input").value = state.config.apiBase;
  $("#settings-modal").showModal();
}
function openDevice() { $("#device-modal").showModal(); }

// ---- Event wiring --------------------------------------------------------
document.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;

  if (form.id === "hero-form") {
    const q = $("#hero-input").value.trim();
    if (!q) return;
    $("#hero-input").value = "";
    if (state.mode === "ask") return runAsk(q);
    if (state.mode === "search") return runSearch(q);
    if (state.mode === "manuals") return runManuals(q);
  }

  if (form.id === "settings-form") {
    const fd = new FormData(form);
    state.config = {
      mode: fd.get("mode") === "live" ? "live" : "mock",
      apiBase: normalizeApiBase(fd.get("apiBase"))
    };
    saveConfig(state.config);
    refreshClient();
    $("#settings-modal").close();
    toast("Settings saved", "ok");
    await checkStatus();
    await refreshDevices();
    return;
  }

  if (form.id === "device-form") {
    const fd = Object.fromEntries(new FormData(form).entries());
    const payload = buildCreateDevicePayload(fd);
    try {
      const r = await api.createDevice(payload);
      const device = r.device ?? r;
      state.devices = [...state.devices.filter((d) => d.asset_id !== device.asset_id), device];
      renderDevices();
      $("#device-modal").close();
      form.reset();
      toast(`Added ${device.brand || ""} ${device.model || ""}`.trim(), "ok");
    } catch (err) {
      toast(normalizeApiError(err).message, "bad");
    }
  }
});

document.addEventListener("click", async (event) => {
  const btn = event.target.closest("[data-action]");
  if (!btn) return;
  const a = btn.dataset.action;

  if (a === "select-device") {
    const id = btn.dataset.assetId;
    state.selectedAssetId = state.selectedAssetId === id ? "" : id;
    renderDevices();
    renderScopeTag();
    return;
  }
  if (a === "clear-scope") {
    state.selectedAssetId = "";
    renderDevices();
    renderScopeTag();
    return;
  }
  if (a === "refresh-devices") {
    await refreshDevices();
    toast("Devices refreshed", "ok");
    return;
  }
  if (a === "open-settings") return openSettings();
  if (a === "close-settings") return $("#settings-modal").close();
  if (a === "check-status") {
    await checkStatus();
    toast(state.status.message, state.status.available ? "ok" : "bad");
    return;
  }
  if (a === "add-device") return openDevice();
  if (a === "close-device") return $("#device-modal").close();
  if (a === "run-ingest") {
    toast("Running ingest…");
    try {
      const report = await api.ingest({});
      const status = await api.status();
      state.status.counts = { devices: status.devices, indexed: status.indexed };
      renderStatus();
      const card = pendingAnswerCard("Ingest");
      const head = card.querySelector(".card-head");
      head.innerHTML = `<span class="who">Ingest</span><span class="chip ok">complete</span><span class="when">${timeNow()}</span>`;
      card.querySelector(".answer").outerHTML = "";
      const metrics = ["converted", "indexed", "skipped", "failed", "removed"]
        .map((k) => `<div class="metric"><strong>${escapeHtml(report[k] ?? 0)}</strong><span>${escapeHtml(k)}</span></div>`).join("");
      card.insertAdjacentHTML("beforeend", `<div class="metric-grid">${metrics}</div>`);
      toast("Ingest complete", "ok");
    } catch (err) {
      toast(normalizeApiError(err).message, "bad");
    }
    return;
  }
  if (a === "choose-candidate") {
    state.selectedAssetId = btn.dataset.assetId;
    renderDevices();
    renderScopeTag();
    const target = btn.dataset.target;
    const lastUser = [...threadEl().querySelectorAll(".user-card .query")].pop();
    const q = lastUser ? lastUser.textContent : "";
    if (!q) return;
    if (target === "ask") return runAsk(q);
    if (target === "search") return runSearch(q);
    return;
  }
  if (a === "download-manual") {
    try {
      const result = await api.downloadManual({
        asset_id: btn.dataset.assetId,
        url: btn.dataset.url
      });
      toast(result.downloaded ? `Saved ${result.saved_path}` : (result.error || "Download failed"), result.downloaded ? "ok" : "bad");
    } catch (err) {
      toast(normalizeApiError(err).message, "bad");
    }
    return;
  }
  if (a === "dismiss-toast") {
    btn.closest(".toast")?.remove();
    return;
  }
});

document.addEventListener("click", (event) => {
  const m = event.target.closest(".mode-btn");
  if (m) setMode(m.dataset.mode);
  const hint = event.target.closest(".hint");
  if (hint) {
    $("#hero-input").value = hint.dataset.hint;
    $("#hero-input").focus();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "/" && !event.metaKey && !event.ctrlKey) {
    const tag = (event.target.tagName || "").toLowerCase();
    if (tag !== "input" && tag !== "textarea") {
      event.preventDefault();
      $("#hero-input").focus();
    }
  } else if (event.key === "Escape") {
    if ($("#hero-input") === document.activeElement) {
      $("#hero-input").value = "";
    }
  } else if ((event.metaKey || event.ctrlKey) && event.key === ",") {
    event.preventDefault();
    openSettings();
  }
});

// click on dialog backdrop closes it
for (const id of ["settings-modal", "device-modal"]) {
  const dlg = document.getElementById(id);
  dlg?.addEventListener("click", (e) => {
    const r = dlg.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) {
      dlg.close();
    }
  });
}

async function init() {
  state.config = loadConfig(await loadRuntimeDefaults());
  refreshClient();
  setMode("ask");
  renderStatus();
  renderDevices();
  await Promise.all([checkStatus(), refreshDevices()]);
}

init();
