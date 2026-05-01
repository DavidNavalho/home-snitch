import { buildCreateDevicePayload } from "./device.js";

export const AGENT_ACTIONS = [
  {
    id: "ask",
    label: "Ask",
    intent: "answer_question",
    action: "POST /ask",
    view: "ask",
    placeholder: "What does E15 mean?"
  },
  {
    id: "search",
    label: "Search",
    intent: "search_docs",
    action: "POST /search",
    view: "search",
    placeholder: "E15 dishwasher error"
  },
  {
    id: "manual_find",
    label: "Find manuals",
    intent: "manual_discovery",
    action: "POST /manuals/find",
    view: "manuals",
    placeholder: "Bosch SMS6ZCW00G manual"
  },
  {
    id: "manual_download",
    label: "Download",
    intent: "manual_download",
    action: "POST /manuals/download",
    view: "manuals",
    placeholder: "https://example.invalid/manual.pdf"
  },
  {
    id: "ingest",
    label: "Ingest",
    intent: "index_refresh",
    action: "POST /ingest",
    view: "ingest",
    placeholder: "Run ingest"
  },
  {
    id: "add_device",
    label: "Add device",
    intent: "device_create",
    action: "POST /devices",
    view: "devices",
    placeholder: "brand=Bosch model=SMS6ZCW00G type=dishwasher room=kitchen"
  },
  {
    id: "list_devices",
    label: "List devices",
    intent: "device_list",
    action: "GET /devices",
    view: "devices",
    placeholder: "list devices"
  }
];

const ACTION_BY_ID = new Map(AGENT_ACTIONS.map((action) => [action.id, action]));

export function getAgentAction(id) {
  return ACTION_BY_ID.get(id) ?? ACTION_BY_ID.get("ask");
}

function clientInputError(message, details = null) {
  const error = new Error(message);
  error.code = "invalid_agent_input";
  error.details = details;
  error.status = 0;
  return error;
}

function compactText(value) {
  return String(value ?? "").trim().replace(/\s+/g, " ");
}

function hasExplicitAction(text) {
  const lower = compactText(text).toLowerCase();
  if (!lower) {
    return null;
  }
  if (/^(\/?list devices?|show devices?|devices)\b/.test(lower)) {
    return "list_devices";
  }
  if (/^(\/?ingest|run ingest|index docs|reindex)\b/.test(lower)) {
    return "ingest";
  }
  if (/^(\/?download|download manual)\b/.test(lower)) {
    return "manual_download";
  }
  if (/^(\/?find manuals?|\/?manuals? find|manual search)\b/.test(lower)) {
    return "manual_find";
  }
  if (/^(\/?add device|new device|create device)\b/.test(lower)) {
    return "add_device";
  }
  if (/^(\/?search|find docs?|look up|lookup)\b/.test(lower)) {
    return "search";
  }
  if (/^(\/?ask|question)\b/.test(lower)) {
    return "ask";
  }
  return null;
}

export function resolveAgentAction(input, selectedAction = "ask") {
  return hasExplicitAction(input) ?? getAgentAction(selectedAction).id;
}

export function stripActionPrefix(input, actionId) {
  const text = String(input ?? "").trim();
  const patterns = {
    ask: /^(\/?ask|question)\b[:\s-]*/i,
    search: /^(\/?search|find docs?|look up|lookup)\b[:\s-]*/i,
    manual_find: /^(\/?find manuals?|\/?manuals? find|manual search)\b[:\s-]*/i,
    manual_download: /^(\/?download|download manual)\b[:\s-]*/i,
    ingest: /^(\/?ingest|run ingest|index docs|reindex)\b[:\s-]*/i,
    add_device: /^(\/?add device|new device|create device)\b[:\s-]*/i,
    list_devices: /^(\/?list devices?|show devices?|devices)\b[:\s-]*/i
  };
  return text.replace(patterns[actionId] ?? /^$/, "").trim();
}

