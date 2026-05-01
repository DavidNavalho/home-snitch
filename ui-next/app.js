// Factory floor console UI. Reuses the existing API client and fixtures
// from /ui/src/* for ask/search/manuals/devices, and adds three demo flows:
// Incident (hero, POST /agent/incident), PM (templated /ask), Compliance (global /search).
import {
  DEFAULT_API_BASE,
  createApiClient,
  normalizeApiBase,
  normalizeApiError,
  probeApiStatus,
  requestJson
} from "/ui/src/api.js";
import { buildCreateDevicePayload } from "/ui/src/device.js";

const CONFIG_KEY = "homeWikiUiNextConfig";

const DEVICE_ICONS = {
  vfd: "⚡",
  drive: "⚡",
  plc: "🧠",
  controller: "🧠",
  robot: "🦾",
  sensor: "📍",
  vision: "👁",
  conveyor: "🛞",
  cnc: "🛠",
  valve: "🔧",
  regulator: "🔧",
  // legacy home types fallthrough
  dishwasher: "🫧",
  router: "📡"
};

function deviceIcon(type) {
  const key = (type || "").toLowerCase();
  if (DEVICE_ICONS[key]) return DEVICE_ICONS[key];
  for (const [k, v] of Object.entries(DEVICE_ICONS)) {
    if (key.includes(k)) return v;
  }
  return "🔌";
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
  view: "incident", // incident | pm | compliance | tools
  mode: "ask",      // tools sub-mode: ask | search | manuals
  selectedAssetId: "",
  devices: [],
  alerts: [],
  thread: [],
  lastResolution: null
};

function makeClient(cfg) {
  return createApiClient({ baseUrl: cfg.apiBase, mode: cfg.mode });
}
let api = makeClient(state.config);

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

// ---- Status -------------------------------------------------------------
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
    countsEl.textContent = `${devices ?? "—"} assets · ${indexed ?? "—"} indexed`;
  } else {
    countsEl.textContent = `${state.devices.length || "—"} assets`;
  }
}

// ---- Device tree --------------------------------------------------------
function buildTree(devices) {
  // Group by `room` interpreted as a slash-separated path. Devices without a
  // path land under "Unassigned".
  const root = { name: "", children: new Map(), devices: [] };
  for (const d of devices) {
    const parts = String(d.room || "Unassigned").split("/").map((s) => s.trim()).filter(Boolean);
    let node = root;
    for (const part of parts) {
      if (!node.children.has(part)) {
        node.children.set(part, { name: part, children: new Map(), devices: [] });
      }
      node = node.children.get(part);
    }
    node.devices.push(d);
  }
  return root;
}

function renderTreeNode(node, depth = 0) {
  const childKeys = [...node.children.keys()].sort();
  const groups = childKeys.map((k) => {
    const child = node.children.get(k);
    const inner = renderTreeNode(child, depth + 1);
    return `<details class="tree-group" open>
      <summary class="tree-summary" style="padding-left:${depth * 10}px">
        <span class="caret"></span><span class="tree-label">${escapeHtml(k)}</span>
      </summary>
      <div class="tree-children">${inner}</div>
    </details>`;
  }).join("");
  const leaves = node.devices.map((d) => {
    const sel = d.asset_id === state.selectedAssetId ? " selected" : "";
    return `<button class="device-card${sel}" data-action="select-device" data-asset-id="${escapeHtml(d.asset_id)}" style="margin-left:${(depth + 1) * 10}px">
      <div class="dev-icon">${deviceIcon(d.device_type)}</div>
      <div>
        <div class="dev-name">${escapeHtml(d.brand || "")} ${escapeHtml(d.model || "")}</div>
        <div class="dev-meta">${escapeHtml(d.device_type || "")}</div>
        <div class="dev-id">${escapeHtml(d.asset_id)}</div>
      </div>
    </button>`;
  }).join("");
  return groups + leaves;
}

function renderDeviceTree() {
  const el = $("#device-tree");
  if (!state.devices.length) {
    el.innerHTML = `<div class="empty-soft">No assets yet. Click "Run ingest" or "Add asset".</div>`;
    return;
  }
  const tree = buildTree(state.devices);
  el.innerHTML = renderTreeNode(tree);
}

function renderScopeTag() {
  const tag = $("#scope-tag");
  const label = $("#scope-tag-label");
  if (!tag || !label) return;
  if (!state.selectedAssetId) {
    tag.hidden = true;
    return;
  }
  const dev = state.devices.find((d) => d.asset_id === state.selectedAssetId);
  label.textContent = dev ? `${dev.brand} ${dev.model}` : state.selectedAssetId;
  tag.hidden = false;
}

