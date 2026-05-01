import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  buildAgentCommandInput,
  buildAgentRequest,
  resolveAgentAction
} from "../src/agent.js";
import { createApiClient } from "../src/api.js";
import { buildCreateDevicePayload } from "../src/device.js";
import { createMemoryFixtureLoader, FIXTURE_KEYS } from "../src/fixtures.js";
import {
  renderAgentChat,
  renderApp,
  renderAskResponse,
  renderDeviceInformation,
  renderDeviceTable,
  renderError,
  renderSearchResponse
} from "../src/render.js";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "..", "..");

async function readFixture(name) {
  const raw = await readFile(join(repoRoot, "fixtures", "api", name), "utf8");
  return JSON.parse(raw);
}

async function loadCanonicalFixtures() {
  const entries = await Promise.all(
    Object.entries(FIXTURE_KEYS).map(async ([key, fileName]) => [
      key,
      await readFixture(fileName)
    ])
  );
  return Object.fromEntries(entries);
}

async function makeMockClient() {
  return createApiClient({
    mode: "mock",
    fixtureLoader: createMemoryFixtureLoader(await loadCanonicalFixtures())
  });
}

test("fixture loader uses canonical fixtures/api payloads", async () => {
  const fixtures = await loadCanonicalFixtures();
  assert.deepEqual(fixtures.devicesList, await readFixture("devices-list.json"));
});

test("renders device list with brand, model, room, and aliases", async () => {
  const fixtures = await loadCanonicalFixtures();
  const html = renderDeviceTable(fixtures.devicesList.devices);
  assert.match(html, /Bosch/);
  assert.match(html, /SMS6ZCW00G/);
  assert.match(html, /kitchen/);
  assert.match(html, /kitchen dishwasher, dishwasher/);
  assert.match(html, /data-action="show-device-info"/);
});

test("builds minimal device create payload from form fields", () => {
  assert.deepEqual(
    buildCreateDevicePayload({
      brand: "Miele",
      model: "G 7310 SC",
      device_type: "Dishwasher",
      room: "utility",
      aliases: "quiet dishwasher, utility washer"
    }),
    {
      asset_id: "dishwasher-miele-g-7310-sc",
      device_type: "dishwasher",
      brand: "Miele",
      model: "G 7310 SC",
      normalized_model: "g7310sc",
      aliases: ["quiet dishwasher", "utility washer"],
      room: "utility"
    }
  );
});

test("agent router resolves explicit commands before the selected chip", () => {
  assert.equal(resolveAgentAction("search E15", "ask"), "search");
  assert.equal(resolveAgentAction("download https://example.invalid/manual.pdf", "ask"), "manual_download");
  assert.equal(resolveAgentAction("list devices", "ask"), "list_devices");
  assert.equal(resolveAgentAction("What does E15 mean?", "ask"), "ask");
});

test("agent request builder maps actions to direct API payloads", () => {
  assert.deepEqual(
    buildAgentRequest({
      action: "ask",
      input: "ask What does E15 mean?",
      assetId: "dishwasher-bosch-sms6zcw00g",
      limit: 4,
      allowGlobalFallback: false
    }),
    {
      question: "What does E15 mean?",
      asset_id: "dishwasher-bosch-sms6zcw00g",
      limit: 4,
      allow_global_fallback: false
    }
  );

  assert.deepEqual(
    buildAgentRequest({
      action: "manual_download",
      input: "",
      assetId: "dishwasher-bosch-sms6zcw00g",
      manualResults: {
        candidates: [{ url: "https://example.invalid/manual.pdf" }]
      }
    }),
    {
      asset_id: "dishwasher-bosch-sms6zcw00g",
      url: "https://example.invalid/manual.pdf"
    }
  );
});

test("agent command builder preserves selected chip context for backend execute", () => {
  assert.equal(
    buildAgentCommandInput({
      action: "search",
      input: "E15",
      assetId: "dishwasher-bosch-sms6zcw00g",
      limit: 4,
      allowGlobalFallback: true
    }),
    "search asset_id=dishwasher-bosch-sms6zcw00g limit=4 allow_global_fallback=true E15"
  );
});