export function extractUrl(input) {
  const match = String(input ?? "").match(/https?:\/\/[^\s"'<>]+|file:\/\/[^\s"'<>]+/i);
  return match ? match[0] : "";
}

function parseJsonObject(input) {
  const text = String(input ?? "").trim();
  if (!text.startsWith("{")) {
    return null;
  }
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed
      : null;
  } catch {
    return null;
  }
}

function parseKeyValueFields(input) {
  const fields = {};
  const pattern = /([a-zA-Z_][\w-]*)\s*=\s*("([^"]*)"|'([^']*)'|[^\s]+)/g;
  for (const match of String(input ?? "").matchAll(pattern)) {
    fields[match[1].toLowerCase().replace(/-/g, "_")] =
      match[3] ?? match[4] ?? match[2] ?? "";
  }
  return fields;
}

function removeKeyValueFields(input) {
  return String(input ?? "").replace(
    /([a-zA-Z_][\w-]*)\s*=\s*("([^"]*)"|'([^']*)'|[^\s]+)/g,
    ""
  );
}

function cleanActionText(input, actionId) {
  return stripActionPrefix(removeKeyValueFields(input), actionId)
    .trim()
    .replace(/\s+/g, " ");
}

function numberField(fields, key, fallback) {
  const value = Number(fields[key]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function boolField(fields, key, fallback) {
  if (fields[key] === undefined || fields[key] === "") {
    return fallback;
  }
  return ["1", "true", "yes", "on"].includes(String(fields[key]).toLowerCase());
}

function normalizeDeviceFields(fields) {
  return {
    asset_id: fields.asset_id ?? fields.asset ?? "",
    brand: fields.brand ?? "",
    model: fields.model ?? "",
    device_type: fields.device_type ?? fields.type ?? "",
    room: fields.room ?? "",
    aliases: fields.aliases ?? fields.alias ?? ""
  };
}

export function parseAgentDevicePayload(input) {
  const json = parseJsonObject(input);
  const fields = normalizeDeviceFields(json ?? parseKeyValueFields(input));
  const missing = ["brand", "model", "device_type"].filter(
    (key) => !String(fields[key] ?? "").trim()
  );
  if (missing.length) {
    throw clientInputError("Add device needs brand, model, and type.", {
      missing,
      accepted: "brand=Bosch model=SMS6ZCW00G type=dishwasher room=kitchen"
    });
  }
  return buildCreateDevicePayload(fields);
}

function requireText(input, actionId, label) {
  const text = cleanActionText(input, actionId);
  if (!text) {
    throw clientInputError(`${label} needs input text.`);
  }
  return text;
}

function firstManualCandidate(manualResults) {
  return manualResults?.candidates?.[0] ?? null;
}

export function buildAgentRequest({
  action,
  input,
  assetId = "",
  limit = 8,
  allowGlobalFallback = false,
  manualResults = null
}) {
  const actionId = getAgentAction(action).id;
  const fields = parseKeyValueFields(input);
  const selectedAssetId =
    String(fields.asset_id ?? fields.asset ?? assetId ?? "").trim() || null;
  const requestLimit = numberField(fields, "limit", limit);
  const requestAllowGlobalFallback = boolField(
    fields,
    "allow_global_fallback",
    boolField(fields, "global", allowGlobalFallback)
  );
  const actionText = cleanActionText(input, actionId);

  if (actionId === "ask") {
    return {
      question: actionText || requireText(input, actionId, "Ask"),
      asset_id: selectedAssetId,
      limit: requestLimit,
      allow_global_fallback: requestAllowGlobalFallback
    };
  }

  if (actionId === "search") {
    return {
      query: actionText || requireText(input, actionId, "Search"),
      asset_id: selectedAssetId,
      filters: null,
      limit: requestLimit,
      allow_global_fallback: requestAllowGlobalFallback
    };
  }

  if (actionId === "manual_find") {
    const query = actionText;
    if (!query && !selectedAssetId) {
      throw clientInputError("Find manuals needs a query or selected device.");
    }
    return {
      asset_id: selectedAssetId,
      limit: Math.min(requestLimit, 20),
      ...(query ? { query } : {})
    };
  }

  if (actionId === "manual_download") {
    const candidate = firstManualCandidate(manualResults);
    const url = extractUrl(input) || fields.url || candidate?.url || "";
    const downloadAssetId = selectedAssetId || candidate?.asset_id || null;
    if (!downloadAssetId) {
      throw clientInputError("Download needs a selected device.");
    }
    if (!url) {
      throw clientInputError("Download needs a manual URL or prior manual candidate.");
    }
    return {
      asset_id: downloadAssetId,
      url
    };
  }

  if (actionId === "ingest") {
    return {};
  }

  if (actionId === "add_device") {
    return parseAgentDevicePayload(stripActionPrefix(input, actionId));
  }

  if (actionId === "list_devices") {
    return {};
  }

  throw clientInputError(`Unknown chat action: ${actionId}`);
}

function commandPrefix(actionId) {
  const prefixes = {
    ask: "ask",
    search: "search",
    manual_find: "find manuals",
    manual_download: "download manual",
    ingest: "ingest",
    add_device: "add device",
    list_devices: "list devices"
  };
  return prefixes[actionId] ?? "ask";
}

export function buildAgentCommandInput({
  action,
  input,
  assetId = "",
  limit = 8,
  allowGlobalFallback = false,
  manualResults = null
}) {
  const actionId = resolveAgentAction(input, action);
  const text = cleanActionText(input, actionId);
  const parts = [commandPrefix(actionId)];

  if (actionId === "ask" || actionId === "search") {
    if (assetId) {
      parts.push(`asset_id=${assetId}`);
    }
    parts.push(`limit=${limit}`);
    parts.push(`allow_global_fallback=${allowGlobalFallback ? "true" : "false"}`);
    if (text) {
      parts.push(text);
    }
    return parts.join(" ");
  }

  if (actionId === "manual_find") {
    if (assetId) {
      parts.push(`asset_id=${assetId}`);
    }
    parts.push(`limit=${Math.min(limit, 20)}`);
    if (text) {
      parts.push(text);
    }
    return parts.join(" ");
  }

  if (actionId === "manual_download") {
    const candidate = firstManualCandidate(manualResults);
    const url = extractUrl(input) || candidate?.url || "";
    const downloadAssetId = assetId || candidate?.asset_id || "";
    if (downloadAssetId) {
      parts.push(`asset_id=${downloadAssetId}`);
    }
    if (url) {
      parts.push(`url=${url}`);
    }
    if (text && text !== url) {
      parts.push(text);
    }
    return parts.join(" ");
  }

  if (actionId === "add_device") {
    const payloadText = stripActionPrefix(input, actionId);
    return [commandPrefix(actionId), payloadText].filter(Boolean).join(" ");
  }

  return parts.join(" ");
}

export function summarizeAgentResult(action, result) {
  if (!result) {
    return "No result";
  }
  const actionId = getAgentAction(action).id;
  if (actionId === "ask") {
    return `${result.generated ? "Generated" : "Evidence-only"} answer, ${
      result.evidence?.length ?? 0
    } evidence item(s).`;
  }
  if (actionId === "search") {
    return `${result.results?.length ?? 0} result(s), ${result.scope ?? "none"} scope.`;
  }
  if (actionId === "manual_find") {
    return `${result.candidates?.length ?? 0} manual candidate(s).`;
  }
  if (actionId === "manual_download") {
    return result.downloaded
      ? `Downloaded to ${result.saved_path}.`
      : result.error || "Download did not complete.";
  }
  if (actionId === "ingest") {
    return `${result.converted ?? 0} converted, ${result.indexed ?? 0} indexed, ${
      result.failed ?? 0
    } failed.`;
  }
  if (actionId === "add_device") {
    const device = result.device ?? result;
    return `Device ${device.asset_id} submitted.`;
  }
  if (actionId === "list_devices") {
    return `${result.devices?.length ?? 0} device(s).`;
  }
  return "Completed.";
}
