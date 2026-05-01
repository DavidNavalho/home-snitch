import {
  DEVICE_INFORMATION_KEYS,
  clonePayload,
  createHttpFixtureLoader,
  makeAmbiguousAskResponse,
  makeGlobalSearchResponse,
  makeMissingEvidenceAskResponse,
  makeNoScopeSearchResponse
} from "./fixtures.js";

export const DEFAULT_API_BASE = "http://127.0.0.1:8000";

export class ApiRequestError extends Error {
  constructor({ code, message, details = null, status = 0 }) {
    super(message);
    this.name = "ApiRequestError";
    this.code = code;
    this.details = details;
    this.status = status;
  }
}

export function normalizeApiBase(value) {
  const trimmed = String(value ?? "").trim();
  if (!trimmed) {
    return DEFAULT_API_BASE;
  }
  return trimmed.replace(/\/+$/g, "");
}

export function normalizeApiError(error) {
  if (error instanceof ApiRequestError) {
    return {
      code: error.code,
      message: error.message,
      details: error.details,
      status: error.status
    };
  }
  if (error?.error) {
    return {
      code: error.error.code ?? "api_error",
      message: error.error.message ?? "API request failed.",
      details: error.error.details ?? null,
      status: error.status ?? 0
    };
  }
  return {
    code: "api_error",
    message: error?.message ?? "API request failed.",
    details: null,
    status: error?.status ?? 0
  };
}

async function parseJsonResponse(response) {
  if (response.status === 204) {
    return null;
  }
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new ApiRequestError({
      code: "invalid_json",
      message: "API returned a non-JSON response.",
      details: { cause: error.message, body: text.slice(0, 500) },
      status: response.status
    });
  }
}

export async function requestJson({
  fetchImpl = globalThis.fetch,
  baseUrl = DEFAULT_API_BASE,
  method = "GET",
  path,
  body = undefined,
  signal = undefined
}) {
  if (!fetchImpl) {
    throw new ApiRequestError({
      code: "fetch_unavailable",
      message: "The browser does not provide fetch()."
    });
  }

  const url = `${normalizeApiBase(baseUrl)}${path}`;
  const options = {
    method,
    headers: {
      accept: "application/json"
    },
    signal
  };

  if (body !== undefined) {
    options.headers["content-type"] = "application/json";
    options.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetchImpl(url, options);
  } catch (error) {
    throw new ApiRequestError({
      code: "api_unavailable",
      message: `Could not reach API at ${normalizeApiBase(baseUrl)}.`,
      details: { cause: error.message },
      status: 0
    });
  }

  const payload = await parseJsonResponse(response);
  if (!response.ok) {
    const structured = normalizeApiError(payload);
    throw new ApiRequestError({
      code: structured.code,
      message: structured.message,
      details: structured.details,
      status: response.status
    });
  }
  if (payload?.error) {
    const structured = normalizeApiError(payload);
    throw new ApiRequestError({
      code: structured.code,
      message: structured.message,
      details: structured.details,
      status: response.status
    });
  }
  return payload;
}

function shouldReturnApiError(text) {
  const lower = String(text ?? "").toLowerCase();
  return lower.includes("api error") || lower.includes("unavailable");
}

function applyQuery(response, query) {
  const next = clonePayload(response);
  next.query = query;
  return next;
}

