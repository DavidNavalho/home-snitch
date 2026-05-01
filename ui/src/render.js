export function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function jsonBlock(value) {
  return `<pre class="json-block"><code>${escapeHtml(
    JSON.stringify(value, null, 2)
  )}</code></pre>`;
}

function chip(text, tone = "") {
  return `<span class="chip ${tone}">${escapeHtml(text)}</span>`;
}

function isPdfPath(value) {
  return /\.pdf(?:$|[?#])/i.test(String(value ?? ""));
}

function sourceFileHref(sourcePath, apiBase = "") {
  const base = String(apiBase ?? "").replace(/\/+$/g, "");
  return `${base}/source-file?path=${encodeURIComponent(sourcePath)}`;
}

function renderSourcePath(sourcePath, apiBase = "") {
  const path = String(sourcePath ?? "");
  const link = isPdfPath(path)
    ? `<a class="source-link" href="${escapeHtml(
        sourceFileHref(path, apiBase)
      )}" target="_blank" rel="noreferrer">Open PDF</a>`
    : "";
  return `<div class="path-line source-path"><span>${escapeHtml(
    path
  )}</span>${link}</div>`;
}

function renderPendingCue() {
  return `<div class="pending-box" role="status" aria-live="polite">
    <span class="spinner" aria-hidden="true"></span>
    <strong>Waiting for answer</strong>
  </div>`;
}

function percent(value) {
  if (typeof value !== "number") {
    return "n/a";
  }
  return `${Math.round(value * 100)}%`;
}

function hasValue(value) {
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  return value !== null && value !== undefined && String(value).trim() !== "";
}

function displayValue(value) {
  if (Array.isArray(value)) {
    return value.length ? value.join(", ") : "Not stored";
  }
  return hasValue(value) ? value : "Not stored";
}

function infoStatus(label, value) {
  const stored = hasValue(value);
  return chip(`${label}: ${stored ? "stored" : "missing"}`, stored ? "green" : "amber");
}

function infoField(label, value) {
  return `<div class="info-field">
    <span>${escapeHtml(label)}</span>
    <strong>${escapeHtml(displayValue(value))}</strong>
  </div>`;
}

function linkField(label, value) {
  if (!hasValue(value)) {
    return infoField(label, value);
  }
  return `<div class="info-field">
    <span>${escapeHtml(label)}</span>
    <strong><a href="${escapeHtml(value)}" target="_blank" rel="noreferrer">${escapeHtml(value)}</a></strong>
  </div>`;
}

function documentTypeLabel(type) {
  const labels = {
    photo_ocr: "photo OCR"
  };
  return labels[type] ?? type ?? "other";
}

function documentsForType(documents, type) {
  return (documents ?? []).filter((document) => document.source_type === type);
}

function scopeLabel(scope) {
  if (scope === "device") {
    return "device-scoped";
  }
  if (scope === "filtered") {
    return "filtered";
  }
  if (scope === "global") {
    return "global";
  }
  return "none";
}

function statusTone(status) {
  if (status === "exact") {
    return "green";
  }
  if (status === "ambiguous") {
    return "amber";
  }
  if (status === "none") {
    return "red";
  }
  return "blue";
}

export function renderError(error) {
  if (!error) {
    return "";
  }
  const details = error.details ? jsonBlock(error.details) : "";
  const status = error.status ? ` HTTP ${error.status}.` : "";
  return `<div class="error-box" role="alert"><strong>${escapeHtml(
    error.code || "api_error"
  )}</strong>${status} ${escapeHtml(error.message || "Request failed.")}${details}</div>`;
}

export function renderNotice(text) {
  return text ? `<div class="notice">${escapeHtml(text)}</div>` : "";
}

export function renderDeviceOptions(devices, selectedAssetId = "") {
  const options = [
    `<option value="">Resolve from text or search globally</option>`,
    ...devices.map((device) => {
      const label = `${device.brand} ${device.model} (${device.room ?? "no room"})`;
      const selected =
        device.asset_id === selectedAssetId ? " selected" : "";
      return `<option value="${escapeHtml(device.asset_id)}"${selected}>${escapeHtml(
        label
      )}</option>`;
    })
  ];
  return options.join("");
}

export function renderDeviceTable(devices) {
  if (!devices?.length) {
    return `<div class="empty">No devices loaded.</div>`;
  }
  const rows = devices
    .map(
      (device) => `<tr>
        <td><strong>${escapeHtml(device.brand)}</strong></td>
        <td>${escapeHtml(device.model)}</td>
        <td>${escapeHtml(device.device_type)}</td>
        <td>${escapeHtml(device.room ?? "")}</td>
        <td>${escapeHtml((device.aliases ?? []).join(", "))}</td>
        <td><code>${escapeHtml(device.asset_id)}</code></td>
        <td><button type="button" data-action="show-device-info" data-asset-id="${escapeHtml(
          device.asset_id
        )}">Info</button></td>
      </tr>`
    )
    .join("");
  return `<div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Brand</th>
          <th>Model</th>
          <th>Type</th>
          <th>Room</th>
          <th>Aliases</th>
          <th>Asset ID</th>
          <th></th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

export function renderResolution(resolution, scope = null) {
  if (!resolution) {
    return "";
  }
  const filters = resolution.filters ?? {};
  const filterText = Object.entries(filters)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `${key}: ${value}`)
    .join(", ");
  return `<div class="status-row">
    ${chip(`resolution: ${resolution.status}`, statusTone(resolution.status))}
    ${scope ? chip(`scope: ${scopeLabel(scope)}`, scope === "device" ? "green" : "blue") : ""}
    ${chip(`confidence: ${percent(resolution.confidence)}`)}
    ${resolution.asset_id ? chip(`asset: ${resolution.asset_id}`) : ""}
    ${(resolution.matched_on ?? []).length ? chip(`matched: ${resolution.matched_on.join(", ")}`) : ""}
    ${filterText ? chip(`filters: ${filterText}`) : ""}
  </div>`;
}

export function renderCandidates(candidates, target = "search") {
  if (!candidates?.length) {
    return "";
  }
  const items = candidates
    .map(
      (candidate) => `<div class="candidate-item">
        <div class="item-head">
          <strong>${escapeHtml(candidate.brand ?? "Unknown")} ${escapeHtml(
            candidate.model ?? ""
          )}</strong>
          ${chip(percent(candidate.confidence), "amber")}
        </div>
        <div class="meta-line">${escapeHtml(candidate.device_type ?? "")} / ${escapeHtml(
          candidate.room ?? ""
        )} / <code>${escapeHtml(candidate.asset_id)}</code></div>
        <div class="inline-actions">
          <button type="button" data-action="choose-candidate" data-target="${escapeHtml(
            target
          )}" data-asset-id="${escapeHtml(candidate.asset_id)}">Choose</button>
        </div>
      </div>`
    )
    .join("");
  return `<div class="candidate-list">${items}</div>`;
}

export function renderSearchResponse(response) {
  if (!response) {
    return `<div class="empty">No search has been run.</div>`;
  }
  const ambiguous =
    response.resolution?.status === "ambiguous"
      ? `<div class="warning-box"><strong>Ambiguous device.</strong> Choose a candidate to run a scoped search.</div>${renderCandidates(
          response.resolution.candidates,
          "search"
        )}`
      : "";
  const results = response.results?.length
    ? `<div class="result-list">${response.results
        .map(
          (result) => `<div class="result-item">
            <div class="item-head">
              <strong>${escapeHtml(result.section_title)}</strong>
              <span>${chip(scopeLabel(response.scope), response.scope === "device" ? "green" : "blue")} ${chip(
                result.source_type ?? "source"
              )}</span>
            </div>
            <div class="path-line">${escapeHtml(result.source_path)}</div>
            <div class="path-line">${escapeHtml(result.markdown_path)}</div>
            <div class="meta-line">asset: <code>${escapeHtml(
              result.asset_id ?? "global"
            )}</code>${typeof result.score === "number" ? ` / score: ${escapeHtml(result.score)}` : ""}</div>
            <p class="snippet">${escapeHtml(result.text)}</p>
          </div>`
        )
        .join("")}</div>`
    : `<div class="empty">No results returned.</div>`;

  return `<section class="panel">
    <div class="panel-header">
      <h3>Search Response</h3>
      <span class="meta-line">${escapeHtml(response.query ?? "")}</span>
    </div>
    <div class="panel-body">
      ${renderResolution(response.resolution, response.scope)}
      ${ambiguous}
      ${results}
    </div>
  </section>`;
}

export function renderAskResponse(response, options = {}) {
  const { apiBase = "", pending = false } = options;
  if (!response) {
    if (pending) {
      return renderPendingCue();
    }
    return `<div class="empty">No question has been asked.</div>`;
  }
  if (response.resolution?.status === "ambiguous") {
    return `<section class="panel">
      <div class="panel-header"><h3>Ask Response</h3></div>
      <div class="panel-body">
        ${renderResolution(response.resolution)}
        <div class="warning-box"><strong>Ambiguous device.</strong> No answer was generated.</div>
        ${renderCandidates(response.resolution.candidates, "ask")}
      </div>
    </section>`;
  }

  const sources = response.sources?.length
    ? `<div><strong>Sources</strong><div class="result-list">${response.sources
        .map((source) => renderSourcePath(source, apiBase))
        .join("")}</div></div>`
    : "";
  const evidence = response.evidence?.length
    ? `<div><strong>Evidence</strong><div class="evidence-list">${response.evidence
        .map(
          (item) => `<div class="evidence-item">
            <div class="item-head">
              <strong>${escapeHtml(item.section_title)}</strong>
              ${chip(item.source_type ?? "source")}
            </div>
            ${renderSourcePath(item.source_path, apiBase)}
            <p class="snippet">${escapeHtml(item.text)}</p>
          </div>`
        )
        .join("")}</div></div>`
    : "";
  const missing = response.missing_information?.length
    ? `<div class="warning-box"><strong>Missing information</strong><br>${escapeHtml(
        response.missing_information.join("; ")
      )}</div>`
    : "";

  return `<section class="panel">
    <div class="panel-header"><h3>Ask Response</h3></div>
    <div class="panel-body">
      ${renderResolution(response.resolution)}
      <div class="status-row">
        ${chip(response.generated ? "generated" : "evidence-only", response.generated ? "blue" : "green")}
        ${chip(`confidence: ${response.confidence}/10`)}
      </div>
      <p class="answer">${escapeHtml(response.answer)}</p>
      ${missing}
      ${sources}
      ${evidence}
    </div>
  </section>`;
}

export function renderManualResults(results, selectedAssetId) {
  if (!results) {
    return `<div class="empty">No manual search has been run.</div>`;
  }
  if (!results.candidates?.length) {
    return `<div class="empty">No manual candidates returned.</div>`;
  }
  return `<div class="manual-list">${results.candidates
    .map(
      (candidate) => `<div class="manual-item">
        <div class="item-head">
          <strong>${escapeHtml(candidate.title)}</strong>
          ${chip(candidate.is_pdf ? "PDF" : "HTML", candidate.is_pdf ? "blue" : "")}
        </div>
        <div class="path-line">${escapeHtml(candidate.url)}</div>
        <div class="meta-line">rank: ${escapeHtml(candidate.rank)} / host: ${escapeHtml(
          candidate.source_host ?? ""
        )}</div>
        <button type="button" data-action="download-manual" data-url="${escapeHtml(
          candidate.url
        )}" data-asset-id="${escapeHtml(
          selectedAssetId || candidate.asset_id || ""
        )}">Download</button>
      </div>`
    )
    .join("")}</div>`;
}

function renderDevicePicker(devices, selectedAssetId) {
  if (!devices?.length) {
    return `<div class="empty">No devices loaded.</div>`;
  }
  return `<div class="device-picker">${devices
    .map((device) => {
      const active = device.asset_id === selectedAssetId ? " active" : "";
      return `<button type="button" class="device-picker-item${active}" data-action="show-device-info" data-asset-id="${escapeHtml(
        device.asset_id
      )}">
        <strong>${escapeHtml(device.brand)} ${escapeHtml(device.model)}</strong>
        <span>${escapeHtml(device.device_type)} / ${escapeHtml(device.room ?? "no room")}</span>
        <code>${escapeHtml(device.asset_id)}</code>
      </button>`;
    })
    .join("")}</div>`;
}

function renderDocumentMetrics(documents) {
  const metrics = [
    ["manual", "Manuals"],
    ["note", "Notes"],
    ["receipt", "Receipts"],
    ["profile", "Profiles"],
    ["photo_ocr", "Photos"]
  ];
  return `<div class="source-metrics">${metrics
    .map(([type, label]) => {
      const count = documentsForType(documents, type).length;
      return `<div class="source-metric"><strong>${escapeHtml(count)}</strong>${escapeHtml(
        label
      )}</div>`;
    })
    .join("")}</div>`;
}

function renderDeviceDocuments(documents) {
  if (!documents?.length) {
    return `<div class="empty">No source documents found for this device.</div>`;
  }
  return `<div class="document-list">${documents
    .map(
      (document) => `<div class="document-item">
        <div class="item-head">
          <strong>${escapeHtml(document.name)}</strong>
          <span>
            ${chip(documentTypeLabel(document.source_type))}
            ${chip(document.available_as_markdown ? "markdown ready" : "source only", document.available_as_markdown ? "green" : "amber")}
          </span>
        </div>
        ${
          document.source_path
            ? `<div class="path-line">source: ${escapeHtml(document.source_path)}</div>`
            : ""
        }
        ${
          document.markdown_path
            ? `<div class="path-line">markdown: ${escapeHtml(document.markdown_path)}</div>`
            : ""
        }
      </div>`
    )
    .join("")}</div>`;
}

function renderCoverage(device, documents) {
  return `<div class="status-row">
    ${infoStatus("serial", device.serial_number)}
    ${infoStatus("purchase", device.purchase_date)}
    ${infoStatus("guarantee", device.warranty_until)}
    ${infoStatus("support", device.support_url)}
    ${infoStatus("manuals", documentsForType(documents, "manual"))}
    ${infoStatus("notes", device.notes)}
  </div>`;
}

export function renderDeviceInformation(state) {
  const selectedAssetId =
    state.deviceInfo.assetId ||
    state.selectedAssetId ||
    state.devices.items[0]?.asset_id ||
    "";
  const response = state.deviceInfo.response;
  const selectedDevice =
    response?.device?.asset_id === selectedAssetId
      ? response.device
      : state.devices.items.find((device) => device.asset_id === selectedAssetId);
  const documents =
    response?.device?.asset_id === selectedAssetId ? response.documents ?? [] : [];

  if (!selectedDevice) {
    return `<section class="panel">
      <div class="panel-header"><h2>Device Info</h2></div>
      <div class="panel-body">
        ${renderDevicePicker(state.devices.items, selectedAssetId)}
        <div class="empty">No device selected.</div>
      </div>
    </section>`;
  }

  return `<section class="panel">
    <div class="panel-header">
      <h2>Device Info</h2>
      <button type="button" data-action="refresh-device-info" data-asset-id="${escapeHtml(
        selectedDevice.asset_id
      )}">Refresh</button>
    </div>
    <div class="panel-body">
      ${renderError(state.deviceInfo.error)}
      ${state.deviceInfo.loading ? `<div class="notice">Loading device information...</div>` : ""}
      <div class="device-info-layout">
        ${renderDevicePicker(state.devices.items, selectedDevice.asset_id)}
        <div class="device-detail">
          <div class="device-detail-header">
            <div>
              <h3>${escapeHtml(selectedDevice.brand)} ${escapeHtml(selectedDevice.model)}</h3>
              <div class="meta-line">${escapeHtml(selectedDevice.device_type)} / ${escapeHtml(
                selectedDevice.room ?? "no room"
              )} / <code>${escapeHtml(selectedDevice.asset_id)}</code></div>
            </div>
            <div class="status-row">
              ${chip(selectedDevice.device_type)}
              ${selectedDevice.room ? chip(selectedDevice.room, "blue") : ""}
            </div>
          </div>
          ${renderCoverage(selectedDevice, documents)}
          <div class="info-section-grid">
            <div class="info-card">
              <h4>Profile</h4>
              <div class="info-field-grid">
                ${infoField("Brand", selectedDevice.brand)}
                ${infoField("Model", selectedDevice.model)}
                ${infoField("Type", selectedDevice.device_type)}
                ${infoField("Room", selectedDevice.room)}
                ${infoField("Serial number", selectedDevice.serial_number)}
                ${infoField("Aliases", selectedDevice.aliases ?? [])}
                ${infoField("Tags", selectedDevice.tags ?? [])}
              </div>
            </div>
            <div class="info-card">
              <h4>Guarantee & Support</h4>
              <div class="info-field-grid">
                ${infoField("Purchase date", selectedDevice.purchase_date)}
                ${infoField("Warranty / guarantee until", selectedDevice.warranty_until)}
                ${linkField("Support URL", selectedDevice.support_url)}
              </div>
            </div>
          </div>
          <div class="info-card">
            <h4>Known Sources</h4>
            ${renderDocumentMetrics(documents)}
            ${renderDeviceDocuments(documents)}
          </div>
          <div class="info-card">
            <h4>Notes</h4>
            <p class="snippet">${escapeHtml(displayValue(selectedDevice.notes))}</p>
          </div>
        </div>
      </div>
    </div>
  </section>`;
}

export function renderIngestReport(report) {
  if (!report) {
    return `<div class="empty">No ingest run has completed.</div>`;
  }
  const metrics = ["converted", "indexed", "skipped", "failed", "removed"]
    .map(
      (key) => `<div class="metric"><strong>${escapeHtml(report[key] ?? 0)}</strong>${escapeHtml(
        key
      )}</div>`
    )
    .join("");
  const warnings = report.warnings?.length
    ? `<div class="warning-box">${escapeHtml(report.warnings.join("; "))}</div>`
    : "";
  const errors = report.errors?.length
    ? report.errors.map(renderError).join("")
    : "";
  return `<div class="metric-grid">${metrics}</div>${warnings}${errors}`;
}

function renderStatus(status, config) {
  const tone = status.available === false ? "red" : status.available ? "green" : "amber";
  const label =
    status.available === false
      ? "API unavailable"
      : status.available
        ? "API available"
        : "API unchecked";
  return `<div class="status-row">
    ${chip(config.mode === "live" ? "live API" : "mock responses", config.mode === "live" ? "blue" : "green")}
    ${chip(label, tone)}
    <span>${escapeHtml(status.message ?? "")}</span>
  </div>`;
}

function navButton(activeView, id, label, pending = false) {
  const classes = [activeView === id ? "active" : "", pending ? "pending" : ""]
    .filter(Boolean)
    .join(" ");
  const ariaLabel = pending ? ` aria-label="${escapeHtml(label)} waiting"` : "";
  return `<button type="button" data-action="set-tab" data-tab="${id}" class="${classes}"${ariaLabel}>
    <span>${escapeHtml(label)}</span>
    ${pending ? `<span class="nav-dot" aria-hidden="true"></span>` : ""}
  </button>`;
}

function renderDevicesView(state) {
  return `<section class="panel">
    <div class="panel-header">
      <h2>Devices</h2>
      <button type="button" data-action="refresh-devices">Refresh</button>
    </div>
    <div class="panel-body">
      ${renderError(state.devices.error)}
      ${renderNotice(state.devices.notice)}
      ${renderDeviceTable(state.devices.items)}
    </div>
  </section>
  <section class="panel">
    <div class="panel-header"><h3>Add Device</h3></div>
    <div class="panel-body">
      <form id="device-create-form" class="form-grid">
        <label>Brand<input name="brand" required placeholder="Bosch"></label>
        <label>Model<input name="model" required placeholder="SMS6ZCW00G"></label>
        <label>Type<input name="device_type" required placeholder="dishwasher"></label>
        <label>Room<input name="room" placeholder="kitchen"></label>
        <label class="wide">Aliases<input name="aliases" placeholder="kitchen dishwasher, dishwasher"></label>
        <label class="wide">Asset ID<input name="asset_id" placeholder="optional"></label>
        <div class="full inline-actions">
          <button class="primary" type="submit">Add Device</button>
        </div>
      </form>
      ${state.devices.lastRequest ? `<div><strong>Last create payload</strong>${jsonBlock(state.devices.lastRequest)}</div>` : ""}
    </div>
  </section>`;
}

function renderSearchView(state) {
  return `<section class="panel">
    <div class="panel-header"><h2>Search</h2></div>
    <div class="panel-body">
      <form id="search-form" class="form-grid">
        <label class="wide">Query<input name="query" required value="${escapeHtml(
          state.search.query
        )}" placeholder="E15"></label>
        <label class="wide">Device<select name="asset_id">${renderDeviceOptions(
          state.devices.items,
          state.search.assetId || state.selectedAssetId
        )}</select></label>
        <label>Limit<input name="limit" type="number" min="1" max="50" value="${escapeHtml(
          state.search.limit
        )}"></label>
        <label class="checkbox-label"><input name="allow_global_fallback" type="checkbox" ${
          state.search.allowGlobalFallback ? "checked" : ""
        }> Global fallback</label>
        <div class="full inline-actions">
          <button class="primary" type="submit">Search</button>
        </div>
      </form>
      ${renderError(state.search.error)}
    </div>
  </section>
  ${renderSearchResponse(state.search.response)}`;
}

function renderAskView(state) {
  return `<section class="panel">
    <div class="panel-header">
      <h2>Ask</h2>
      ${state.ask.pending ? chip("waiting for answer", "amber") : ""}
    </div>
    <div class="panel-body">
      <form id="ask-form" class="form-grid">
        <label class="wide">Question<textarea name="question" required placeholder="What does E15 mean?">${escapeHtml(
          state.ask.question
        )}</textarea></label>
        <label class="wide">Device<select name="asset_id">${renderDeviceOptions(
          state.devices.items,
          state.ask.assetId || state.selectedAssetId
        )}</select></label>
        <label>Limit<input name="limit" type="number" min="1" max="50" value="${escapeHtml(
          state.ask.limit
        )}"></label>
        <label class="checkbox-label"><input name="allow_global_fallback" type="checkbox" ${
          state.ask.allowGlobalFallback ? "checked" : ""
        }> Global fallback</label>
        <div class="full inline-actions">
          <button class="primary" type="submit" ${
            state.ask.pending ? "disabled" : ""
          }>${state.ask.pending ? "Waiting..." : "Ask"}</button>
        </div>
      </form>
      ${renderError(state.ask.error)}
    </div>
  </section>
  ${renderAskResponse(state.ask.response, {
    apiBase: state.config.apiBase,
    pending: state.ask.pending
  })}`;
}

function renderManualsView(state) {
  return `<section class="panel">
    <div class="panel-header"><h2>Manuals</h2></div>
    <div class="panel-body">
      <form id="manual-find-form" class="form-grid">
        <label class="wide">Device<select name="asset_id">${renderDeviceOptions(
          state.devices.items,
          state.manuals.assetId || state.selectedAssetId
        )}</select></label>
        <label class="wide">Query<input name="query" value="${escapeHtml(
          state.manuals.query
        )}" placeholder="Bosch SMS6ZCW00G manual"></label>
        <div class="full inline-actions">
          <button class="primary" type="submit">Find Manuals</button>
        </div>
      </form>
      ${renderError(state.manuals.error)}
      ${renderNotice(state.manuals.notice)}
      ${renderManualResults(state.manuals.results, state.manuals.assetId || state.selectedAssetId)}
    </div>
  </section>`;
}

function renderIngestView(state) {
  return `<section class="panel">
    <div class="panel-header">
      <h2>Ingest</h2>
      <div class="inline-actions">
        <button type="button" data-action="refresh-status">Refresh Status</button>
        <button class="primary" type="button" data-action="run-ingest">Run Ingest</button>
      </div>
    </div>
    <div class="panel-body">
      ${renderError(state.ingest.error)}
      <div><strong>Status</strong>${state.ingest.status ? jsonBlock(state.ingest.status) : `<div class="empty">No status loaded.</div>`}</div>
      <div><strong>Last ingest</strong>${renderIngestReport(state.ingest.report)}</div>
    </div>
  </section>`;
}

function renderActiveView(state) {
  if (state.activeView === "search") {
    return renderSearchView(state);
  }
  if (state.activeView === "ask") {
    return renderAskView(state);
  }
  if (state.activeView === "manuals") {
    return renderManualsView(state);
  }
  if (state.activeView === "device-info") {
    return renderDeviceInformation(state);
  }
  if (state.activeView === "ingest") {
    return renderIngestView(state);
  }
  return renderDevicesView(state);
}

export function renderApp(state) {
  return `<header class="topbar">
    <div class="brand">
      <h1>Home Wiki</h1>
      ${renderStatus(state.status, state.config)}
    </div>
    <form id="config-form" class="config-form">
      <label>Mode
        <select name="mode">
          <option value="mock" ${state.config.mode === "mock" ? "selected" : ""}>Mock</option>
          <option value="live" ${state.config.mode === "live" ? "selected" : ""}>Live</option>
        </select>
      </label>
      <label>API Base
        <input name="apiBase" value="${escapeHtml(state.config.apiBase)}">
      </label>
      <button type="submit">Save</button>
      <button type="button" data-action="check-status">Check</button>
    </form>
  </header>
  <div class="content-grid">
    <nav class="nav" aria-label="Main">
      ${navButton(state.activeView, "devices", "Devices")}
      ${navButton(state.activeView, "device-info", "Info")}
      ${navButton(state.activeView, "search", "Search")}
      ${navButton(state.activeView, "ask", "Ask", state.ask.pending)}
      ${navButton(state.activeView, "manuals", "Manuals")}
      ${navButton(state.activeView, "ingest", "Ingest")}
    </nav>
    <main class="workspace">
      ${renderActiveView(state)}
    </main>
  </div>`;
}
