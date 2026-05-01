import {
  DEFAULT_API_BASE,
  createApiClient,
  normalizeApiBase,
  normalizeApiError,
  probeApiStatus
} from "./api.js";
import { buildCreateDevicePayload } from "./device.js";
import { renderApp } from "./render.js";

const CONFIG_KEY = "homeWikiUiConfig";

async function loadRuntimeDefaults() {
  try {
    const response = await fetch("/ui-config.json", {
      headers: { accept: "application/json" }
    });
    if (!response.ok) {
      return {};
    }
    return await response.json();
  } catch {
    return {};
  }
}

function loadConfig(runtimeDefaults = {}) {
  const params = new URLSearchParams(globalThis.location?.search ?? "");
  let saved = {};
  try {
    saved = JSON.parse(globalThis.localStorage?.getItem(CONFIG_KEY) ?? "{}");
  } catch {
    saved = {};
  }
  return {
    mode: params.get("mode") || saved.mode || "mock",
    apiBase: normalizeApiBase(
      params.get("apiBase") ||
        saved.apiBase ||
        runtimeDefaults.apiBase ||
        DEFAULT_API_BASE
    )
  };
}

function saveConfig(config) {
  globalThis.localStorage?.setItem(CONFIG_KEY, JSON.stringify(config));
}