test("renders top chat with quick actions and structured output cards", async () => {
  const fixtures = await loadCanonicalFixtures();
  const html = renderAgentChat({
    devices: { items: fixtures.devicesList.devices },
    selectedAssetId: "dishwasher-bosch-sms6zcw00g",
    agent: {
      selectedAction: "ask",
      input: "What does E15 mean?",
      assetId: "dishwasher-bosch-sms6zcw00g",
      limit: 8,
      allowGlobalFallback: true,
      running: false,
      messages: [
        {
          id: "agent-1",
          intent: "answer_question",
          action: "ask",
          actionLabel: "Ask",
          endpoint: "POST /ask",
          input: "What does E15 mean?",
          inputs: {
            question: "What does E15 mean?",
            asset_id: "dishwasher-bosch-sms6zcw00g"
          },
          status: "success",
          result: fixtures.askEvidenceOnlyBoschE15,
          resultSummary: "Evidence-only answer, 1 evidence item(s).",
          error: null
        }
      ]
    }
  });

  assert.match(html, /data-agent-action="ask"/);
  assert.match(html, /data-agent-action="manual_find"/);
  assert.match(html, /data-agent-action="list_devices"/);
  assert.match(html, /intent: answer_question/);
  assert.match(html, /action: POST \/ask/);
  assert.match(html, /Resolution/);
  assert.match(html, /Sources/);
  assert.match(html, /Evidence/);
});

test("POST /agent/execute sends freeform input only in live mode", async () => {
  const calls = [];
  const client = createApiClient({
    mode: "live",
    baseUrl: "http://api.test/",
    fetchImpl: async (url, options) => {
      calls.push({ url, options, body: JSON.parse(options.body) });
      return new Response(
        JSON.stringify({
          input: calls[0].body.input,
          plan: [
            {
              order: 1,
              intent: "device_list",
              tool_call: { action: "list_devices", inputs: {} }
            }
          ],
          steps: [
            {
              order: 1,
              intent: "device_list",
              tool_call: { action: "list_devices", inputs: {} },
              status: "success",
              result: { devices: [] },
              error: null
            }
          ],
          result: { devices: [] }
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" }
        }
      );
    }
  });

  const response = await client.executeAgent({ input: "list devices" });

  assert.equal(calls[0].url, "http://api.test/agent/execute");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(calls[0].body, { input: "list devices" });
  assert.equal(response.steps[0].tool_call.action, "list_devices");
});

test("mock agent execute returns plan, steps, and result", async () => {
  const client = await makeMockClient();

  const response = await client.executeAgent({
    input: "ask asset_id=dishwasher-bosch-sms6zcw00g What does E15 mean?"
  });

  assert.equal(response.plan[0].tool_call.action, "ask");
  assert.equal(response.steps[0].status, "success");
  assert.equal(response.steps[0].tool_call.inputs.question, "What does E15 mean?");
  assert.equal(response.result.generated, false);
});

test("POST /devices sends expected JSON payload", async () => {
  const calls = [];
  const client = createApiClient({
    mode: "live",
    baseUrl: "http://api.test/",
    fetchImpl: async (url, options) => {
      calls.push({ url, options, body: JSON.parse(options.body) });
      return new Response(JSON.stringify({ device: calls[0].body }), {
        status: 201,
        headers: { "content-type": "application/json" }
      });
    }
  });
  const payload = buildCreateDevicePayload({
    brand: "ASUS",
    model: "RT-AX88U",
    device_type: "router",
    aliases: "wifi router"
  });

  const response = await client.createDevice(payload);

  assert.equal(calls[0].url, "http://api.test/devices");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers["content-type"], "application/json");
  assert.deepEqual(calls[0].body, payload);
  assert.deepEqual(response.device, payload);
});

test("mock client returns device information for known source documents", async () => {
  const client = await makeMockClient();

  const response = await client.getDeviceInformation(
    "dishwasher-bosch-sms6zcw00g"
  );

  assert.equal(response.device.support_url, "https://www.bosch-home.com/support");
  assert.ok(
    response.documents.some(
      (document) =>
        document.source_type === "manual" &&
        document.source_path.includes("manuals/quick-manual.md")
    )
  );
});

test("renders device information with guarantee and source visibility", async () => {
  const fixtures = await loadCanonicalFixtures();
  const deviceInformation = await readFixture("device-information-bosch.json");
  const html = renderDeviceInformation({
    selectedAssetId: "dishwasher-bosch-sms6zcw00g",
    devices: {
      items: fixtures.devicesList.devices
    },
    deviceInfo: {
      assetId: "dishwasher-bosch-sms6zcw00g",
      response: deviceInformation,
      error: null,
      loading: false
    }
  });

  assert.match(html, /Device Info/);
  assert.match(html, /Warranty \/ guarantee until/);
  assert.match(html, /guarantee: missing/);
  assert.match(html, /https:\/\/www\.bosch-home\.com\/support/);
  assert.match(html, /quick-manual\.md/);
  assert.match(html, /markdown ready/);
});