async function makeScopedSearch(loadFixture, request) {
  if (request.asset_id === "dishwasher-siemens-sn23ec14cg") {
    const response = await loadFixture("searchScopedBoschE15");
    response.query = request.query;
    response.resolution.asset_id = "dishwasher-siemens-sn23ec14cg";
    response.resolution.filters.asset_id = "dishwasher-siemens-sn23ec14cg";
    response.results = response.results.map((result) => ({
      ...result,
      source_path:
        "fixtures/source_docs/devices/dishwasher-siemens-sn23ec14cg/manuals/quick-manual.md",
      markdown_path:
        "fixtures/markdown_docs/devices/dishwasher-siemens-sn23ec14cg/manuals/quick-manual.md",
      section_title: "Troubleshooting > Error Codes > E24",
      asset_id: "dishwasher-siemens-sn23ec14cg",
      score: 0.91,
      text:
        "E24 means the drain system is blocked or water cannot drain correctly in this fixture."
    }));
    return response;
  }
  if (request.asset_id === "router-asus-rt-ax88u") {
    const response = await makeGlobalSearchResponse(loadFixture, request.query);
    response.resolution.status = "exact";
    response.resolution.asset_id = "router-asus-rt-ax88u";
    response.resolution.confidence = 1;
    response.resolution.matched_on = ["asset_id"];
    response.resolution.filters.asset_id = "router-asus-rt-ax88u";
    response.scope = "device";
    return response;
  }
  const response = applyQuery(await loadFixture("searchScopedBoschE15"), request.query);
  if (request.asset_id) {
    response.resolution.asset_id = request.asset_id;
    response.resolution.filters.asset_id = request.asset_id;
  }
  return response;
}

function makeEvidenceAskFromSearch(searchResponse, answer) {
  return {
    answer,
    resolution: searchResponse.resolution,
    sources: searchResponse.results.map((result) => result.markdown_path),
    evidence: searchResponse.results,
    confidence: searchResponse.results.length ? 6 : 0,
    generated: false,
    missing_information: []
  };
}

function makeManualFindResponse(request) {
  const assetId = request.asset_id || request.device || "dishwasher-bosch-sms6zcw00g";
  return {
    query: request.query || `${assetId} manual`,
    candidates: [
      {
        title: "Fixture manual candidate",
        url: `https://example.invalid/manuals/${assetId}.pdf`,
        source_host: "example.invalid",
        is_pdf: true,
        rank: 1,
        asset_id: assetId
      }
    ]
  };
}

async function throwFixtureApiError(loadFixture) {
  const errorFixture = await loadFixture("apiError");
  const error = errorFixture.error;
  throw new ApiRequestError({
    code: error.code,
    message: error.message,
    details: error.details,
    status: 0
  });
}