function formFields(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function formCheckbox(form, name) {
  return form.elements[name]?.checked ?? false;
}

function formNumber(form, name, fallback) {
  const value = Number(form.elements[name]?.value);
  return Number.isFinite(value) ? value : fallback;
}

const state = {
  config: loadConfig(),
  status: {
    available: null,
    message: "Checking status..."
  },
  activeView: "devices",
  selectedAssetId: "",
  devices: {
    items: [],
    error: null,
    notice: "",
    lastRequest: null
  },
  search: {
    query: "E15",
    assetId: "dishwasher-bosch-sms6zcw00g",
    limit: 8,
    allowGlobalFallback: true,
    response: null,
    error: null
  },
  ask: {
    question: "What does E15 mean?",
    assetId: "dishwasher-bosch-sms6zcw00g",
    limit: 8,
    allowGlobalFallback: false,
    response: null,
    error: null
  },
  manuals: {
    query: "Bosch SMS6ZCW00G manual",
    assetId: "dishwasher-bosch-sms6zcw00g",
    results: null,
    notice: "",
    error: null
  },
  ingest: {
    status: null,
    report: null,
    error: null
  }
};

let api = createApiClient(state.config);

function refreshClient() {
  api = createApiClient(state.config);
}

function render() {
  document.getElementById("app").innerHTML = renderApp(state);
}

async function checkStatus() {
  state.status = {
    available: null,
    message: "Checking status..."
  };
  render();

  if (state.config.mode === "mock") {
    try {
      await probeApiStatus({ baseUrl: state.config.apiBase });
      state.status = {
        available: true,
        message: `Live API responded at ${state.config.apiBase}; mock responses remain active.`
      };
    } catch (error) {
      const normalized = normalizeApiError(error);
      state.status = {
        available: false,
        message: `${normalized.message} Mock responses are active.`
      };
    }
    render();
    return;
  }

  try {
    const status = await api.status();
    state.status = {
      available: true,
      message: `Live API responded at ${state.config.apiBase}.`
    };
    state.ingest.status = status;
  } catch (error) {
    const normalized = normalizeApiError(error);
    state.status = {
      available: false,
      message: normalized.message
    };
  }
  render();
}

async function refreshDevices() {
  state.devices.error = null;
  state.devices.notice = "";
  render();
  try {
    const payload = await api.getDevices();
    state.devices.items = payload.devices ?? [];
  } catch (error) {
    state.devices.error = normalizeApiError(error);
  }
  render();
}

async function refreshStatus() {
  state.ingest.error = null;
  render();
  try {
    state.ingest.status = await api.status();
  } catch (error) {
    state.ingest.error = normalizeApiError(error);
  }
  render();
}

async function submitCreateDevice(form) {
  const payload = buildCreateDevicePayload(formFields(form));
  state.devices.error = null;
  state.devices.notice = "";
  state.devices.lastRequest = payload;
  render();
  try {
    const response = await api.createDevice(payload);
    const device = response.device ?? response;
    const existing = state.devices.items.filter(
      (item) => item.asset_id !== device.asset_id
    );
    state.devices.items = [...existing, device];
    state.devices.notice = `Device ${device.asset_id} submitted.`;
  } catch (error) {
    state.devices.error = normalizeApiError(error);
  }
  render();
}

async function submitSearch(form) {
  const fields = formFields(form);
  const payload = {
    query: fields.query,
    asset_id: fields.asset_id || null,
    filters: null,
    limit: formNumber(form, "limit", 8),
    allow_global_fallback: formCheckbox(form, "allow_global_fallback")
  };
  state.search.query = payload.query;
  state.search.assetId = payload.asset_id ?? "";
  state.search.limit = payload.limit;
  state.search.allowGlobalFallback = payload.allow_global_fallback;
  state.search.error = null;
  render();
  try {
    state.search.response = await api.search(payload);
  } catch (error) {
    state.search.response = null;
    state.search.error = normalizeApiError(error);
  }
  render();
}

async function submitAsk(form) {
  const fields = formFields(form);
  const payload = {
    question: fields.question,
    asset_id: fields.asset_id || null,
    limit: formNumber(form, "limit", 8),
    allow_global_fallback: formCheckbox(form, "allow_global_fallback")
  };
  state.ask.question = payload.question;
  state.ask.assetId = payload.asset_id ?? "";
  state.ask.limit = payload.limit;
  state.ask.allowGlobalFallback = payload.allow_global_fallback;
  state.ask.error = null;
  render();
  try {
    state.ask.response = await api.ask(payload);
  } catch (error) {
    state.ask.response = null;
    state.ask.error = normalizeApiError(error);
  }
  render();
}

async function submitManualFind(form) {
  const fields = formFields(form);
  const payload = {
    asset_id: fields.asset_id || null,
    query: fields.query
  };
  state.manuals.assetId = payload.asset_id ?? "";
  state.manuals.query = payload.query;
  state.manuals.error = null;
  state.manuals.notice = "";
  render();
  try {
    state.manuals.results = await api.findManuals(payload);
  } catch (error) {
    state.manuals.results = null;
    state.manuals.error = normalizeApiError(error);
  }
  render();
}

async function downloadManual(assetId, url) {
  state.manuals.error = null;
  state.manuals.notice = "";
  render();
  try {
    const result = await api.downloadManual({
      asset_id: assetId || state.manuals.assetId || state.selectedAssetId,
      url
    });
    state.manuals.notice = result.downloaded
      ? `Downloaded to ${result.saved_path}.`
      : result.error || "Download did not complete.";
  } catch (error) {
    state.manuals.error = normalizeApiError(error);
  }
  render();
}

async function runIngest() {
  state.ingest.error = null;
  render();
  try {
    state.ingest.report = await api.ingest({});
    state.ingest.status = await api.status();
  } catch (error) {
    state.ingest.error = normalizeApiError(error);
  }
  render();
}

async function chooseCandidate(assetId, target) {
  state.selectedAssetId = assetId;
  if (target === "ask") {
    state.ask.assetId = assetId;
    state.activeView = "ask";
    try {
      state.ask.error = null;
      state.ask.response = await api.ask({
        question: state.ask.question,
        asset_id: assetId,
        limit: state.ask.limit,
        allow_global_fallback: state.ask.allowGlobalFallback
      });
    } catch (error) {
      state.ask.response = null;
      state.ask.error = normalizeApiError(error);
    }
    render();
    return;
  }
  state.search.assetId = assetId;
  state.activeView = "search";
  try {
    state.search.error = null;
    state.search.response = await api.search({
      query: state.search.query,
      asset_id: assetId,
      filters: null,
      limit: state.search.limit,
      allow_global_fallback: state.search.allowGlobalFallback
    });
  } catch (error) {
    state.search.response = null;
    state.search.error = normalizeApiError(error);
  }
  render();
}

document.addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) {
    return;
  }
  if (form.id === "config-form") {
    const fields = formFields(form);
    state.config = {
      mode: fields.mode === "live" ? "live" : "mock",
      apiBase: normalizeApiBase(fields.apiBase)
    };
    saveConfig(state.config);
    refreshClient();
    checkStatus();
    refreshDevices();
    return;
  }
  if (form.id === "device-create-form") {
    submitCreateDevice(form);
    return;
  }
  if (form.id === "search-form") {
    submitSearch(form);
    return;
  }
  if (form.id === "ask-form") {
    submitAsk(form);
    return;
  }
  if (form.id === "manual-find-form") {
    submitManualFind(form);
  }
});

document.addEventListener("click", (event) => {
  const control = event.target.closest("[data-action]");
  if (!control) {
    return;
  }
  const { action } = control.dataset;
  if (action === "set-tab") {
    state.activeView = control.dataset.tab;
    render();
    return;
  }
  if (action === "refresh-devices") {
    refreshDevices();
    return;
  }
  if (action === "check-status") {
    checkStatus();
    return;
  }
  if (action === "refresh-status") {
    refreshStatus();
    return;
  }
  if (action === "run-ingest") {
    runIngest();
    return;
  }
  if (action === "choose-candidate") {
    chooseCandidate(control.dataset.assetId, control.dataset.target);
    return;
  }
  if (action === "download-manual") {
    downloadManual(control.dataset.assetId, control.dataset.url);
  }
});

async function init() {
  state.config = loadConfig(await loadRuntimeDefaults());
  refreshClient();
  render();
  checkStatus();
  refreshDevices();
  refreshStatus();
}

render();
init();