function fillAssetSelect(selectId, { includeBlank = false, blankLabel = "" } = {}) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  const prev = sel.value;
  const opts = state.devices.map((d) =>
    `<option value="${escapeHtml(d.asset_id)}">${escapeHtml(d.brand || "")} ${escapeHtml(d.model || "")} · ${escapeHtml(d.asset_id)}</option>`
  );
  if (includeBlank) opts.unshift(`<option value="">${escapeHtml(blankLabel)}</option>`);
  sel.innerHTML = opts.join("");
  if (prev && state.devices.some((d) => d.asset_id === prev)) {
    sel.value = prev;
  } else if (state.selectedAssetId) {
    sel.value = state.selectedAssetId;
  }
}

// ---- View routing -------------------------------------------------------
function setView(view) {
  state.view = view;
  document.querySelectorAll(".view-tab").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach((s) => {
    s.hidden = s.dataset.view !== view;
  });
  if (view === "incident") {
    fillAssetSelect("incident-asset");
    if (state.selectedAssetId && state.devices.some((d) => d.asset_id === state.selectedAssetId)) {
      $("#incident-asset").value = state.selectedAssetId;
    }
  } else if (view === "pm") {
    fillAssetSelect("pm-asset");
    if (state.selectedAssetId) $("#pm-asset").value = state.selectedAssetId;
  }
}

function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll(".mode-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.mode === mode);
  });
  const input = $("#hero-input");
  if (!input) return;
  if (mode === "ask") input.placeholder = "Ask about an asset — e.g. What does F004 mean?";
  if (mode === "search") input.placeholder = "Search the wiki — e.g. fault code F004";
  if (mode === "manuals") input.placeholder = "Find a manual — e.g. PowerFlex 525";
}

// ---- Generic answer card helpers ---------------------------------------
function clearThreadEmpty(threadSel = "#thread") {
  const empty = document.querySelector(`${threadSel} .thread-empty, ${threadSel} .empty-soft`);
  if (empty) empty.remove();
}