test("renders ambiguous search response with candidate choices", async () => {
  const response = await readFixture("search-ambiguous-dishwasher.json");
  const html = renderSearchResponse(response);
  assert.match(html, /resolution: ambiguous/);
  assert.match(html, /Bosch/);
  assert.match(html, /Siemens/);
  assert.match(html, /data-action="choose-candidate"/);
});

test("renders scoped search result with scope, source, section, and snippet", async () => {
  const response = await readFixture("search-scoped-bosch-e15.json");
  const html = renderSearchResponse(response);
  assert.match(html, /device-scoped/);
  assert.match(
    html,
    /fixtures\/source_docs\/devices\/dishwasher-bosch-sms6zcw00g\/manuals\/quick-manual.md/
  );
  assert.match(html, /Troubleshooting &gt; Error Codes &gt; E15/);
  assert.match(html, /E15 means the water protection system/);
});

test("renders ask response with answer, sources, and evidence", async () => {
  const response = await readFixture("ask-evidence-only-bosch-e15.json");
  const html = renderAskResponse(response);
  assert.match(html, /Chat is disabled/);
  assert.match(html, /evidence-only/);
  assert.match(
    html,
    /fixtures\/markdown_docs\/devices\/dishwasher-bosch-sms6zcw00g\/manuals\/quick-manual.md/
  );
  assert.match(html, /Evidence/);
});

test("renders ask PDF evidence with local source link", async () => {
  const response = await readFixture("ask-evidence-only-bosch-e15.json");
  response.sources = [
    "source_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/manual.pdf"
  ];
  response.evidence[0].source_path =
    "source_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/manual.pdf";

  const html = renderAskResponse(response, {
    apiBase: "http://api.test"
  });

  assert.match(html, /Open PDF/);
  assert.match(
    html,
    /http:\/\/api\.test\/source-file\?path=source_docs%2Fdevices%2Fdishwasher-bosch-sms6zcw00g%2Fmanuals%2Fmanual\.pdf/
  );
});

test("renders ask waiting indicator while a response is pending", () => {
  const html = renderApp({
    config: { mode: "mock", apiBase: "http://127.0.0.1:8000" },
    status: { available: true, message: "ok" },
    activeView: "ask",
    selectedAssetId: "",
    devices: { items: [], error: null, notice: "", lastRequest: null },
    search: {
      query: "",
      assetId: "",
      limit: 8,
      allowGlobalFallback: true,
      response: null,
      error: null
    },
    ask: {
      question: "What does E15 mean?",
      assetId: "",
      limit: 8,
      allowGlobalFallback: false,
      pending: true,
      response: null,
      error: null
    },
    manuals: { query: "", assetId: "", results: null, notice: "", error: null },
    ingest: { status: null, report: null, error: null }
  });

  assert.match(html, /waiting for answer/);
  assert.match(html, /Waiting\.\.\./);
  assert.match(html, /class="nav-dot"/);
  assert.match(html, /role="status"/);
});

test("renders API error state", async () => {
  const response = await readFixture("api-error.json");
  const html = renderError(response.error);
  assert.match(html, /api_unavailable/);
  assert.match(html, /API is unavailable/);
  assert.match(html, /retryable/);
});

test("mock client returns ambiguous ask without an answer", async () => {
  const client = await makeMockClient();
  const response = await client.ask({
    question: "dishwasher error code",
    asset_id: null,
    limit: 8,
    allow_global_fallback: false
  });
  const html = renderAskResponse(response);
  assert.equal(response.generated, false);
  assert.equal(response.answer, "");
  assert.match(html, /No answer was generated/);
  assert.match(html, /Bosch/);
  assert.match(html, /Siemens/);
});

test("mock client keeps selected ambiguous candidates device-scoped", async () => {
  const client = await makeMockClient();
  const response = await client.search({
    query: "dishwasher error code",
    asset_id: "dishwasher-siemens-sn23ec14cg",
    filters: null,
    limit: 8,
    allow_global_fallback: true
  });

  assert.equal(response.scope, "device");
  assert.equal(response.resolution.asset_id, "dishwasher-siemens-sn23ec14cg");
  assert.ok(response.results.length > 0);
  assert.ok(
    response.results.every(
      (result) => result.asset_id === "dishwasher-siemens-sn23ec14cg"
    )
  );
  assert.match(renderSearchResponse(response), /E24 means the drain system/);
});

test("ui source does not import backend implementation modules", async () => {
  const files = ["agent.js", "api.js", "app.js", "device.js", "fixtures.js", "render.js"];
  for (const file of files) {
    const source = await readFile(join(here, "..", "src", file), "utf8");
    assert.doesNotMatch(
      source,
      /from\s+["'][^"']*(homewiki|lancedb|ask_service|search_service|llm)[^"']*["']/i,
      file
    );
  }
});
