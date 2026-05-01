export const FIXTURE_KEYS = {
  devicesList: "devices-list.json",
  deviceInformationBosch: "device-information-bosch.json",
  deviceInformationSiemens: "device-information-siemens.json",
  deviceInformationRouter: "device-information-router.json",
  searchScopedBoschE15: "search-scoped-bosch-e15.json",
  searchAmbiguousDishwasher: "search-ambiguous-dishwasher.json",
  askEvidenceOnlyBoschE15: "ask-evidence-only-bosch-e15.json",
  apiError: "api-error.json"
};

export const DEVICE_INFORMATION_KEYS = {
  "dishwasher-bosch-sms6zcw00g": "deviceInformationBosch",
  "dishwasher-siemens-sn23ec14cg": "deviceInformationSiemens",
  "router-asus-rt-ax88u": "deviceInformationRouter"
};

export function clonePayload(value) {
  return JSON.parse(JSON.stringify(value));
}

export function createHttpFixtureLoader({
  fetchImpl = globalThis.fetch,
  fixtureBase = "/fixtures/api"
} = {}) {
  const cache = new Map();
  return async (key) => {
    const fileName = FIXTURE_KEYS[key] ?? key;
    if (!cache.has(fileName)) {
      const response = await fetchImpl(`${fixtureBase}/${fileName}`, {
        headers: { accept: "application/json" }
      });
      if (!response.ok) {
        throw new Error(`Could not load fixture ${fileName}`);
      }
      cache.set(fileName, await response.json());
    }
    return clonePayload(cache.get(fileName));
  };
}

export function createMemoryFixtureLoader(fixtures) {
  return async (key) => {
    const value = fixtures[key];
    if (value === undefined) {
      throw new Error(`Missing fixture ${key}`);
    }
    return clonePayload(value);
  };
}

export async function makeAmbiguousAskResponse(loadFixture, question) {
  const askTemplate = await loadFixture("askEvidenceOnlyBoschE15");
  const ambiguousSearch = await loadFixture("searchAmbiguousDishwasher");
  askTemplate.answer = "";
  askTemplate.resolution = ambiguousSearch.resolution;
  askTemplate.sources = [];
  askTemplate.evidence = [];
  askTemplate.confidence = 0;
  askTemplate.generated = false;
  askTemplate.missing_information = [
    `Choose a device before answering "${question}".`
  ];
  return askTemplate;
}

export async function makeMissingEvidenceAskResponse(
  loadFixture,
  question,
  assetId = null
) {
  const response = await loadFixture("askEvidenceOnlyBoschE15");
  response.answer = "The home wiki does not contain evidence for this question.";
  response.resolution.status = assetId ? "exact" : "none";
  response.resolution.asset_id = assetId;
  response.resolution.confidence = assetId ? 1 : 0;
  response.resolution.matched_on = assetId ? ["asset_id"] : [];
  response.resolution.candidates = [];
  response.resolution.filters.asset_id = assetId;
  response.sources = [];
  response.evidence = [];
  response.confidence = 0;
  response.generated = false;
  response.missing_information = [`No indexed evidence matched "${question}".`];
  return response;
}

export async function makeGlobalSearchResponse(loadFixture, query) {
  const response = await loadFixture("searchScopedBoschE15");
  response.query = query;
  response.resolution.status = "none";
  response.resolution.asset_id = null;
  response.resolution.confidence = 0;
  response.resolution.matched_on = [];
  response.resolution.candidates = [];
  response.resolution.filters.asset_id = null;
  response.scope = "global";
  response.results = [
    {
      ...response.results[0],
      source_path:
        "fixtures/source_docs/devices/router-asus-rt-ax88u/notes/admin-notes.md",
      markdown_path:
        "fixtures/markdown_docs/devices/router-asus-rt-ax88u/notes/admin-notes.md",
      section_title: "Admin Notes",
      asset_id: "router-asus-rt-ax88u",
      source_type: "note",
      score: 0.72,
      text: "The router admin URL is documented in the office router notes."
    }
  ];
  return response;
}

export async function makeNoScopeSearchResponse(loadFixture, query) {
  const response = await loadFixture("searchAmbiguousDishwasher");
  response.query = query;
  response.resolution.status = "none";
  response.resolution.asset_id = null;
  response.resolution.confidence = 0;
  response.resolution.matched_on = [];
  response.resolution.candidates = [];
  response.resolution.filters.asset_id = null;
  response.scope = "none";
  response.results = [];
  return response;
}