function pushUserCard(query, modeLabel, threadSel = "#thread") {
  clearThreadEmpty(threadSel);
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
  document.querySelector(threadSel).appendChild(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
}

function pendingAnswerCard(label, threadSel = "#thread") {
  clearThreadEmpty(threadSel);
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
  document.querySelector(threadSel).appendChild(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
  return el;
}

function typewrite(targetEl, text, speed = 12) {
  // Skip animation when the tab is hidden — browsers throttle timers in
  // background tabs which would stall the agent timeline.
  if (typeof document !== "undefined" && document.hidden) {
    targetEl.innerHTML = escapeHtml(text);
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    const stepSize = Math.max(1, Math.round(text.length / 240));
    let i = 0;
    const step = () => {
      if (i > text.length) {
        targetEl.innerHTML = escapeHtml(text);
        return resolve();
      }
      targetEl.innerHTML = `${escapeHtml(text.slice(0, i))}<span class="cursor"></span>`;
      i += stepSize;
      setTimeout(step, speed);
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
  return `
    <div class="chips">
      <span class="chip ${tone}">resolution · ${escapeHtml(resolution.status)}</span>
      ${scope ? `<span class="chip ${scopeTone}">scope · ${escapeHtml(scope)}</span>` : ""}
      <span class="chip">confidence · ${escapeHtml(conf)}</span>
      ${resolution.asset_id ? `<span class="chip"><code>${escapeHtml(resolution.asset_id)}</code></span>` : ""}
      ${(resolution.matched_on || []).length ? `<span class="chip">matched · ${escapeHtml(resolution.matched_on.join(", "))}</span>` : ""}
    </div>`;
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

function failCard(card, err) {
  card.classList.add("error-card");
  const head = card.querySelector(".card-head");
  const body = card.querySelector(".answer");
  head.innerHTML = `<span class="who">Error</span><span class="chip bad">${escapeHtml(err.code || "api_error")}</span><span class="when">${timeNow()}</span>`;
  body.innerHTML = escapeHtml(err.message || "Request failed.");
  if (err.details) card.insertAdjacentHTML("beforeend", jsonBlock(err.details));
}

// ---- Inspector ----------------------------------------------------------
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
      </div>
    </div>
    ${jsonBlock(payload)}
  `;
}

// ---- Loaders -----------------------------------------------------------
async function refreshClient() { api = makeClient(state.config); }

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
  renderDeviceTree();
  renderStatus();
  // Refresh select boxes if their views are visible
  fillAssetSelect("incident-asset");
  fillAssetSelect("pm-asset");
}

async function loadAlerts() {
  try {
    const r = await fetch("/seeds/factory/alerts.json", { headers: { accept: "application/json" } });
    if (!r.ok) return;
    const data = await r.json();
    state.alerts = data.alerts || [];
  } catch {
    state.alerts = [];
  }
  renderAlerts();
}

function renderAlerts() {
  const list = $("#alerts-list");
  const meta = $("#alerts-meta");
  if (!list) return;
  if (!state.alerts.length) {
    list.innerHTML = `<div class="empty-soft">No live alerts.</div>`;
    if (meta) meta.textContent = "0 active";
    return;
  }
  if (meta) meta.textContent = `${state.alerts.length} active`;
  list.innerHTML = state.alerts.map((a) => {
    const sev = (a.severity || "info").toLowerCase();
    return `<button class="alert-row" data-action="use-alert"
      data-asset-id="${escapeHtml(a.asset_id || "")}"
      data-fault="${escapeHtml(a.fault_code || "")}"
      data-symptom="${escapeHtml(a.symptom || "")}">
      <span class="sev sev-${escapeHtml(sev)}"></span>
      <div>
        <div class="alert-line">
          <code>${escapeHtml(a.fault_code || "—")}</code>
          <span class="dim">·</span>
          <span class="asset"><code>${escapeHtml(a.asset_id || "—")}</code></span>
        </div>
        <div class="alert-symptom">${escapeHtml(a.symptom || a.message || "")}</div>
        <div class="alert-meta">${escapeHtml(a.timestamp || "")} · ${escapeHtml(a.location || "")}</div>
      </div>
      <span class="chip">use →</span>
    </button>`;
  }).join("");
}

// ---- Tools view: ask/search/manuals ------------------------------------
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
    failCard(card, normalizeApiError(err));
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
    failCard(card, normalizeApiError(err));
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
    failCard(card, normalizeApiError(err));
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
    body.innerHTML = `<em style="color:var(--warn)">Multiple assets match — pick one to scope the answer.</em>`;
    card.insertAdjacentHTML("beforeend", scopeChips(response.resolution));
    return;
  }
  await typewrite(body, response.answer || "(no answer)", 10);
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
  html += searchResultsBlock(response.results, scope);
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

// ---- Incident flow -----------------------------------------------------
async function runIncident({ assetId, faultCode, symptom }) {
  const timeline = $("#incident-timeline");
  timeline.innerHTML = "";
  const header = document.createElement("div");
  header.className = "card incident-header";
  header.innerHTML = `
    <div class="card-head">
      <span class="who">Incident plan</span>
      <span class="chip info">asset · <code>${escapeHtml(assetId)}</code></span>
      <span class="chip warn">fault · <code>${escapeHtml(faultCode)}</code></span>
      ${symptom ? `<span class="chip">symptom · ${escapeHtml(symptom)}</span>` : ""}
      <span class="when">${timeNow()}</span>
    </div>
    <div class="plan-skeleton">
      <div class="plan-step pending" data-step="1"><span class="step-num">1</span><span class="step-name">SEARCH fault evidence</span><span class="step-status">queued</span></div>
      <div class="plan-step pending" data-step="2"><span class="step-num">2</span><span class="step-name">ASK recovery procedure</span><span class="step-status">queued</span></div>
      <div class="plan-step pending" data-step="3"><span class="step-num">3</span><span class="step-name">SEARCH likely parts</span><span class="step-status">queued</span></div>
    </div>
  `;
  timeline.appendChild(header);

  if (state.config.mode !== "live") {
    const note = document.createElement("div");
    note.className = "card warn-card";
    note.innerHTML = `<div class="card-head"><span class="who">Mock mode</span><span class="chip warn">no orchestrator</span></div>
      <p class="answer">Incident orchestration requires the live API. Switch to live mode in Settings (⌘,) and point at the running backend (e.g. http://127.0.0.1:8124).</p>`;
    timeline.appendChild(note);
    return;
  }

  let response;
  try {
    response = await requestJson({
      baseUrl: state.config.apiBase,
      method: "POST",
      path: "/agent/incident",
      body: { asset_id: assetId, fault_code: faultCode, symptom: symptom || null }
    });
  } catch (err) {
    const n = normalizeApiError(err);
    const note = document.createElement("div");
    note.className = "card error-card";
    note.innerHTML = `<div class="card-head"><span class="who">Error</span><span class="chip bad">${escapeHtml(n.code)}</span><span class="when">${timeNow()}</span></div><p class="answer">${escapeHtml(n.message)}</p>`;
    timeline.appendChild(note);
    return;
  }

  state.lastResolution = response;
  renderInspector(response);

  const steps = response.steps || [];
  for (let i = 0; i < steps.length; i++) {
    const step = steps[i];
    const skel = header.querySelector(`.plan-step[data-step="${i + 1}"]`);
    if (skel) {
      skel.classList.remove("pending");
      skel.classList.add(step.status === "error" ? "error" : "ok");
      skel.querySelector(".step-status").textContent = step.status;
    }
    const card = document.createElement("article");
    card.className = "card timeline-card";
    const action = step.tool_call?.action || "";
    const intent = step.intent || "";
    card.innerHTML = `
      <div class="card-head">
        <span class="who">Step ${i + 1} · ${escapeHtml(action.toUpperCase())}</span>
        <span class="chip">${escapeHtml(intent)}</span>
        <span class="chip ${step.status === "error" ? "bad" : "ok"}">${escapeHtml(step.status)}</span>
        <span class="when">${timeNow()}</span>
      </div>
      <div class="timeline-body" data-slot="body"></div>
    `;
    timeline.appendChild(card);
    const body = card.querySelector('[data-slot="body"]');
    if (step.status === "error") {
      body.innerHTML = `<p class="answer">${escapeHtml(step.error?.message || "step failed")}</p>${step.error?.details ? jsonBlock(step.error.details) : ""}`;
    } else if (action === "search") {
      const r = step.result || {};
      body.innerHTML = `${scopeChips(r.resolution, r.scope)}${searchResultsBlock(r.results, r.scope)}`;
    } else if (action === "ask") {
      const r = step.result || {};
      const answer = document.createElement("p");
      answer.className = "answer";
      body.appendChild(answer);
      await typewrite(answer, r.answer || "(no answer)", 8);
      answer.innerHTML = escapeHtml(r.answer || "(no answer)");
      body.insertAdjacentHTML("beforeend", scopeChips(r.resolution));
      if (r.missing_information?.length) {
        body.insertAdjacentHTML("beforeend", `<div class="chip warn" style="margin-top:8px">missing · ${escapeHtml(r.missing_information.join("; "))}</div>`);
      }
      body.insertAdjacentHTML("beforeend", evidenceList(r.evidence));
    } else {
      body.innerHTML = jsonBlock(step.result || {});
    }
    card.scrollIntoView({ behavior: "smooth", block: "end" });
  }
}

// ---- PM flow -----------------------------------------------------------
async function runPm({ assetId, cadence }) {
  const dev = state.devices.find((d) => d.asset_id === assetId);
  const label = dev ? `${dev.brand} ${dev.model} (${assetId})` : assetId;
  const question = `Generate today's ${cadence} preventive maintenance checklist for ${label}. List inspection points, lubrication points, fastener torque checks, and any safety steps. Cite the section for each item.`;
  pushUserCard(`${cadence} PM checklist for ${label}`, "PM", "#pm-thread");
  const card = pendingAnswerCard("Wiki", "#pm-thread");
  try {
    const response = await api.ask({
      question,
      asset_id: assetId,
      limit: 8,
      allow_global_fallback: false
    });
    state.lastResolution = response;
    renderInspector(response);
    finalizeAskCard(card, response);
  } catch (err) {
    failCard(card, normalizeApiError(err));
  }
}

// ---- Compliance flow ---------------------------------------------------
async function runCompliance(query) {
  pushUserCard(query, "AUDIT", "#compliance-thread");
  const card = pendingAnswerCard("Search", "#compliance-thread");
  try {
    const response = await api.search({
      query,
      asset_id: null,
      filters: null,
      limit: 16,
      allow_global_fallback: true
    });
    state.lastResolution = response;
    renderInspector(response);
    // Group results by asset_id
    const groups = new Map();
    for (const r of response.results || []) {
      const key = r.asset_id || "global";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(r);
    }
    const head = card.querySelector(".card-head");
    head.innerHTML = `
      <span class="who">Audit</span>
      <span class="chip info">scope · ${escapeHtml(response.scope || "—")}</span>
      <span class="chip">${response.results?.length ?? 0} hits across ${groups.size} asset(s)</span>
      <span class="when">${timeNow()}</span>
    `;
    card.querySelector(".answer").outerHTML = "";
    let html = scopeChips(response.resolution, response.scope);
    html += `<div class="audit-groups">`;
    for (const [assetId, rows] of groups) {
      const dev = state.devices.find((d) => d.asset_id === assetId);
      const title = dev ? `${dev.brand} ${dev.model}` : assetId;
      html += `<div class="audit-group">
        <div class="audit-group-head"><strong>${escapeHtml(title)}</strong> <code>${escapeHtml(assetId)}</code> <span class="chip">${rows.length}</span></div>
        ${searchResultsBlock(rows, response.scope)}
      </div>`;
    }
    html += `</div>`;
    card.insertAdjacentHTML("beforeend", html);
  } catch (err) {
    failCard(card, normalizeApiError(err));
  }
}

// ---- Modals ------------------------------------------------------------
function openSettings() {
  $("#mode-select").value = state.config.mode;
  $("#api-base-input").value = state.config.apiBase;
  $("#settings-modal").showModal();
}
function openDevice() { $("#device-modal").showModal(); }

// ---- Event wiring ------------------------------------------------------
document.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;

  if (form.id === "incident-form") {
    const assetId = $("#incident-asset").value.trim();
    const faultCode = $("#incident-fault").value.trim();
    const symptom = $("#incident-symptom").value.trim();
    if (!assetId || !faultCode) return toast("Pick an asset and enter a fault code", "bad");
    return runIncident({ assetId, faultCode, symptom });
  }
  if (form.id === "pm-form") {
    const assetId = $("#pm-asset").value.trim();
    const cadence = $("#pm-cadence").value;
    if (!assetId) return toast("Pick a machine", "bad");
    return runPm({ assetId, cadence });
  }
  if (form.id === "compliance-form") {
    const q = $("#compliance-query").value.trim();
    if (!q) return;
    $("#compliance-query").value = "";
    return runCompliance(q);
  }
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
      renderDeviceTree();
      $("#device-modal").close();
      form.reset();
      toast(`Added ${device.brand || ""} ${device.model || ""}`.trim(), "ok");
    } catch (err) {
      toast(normalizeApiError(err).message, "bad");
    }
  }
});

