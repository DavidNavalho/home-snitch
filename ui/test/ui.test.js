import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { createApiClient } from "../src/api.js";
import { buildCreateDevicePayload } from "../src/device.js";
import { createMemoryFixtureLoader, FIXTURE_KEYS } from "../src/fixtures.js";
import {
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
  const files = ["api.js", "app.js", "device.js", "fixtures.js", "render.js"];
  for (const file of files) {
    const source = await readFile(join(here, "..", "src", file), "utf8");
    assert.doesNotMatch(
      source,
      /from\s+["'][^"']*(homewiki|lancedb|ask_service|search_service|llm)[^"']*["']/i,
      file
    );
  }
});