export function createApiClient({
  baseUrl = DEFAULT_API_BASE,
  mode = "mock",
  fetchImpl = globalThis.fetch,
  fixtureLoader = createHttpFixtureLoader({ fetchImpl })
} = {}) {
  const normalizedBase = normalizeApiBase(baseUrl);
  const useMock = mode !== "live";
  const live = (method, path, body) =>
    requestJson({
      fetchImpl,
      baseUrl: normalizedBase,
      method,
      path,
      body
    });
  const loadFixture = fixtureLoader;

  return {
    mode: useMock ? "mock" : "live",
    baseUrl: normalizedBase,

    async status() {
      if (useMock) {
        const devices = await loadFixture("devicesList");
        return {
          api: "mock",
          available: true,
          devices: devices.devices?.length ?? 0,
          indexed: 3,
          failed: 0
        };
      }
      return live("GET", "/status");
    },

    async getDevices() {
      if (useMock) {
        return loadFixture("devicesList");
      }
      return live("GET", "/devices");
    },

    async getDeviceInformation(assetId) {
      if (useMock) {
        const fixtureKey = DEVICE_INFORMATION_KEYS[assetId];
        if (fixtureKey) {
          return loadFixture(fixtureKey);
        }
        const devices = await loadFixture("devicesList");
        const device = devices.devices.find((item) => item.asset_id === assetId);
        if (!device) {
          throw new ApiRequestError({
            code: "unknown_asset_id",
            message: `Device asset_id ${assetId} is not registered.`,
            details: { asset_id: assetId },
            status: 404
          });
        }
        return {
          device,
          documents: []
        };
      }
      return live(
        "GET",
        `/devices/${encodeURIComponent(assetId)}/information`
      );
    },

    async createDevice(payload) {
      if (useMock) {
        return { device: clonePayload(payload) };
      }
      return live("POST", "/devices", payload);
    },

    async findManuals(payload) {
      if (useMock) {
        if (shouldReturnApiError(payload.query)) {
          await throwFixtureApiError(loadFixture);
        }
        return makeManualFindResponse(payload);
      }
      return live("POST", "/manuals/find", payload);
    },

    async downloadManual(payload) {
      if (useMock) {
        return {
          asset_id: payload.asset_id,
          url: payload.url,
          saved_path: `source_docs/devices/${payload.asset_id}/manuals/manual.pdf`,
          sidecar_path: `source_docs/devices/${payload.asset_id}/manuals/manual.pdf.yaml`,
          downloaded: true,
          error: null
        };
      }
      return live("POST", "/manuals/download", payload);
    },

    async search(payload) {
      if (useMock) {
        if (shouldReturnApiError(payload.query)) {
          await throwFixtureApiError(loadFixture);
        }
        const query = String(payload.query ?? "");
        const lower = query.toLowerCase();
        if (payload.asset_id || lower.includes("e15")) {
          return makeScopedSearch(loadFixture, payload);
        }
        if (lower.includes("dishwasher")) {
          return applyQuery(await loadFixture("searchAmbiguousDishwasher"), query);
        }
        if (payload.allow_global_fallback) {
          return makeGlobalSearchResponse(loadFixture, query);
        }
        return makeNoScopeSearchResponse(loadFixture, query);
      }
      return live("POST", "/search", payload);
    },

    async ask(payload) {
      if (useMock) {
        if (shouldReturnApiError(payload.question)) {
          await throwFixtureApiError(loadFixture);
        }
        const question = String(payload.question ?? "");
        const lower = question.toLowerCase();
        if (!payload.asset_id && lower.includes("dishwasher")) {
          return makeAmbiguousAskResponse(loadFixture, question);
        }
        if (payload.asset_id === "dishwasher-siemens-sn23ec14cg") {
          const searchResponse = await makeScopedSearch(loadFixture, {
            query: question,
            asset_id: payload.asset_id
          });
          return makeEvidenceAskFromSearch(
            searchResponse,
            "Chat is disabled. Retrieved evidence says E24 means the drain system is blocked or water cannot drain correctly."
          );
        }
        if (
          (!payload.asset_id ||
            payload.asset_id === "dishwasher-bosch-sms6zcw00g") &&
          (lower.includes("e15") ||
            lower.includes("error code") ||
            lower.includes("dishwasher"))
        ) {
          const response = await loadFixture("askEvidenceOnlyBoschE15");
          if (payload.asset_id) {
            response.resolution.asset_id = payload.asset_id;
            response.resolution.filters.asset_id = payload.asset_id;
          }
          return response;
        }
        return makeMissingEvidenceAskResponse(
          loadFixture,
          question,
          payload.asset_id ?? null
        );
      }
      return live("POST", "/ask", payload);
    },

    async ingest(payload = {}) {
      if (useMock) {
        return {
          converted: 2,
          indexed: 3,
          skipped: 0,
          failed: 0,
          removed: 0,
          warnings: [],
          errors: []
        };
      }
      return live("POST", "/ingest", payload);
    }
  };
}

export async function probeApiStatus({
  baseUrl = DEFAULT_API_BASE,
  fetchImpl = globalThis.fetch,
  timeoutMs = 1200
} = {}) {
  const controller =
    typeof AbortController !== "undefined" ? new AbortController() : null;
  const timeout =
    controller && timeoutMs
      ? setTimeout(() => controller.abort(), timeoutMs)
      : null;
  try {
    return await requestJson({
      fetchImpl,
      baseUrl,
      method: "GET",
      path: "/status",
      signal: controller?.signal
    });
  } finally {
    if (timeout) {
      clearTimeout(timeout);
    }
  }
}