document.addEventListener("click", async (event) => {
  const tab = event.target.closest(".view-tab");
  if (tab) {
    setView(tab.dataset.view);
    return;
  }
  const m = event.target.closest(".mode-btn");
  if (m) { setMode(m.dataset.mode); return; }
  const hint = event.target.closest(".hint");
  if (hint) {
    if (hint.dataset.compliance != null || hint.dataset.complianceHint) {
      $("#compliance-query").value = hint.dataset.complianceHint;
      $("#compliance-query").focus();
    } else if (hint.dataset.hint) {
      $("#hero-input").value = hint.dataset.hint;
      $("#hero-input").focus();
    }
    return;
  }
  const btn = event.target.closest("[data-action]");
  if (!btn) return;
  const a = btn.dataset.action;

  if (a === "select-device") {
    const id = btn.dataset.assetId;
    state.selectedAssetId = state.selectedAssetId === id ? "" : id;
    renderDeviceTree();
    renderScopeTag();
    if (state.view === "incident" && state.selectedAssetId) {
      $("#incident-asset").value = state.selectedAssetId;
    } else if (state.view === "pm" && state.selectedAssetId) {
      $("#pm-asset").value = state.selectedAssetId;
    }
    return;
  }
  if (a === "use-alert") {
    const assetId = btn.dataset.assetId;
    const fault = btn.dataset.fault;
    const symptom = btn.dataset.symptom;
    setView("incident");
    if (assetId) {
      state.selectedAssetId = assetId;
      $("#incident-asset").value = assetId;
      renderDeviceTree();
      renderScopeTag();
    }
    $("#incident-fault").value = fault || "";
    $("#incident-symptom").value = symptom || "";
    return;
  }
  if (a === "clear-scope") {
    state.selectedAssetId = "";
    renderDeviceTree();
    renderScopeTag();
    return;
  }
  if (a === "refresh-devices") {
    await refreshDevices();
    toast("Assets refreshed", "ok");
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
      toast(`Ingest complete · ${report.indexed ?? 0} indexed`, "ok");
    } catch (err) {
      toast(normalizeApiError(err).message, "bad");
    }
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

document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === ",") {
    event.preventDefault();
    openSettings();
  }
});

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
  setView("incident");
  renderStatus();
  renderDeviceTree();
  await Promise.all([checkStatus(), refreshDevices(), loadAlerts()]);
  fillAssetSelect("incident-asset");
  fillAssetSelect("pm-asset");
}

init();
