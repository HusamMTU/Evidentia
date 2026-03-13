const state = {
  rows: [],
  nextToken: null,
  selectedKey: null,
  selectedVector: null,
  similarResults: null,
  loadedConfig: null,
  vectorBuckets: [],
  indexes: [],
  indexDetails: null,
  config: {},
  envContext: {},
  validationError: null,
  summary: null,
};

const $ = (id) => document.getElementById(id);

function setStatus(message, tone = "info") {
  const el = $("status");
  el.textContent = message;
  el.dataset.tone = tone;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function compactText(value, maxLength = 140) {
  const normalized = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "";
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1)}...`;
}

function toPretty(value) {
  return JSON.stringify(value, null, 2);
}

function buildQuery(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      search.set(key, String(value));
    }
  });
  return search.toString();
}

async function apiGet(path, params = {}) {
  const query = buildQuery(params);
  const url = query ? `${path}?${query}` : path;
  const res = await fetch(url);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || `Request failed: ${res.status}`);
  }
  return data;
}

function getConfigParams() {
  return {
    region: $("region").value.trim(),
    vector_bucket_name: $("vector_bucket_name").value.trim(),
    index_name: $("index_name").value.trim(),
  };
}

function hasCompleteConfig() {
  const config = getConfigParams();
  return Boolean(config.region && config.vector_bucket_name && config.index_name);
}

function sameConfig(left, right) {
  return (
    (left?.region || "") === (right?.region || "") &&
    (left?.vector_bucket_name || "") === (right?.vector_bucket_name || "") &&
    (left?.index_name || "") === (right?.index_name || "")
  );
}

function currentDataSourceId() {
  return state.envContext.knowledge_base_data_source_id || "";
}

function applyConfig(config) {
  state.config = config || {};
  $("region").value = config.region || "";
  $("vector_bucket_name").value = config.vector_bucket_name || "";
  $("index_name").value = config.index_name || "";
}

function populateDatalist(id, values) {
  const el = $(id);
  const uniqueValues = [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
  el.innerHTML = uniqueValues.map((value) => `<option value="${escapeHtml(value)}"></option>`).join("");
}

function getVectorBucketName(bucket) {
  if (typeof bucket === "string") {
    return bucket;
  }
  return bucket.vectorBucketName || bucket.name || bucket.vectorBucketArn || "";
}

function getIndexName(index) {
  if (typeof index === "string") {
    return index;
  }
  return index.indexName || index.name || index.indexArn || "";
}

function badgeMarkup(label, variant) {
  return `<span class="badge ${variant}">${escapeHtml(label)}</span>`;
}

function renderPageState() {
  const el = $("page_state");
  if (!state.rows.length) {
    el.textContent = "No vectors loaded";
    return;
  }

  const suffix = state.nextToken ? "More pages available" : "End of sample";
  el.textContent = `${state.rows.length} loaded • ${suffix}`;
}

function similarityInputKey() {
  return $("similarity_key").value.trim();
}

function syncSimilarityKeyFromSelection({ clearResults = true } = {}) {
  $("similarity_key").value = state.selectedKey || "";
  if (clearResults) {
    state.similarResults = null;
  }
  renderSimilarityResults();
}

function renderContext() {
  const contextItems = [
    ["Knowledge Base ID", state.envContext.knowledge_base_id],
    ["Current Data Source ID", state.envContext.knowledge_base_data_source_id],
    ["Assets Bucket", state.envContext.assets_bucket_name],
  ];

  if (state.summary && state.summary.sample_size) {
    contextItems.push([
      "Historical DS IDs In Sample",
      state.summary.historical_data_source_ids?.join(", ") || "None observed",
    ]);
  }

  $("context_grid").innerHTML = contextItems
    .map(([label, value]) => {
      const hasValue = Boolean(String(value || "").trim());
      return `
        <article class="context-item">
          <span class="context-label">${escapeHtml(label)}</span>
          <span class="context-value ${hasValue ? "" : "missing"}">${escapeHtml(value || "Not set")}</span>
        </article>
      `;
    })
    .join("");
}

function filteredRows() {
  const filter = $("search").value.trim().toLowerCase();
  if (!filter) {
    return state.rows;
  }

  return state.rows.filter((row) => {
    return [
      row.key,
      row.data_source_id,
      row.modality,
      row.source_uri,
      row.text_preview,
      row.mime_type,
    ]
      .map((value) => String(value ?? "").toLowerCase())
      .some((value) => value.includes(filter));
  });
}

function previewLabel(row) {
  if (row.text_preview) {
    return row.text_preview;
  }

  const relatedTypes = Object.entries(row.related_content_types || {})
    .map(([name, count]) => `${name} x${count}`)
    .join(", ");
  if (relatedTypes) {
    return `Related: ${relatedTypes}`;
  }

  return "No text preview";
}

function renderRows() {
  const tbody = $("vectors_body");
  const rows = filteredRows();

  if (!rows.length) {
    tbody.innerHTML = `
      <tr class="row-empty">
        <td colspan="6">No vectors match the current filter or the selected index returned no rows.</td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = "";
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    if (row.key === state.selectedKey) {
      tr.classList.add("selected");
    }

    const dsVariant =
      row.is_current_data_source === true
        ? "current"
        : row.is_current_data_source === false
          ? "historical"
          : "muted";

    tr.innerHTML = `
      <td class="row-key">${escapeHtml(row.key || "")}</td>
      <td>${badgeMarkup(row.data_source_id || "<missing>", dsVariant)}</td>
      <td>${badgeMarkup(row.modality || "<missing>", "muted")}</td>
      <td>${escapeHtml(row.page_number || "—")}</td>
      <td><span class="source-linkish" title="${escapeHtml(row.source_uri || "")}">${escapeHtml(compactText(row.source_uri || "—", 72))}</span></td>
      <td><span class="preview-text" title="${escapeHtml(previewLabel(row))}">${escapeHtml(compactText(previewLabel(row), 110))}</span></td>
    `;
    tr.addEventListener("click", async () => {
      const previousSelectedKey = state.selectedKey;
      state.selectedKey = row.key;
      if (previousSelectedKey !== row.key || similarityInputKey() !== row.key) {
        syncSimilarityKeyFromSelection();
      } else {
        renderSimilarityResults();
      }
      renderRows();
      await loadSelectedVector();
    });
    tbody.appendChild(tr);
  });
}

function detailCardMarkup(label, value) {
  return `
    <article class="detail-card">
      <span class="detail-label">${escapeHtml(label)}</span>
      <span class="detail-value">${escapeHtml(value || "—")}</span>
    </article>
  `;
}

function vectorDimension(vectorResponse) {
  const data = vectorResponse?.vector?.data;
  const float32 = data?.float32;
  if (Array.isArray(float32) && float32.length) {
    return String(float32.length);
  }
  const indexDimension = state.indexDetails?.dimension;
  if (Number.isFinite(indexDimension) && indexDimension > 0) {
    return String(indexDimension);
  }
  return null;
}

function vectorTextPreview(vectorResponse) {
  const rawText = vectorResponse?.vector?.metadata?.AMAZON_BEDROCK_TEXT;
  if (typeof rawText === "string" && rawText.trim()) {
    return compactText(rawText, 1800);
  }
  return "No extracted text stored on this vector.";
}

function renderSelection() {
  const content = $("selected_content");

  if (!state.selectedVector?.summary) {
    content.hidden = true;
    $("selected_overview").innerHTML = "";
    $("selected_text").textContent = "";
    $("selected_metadata").textContent = "";
    $("selected_payload").textContent = "";
    renderSimilarityResults();
    return;
  }

  const summary = state.selectedVector.summary;
  const dimension = vectorDimension(state.selectedVector);
  const cards = [
    ["Related Assets", String(summary.related_asset_count || 0)],
    ["Text Length", summary.text_length ? `${summary.text_length} chars` : "None stored"],
    ["Vector Dimension", dimension ? `${dimension} float32 values` : "Not loaded"],
  ];

  $("selected_overview").innerHTML = cards.map(([label, value]) => detailCardMarkup(label, value)).join("");
  $("selected_text").textContent = vectorTextPreview(state.selectedVector);
  $("selected_metadata").textContent = toPretty(state.selectedVector.parsed_bedrock_metadata || {});
  $("selected_payload").textContent = toPretty(state.selectedVector.vector || {});

  content.hidden = false;
  renderSimilarityResults();
}

function renderSimilarityResults() {
  const queryKey = similarityInputKey() || state.selectedKey || "";
  const badge = $("distance_metric_badge");
  const container = $("similar_results_table");
  const raw = $("similar_results_raw");

  if (!state.similarResults) {
    badge.textContent = "Metric unavailable";
    container.innerHTML = queryKey
      ? '<div class="empty-state">Run a similarity query for this key to inspect nearest matches.</div>'
      : '<div class="empty-state">Select a row or enter a vector key to inspect nearest matches.</div>';
    raw.textContent = "";
    return;
  }

  badge.textContent = state.similarResults.distance_metric
    ? `Metric: ${state.similarResults.distance_metric}`
    : "Metric unavailable";

  const matches = state.similarResults.matches || [];
  if (!matches.length) {
    container.innerHTML = `<div class="empty-state">No similarity matches returned for ${escapeHtml(queryKey || "the requested key")}.</div>`;
    raw.textContent = toPretty(state.similarResults);
    return;
  }

  container.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Key</th>
          <th>Distance</th>
          <th>Modality</th>
          <th>Page</th>
          <th>Source</th>
          <th>Preview</th>
        </tr>
      </thead>
      <tbody>
        ${matches
          .map((match) => {
            const summary = match.summary || {};
            const matchKey = match.key || summary.key || "";
            const badges = [];
            if (matchKey && matchKey === queryKey) {
              badges.push(badgeMarkup("Queried", "muted"));
            }
            if (matchKey && matchKey === state.selectedKey && matchKey !== queryKey) {
              badges.push(badgeMarkup("Selected", "muted"));
            }
            return `
              <tr>
                <td class="row-key">
                  ${escapeHtml(matchKey)}
                  ${badges.length ? `<div style="margin-top: 6px; display: flex; gap: 6px; flex-wrap: wrap;">${badges.join("")}</div>` : ""}
                </td>
                <td>${escapeHtml(Number(match.distance || 0).toFixed(6))}</td>
                <td>${escapeHtml(summary.modality || "—")}</td>
                <td>${escapeHtml(summary.page_number || "—")}</td>
                <td><span class="source-linkish" title="${escapeHtml(summary.source_uri || "")}">${escapeHtml(compactText(summary.source_uri || "—", 68))}</span></td>
                <td><span class="preview-text" title="${escapeHtml(previewLabel(summary))}">${escapeHtml(compactText(previewLabel(summary), 110))}</span></td>
              </tr>
            `;
          })
          .join("")}
      </tbody>
    </table>
  `;
  raw.textContent = toPretty(state.similarResults);
}

function summaryItemsMarkup(counts, { currentKey = "", highlightHistorical = false } = {}) {
  const entries = Object.entries(counts || {});
  if (!entries.length) {
    return '<div class="empty-state">No summary data loaded yet.</div>';
  }

  const maxCount = Math.max(...entries.map(([, count]) => Number(count || 0)), 1);

  return entries
    .map(([name, count]) => {
      const normalizedCount = Number(count || 0);
      const width = Math.max(8, Math.round((normalizedCount / maxCount) * 100));
      const isCurrent = currentKey && name === currentKey;
      const badge =
        isCurrent
          ? badgeMarkup("Current", "current")
          : name === "<missing>"
            ? badgeMarkup("Missing", "muted")
            : highlightHistorical && currentKey
              ? badgeMarkup("Historical", "historical")
              : "";

      return `
        <article class="summary-item">
          <div class="summary-line">
            <span class="summary-name">${escapeHtml(name)}</span>
            <span class="summary-count">${escapeHtml(normalizedCount)}</span>
          </div>
          ${badge ? `<div style="margin-top: 8px;">${badge}</div>` : ""}
          <div class="summary-bar">
            <div class="summary-bar-fill ${!isCurrent && highlightHistorical && currentKey ? "alt" : ""}" style="width: ${width}%"></div>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderSummary() {
  const summary = state.summary;
  const sampleSize = summary?.sample_size || 0;
  $("summary_sample_size").textContent = String(sampleSize);

  $("data_source_summary").innerHTML = summaryItemsMarkup(summary?.data_source_counts, {
    currentKey: summary?.current_data_source_id || currentDataSourceId(),
    highlightHistorical: true,
  });
  $("modality_summary").innerHTML = summaryItemsMarkup(summary?.modality_counts);
}

async function loadDefaultConfig() {
  try {
    const data = await apiGet("/api/config");
    applyConfig(data.config || {});
    state.envContext = data.env_context || {};
    state.validationError = data.validation_error || null;
    renderContext();
    renderPageState();

    if (state.validationError) {
      setStatus(`${state.validationError} Discover resources or fill the missing fields.`, "warn");
    } else if (hasCompleteConfig()) {
      setStatus("Loaded config from environment.", "success");
    } else {
      setStatus("Loaded partial environment config.", "warn");
    }
  } catch (err) {
    setStatus(err.message, "error");
  }
}

async function loadVectorBuckets() {
  const region = $("region").value.trim();
  if (!region) {
    populateDatalist("vector_bucket_options", []);
    return [];
  }

  const data = await apiGet("/api/vector-buckets", { region, max_results: 200 });
  state.vectorBuckets = data.vector_buckets || [];
  const bucketNames = state.vectorBuckets.map(getVectorBucketName).filter(Boolean);
  populateDatalist("vector_bucket_options", bucketNames);

  if (!$("vector_bucket_name").value.trim() && bucketNames.length === 1) {
    $("vector_bucket_name").value = bucketNames[0];
  }
  return bucketNames;
}

async function loadIndexes() {
  const { region, vector_bucket_name } = getConfigParams();
  if (!region || !vector_bucket_name) {
    state.indexes = [];
    populateDatalist("index_options", []);
    return [];
  }

  const data = await apiGet("/api/indexes", {
    region,
    vector_bucket_name,
    max_results: 200,
  });
  state.config = { ...(state.config || {}), ...(data.config || {}) };
  state.indexes = data.indexes || [];
  const indexNames = state.indexes.map(getIndexName).filter(Boolean);
  populateDatalist("index_options", indexNames);

  if (!$("index_name").value.trim() && indexNames.length === 1) {
    $("index_name").value = indexNames[0];
  }
  return indexNames;
}

async function loadIndexDetails(options = {}) {
  const { silent = false } = options;
  if (!hasCompleteConfig()) {
    state.indexDetails = null;
    return null;
  }

  try {
    const data = await apiGet("/api/index", getConfigParams());
    state.indexDetails = data.index || null;
    return state.indexDetails;
  } catch (err) {
    state.indexDetails = null;
    if (!silent) {
      setStatus(err.message, "error");
    }
    return null;
  }
}

async function discoverResources() {
  try {
    setStatus("Discovering vector buckets and indexes...", "info");
    await loadVectorBuckets();
    await loadIndexes();
    renderContext();

    if (hasCompleteConfig()) {
      setStatus("Resource discovery complete.", "success");
    } else {
      setStatus("Resource discovery complete. Choose a bucket and index to continue.", "warn");
    }
  } catch (err) {
    setStatus(err.message, "error");
  }
}

async function loadSelectedVector(options = {}) {
  if (!state.selectedKey) {
    state.selectedVector = null;
    renderSelection();
    return;
  }

  const { silent = false } = options;

  try {
    if (!silent) {
      setStatus(`Loading vector ${state.selectedKey}...`, "info");
    }

    const data = await apiGet("/api/vector", {
      ...getConfigParams(),
      key: state.selectedKey,
      return_metadata: true,
      return_data: $("include_vector_data").checked,
    });
    state.selectedVector = data;
    renderSelection();

    if (!silent) {
      setStatus(`Selected ${state.selectedKey}.`, "success");
    }
  } catch (err) {
    setStatus(err.message, "error");
  }
}

async function loadVectors(reset = true) {
  try {
    if (!hasCompleteConfig()) {
      throw new Error("Choose region, vector bucket, and index before loading vectors.");
    }
    if (!reset && !state.nextToken) {
      setStatus("No additional vector pages are available.", "warn");
      return;
    }

    setStatus(reset ? "Loading vectors..." : "Loading additional vectors...", "info");
    const params = {
      ...getConfigParams(),
      max_results: $("max_results").value,
      return_metadata: true,
      return_data: false,
    };
    if (!reset && state.nextToken) {
      params.next_token = state.nextToken;
    }

    await loadIndexDetails({ silent: true });
    const data = await apiGet("/api/vectors", params);
    state.config = { ...(state.config || {}), ...(data.config || {}) };
    state.envContext = data.env_context || state.envContext;
    state.validationError = null;

    if (reset) {
      state.rows = data.rows || [];
    } else {
      state.rows = state.rows.concat(data.rows || []);
    }
    state.nextToken = data.next_token || null;
    state.loadedConfig = { ...getConfigParams() };

    const previouslySelected = state.selectedKey;
    const selectionStillExists = state.rows.some((row) => row.key === previouslySelected);
    if (!selectionStillExists) {
      state.selectedKey = state.rows[0]?.key || null;
      state.selectedVector = null;
      syncSimilarityKeyFromSelection();
    }

    renderRows();
    renderPageState();
    renderContext();

    let summaryRefreshed = true;
    if (reset) {
      summaryRefreshed = await refreshSummary({ silent: true, raiseOnError: false });
    }

    if (state.selectedKey && (!selectionStillExists || reset || !state.selectedVector)) {
      await loadSelectedVector({ silent: true });
    } else {
      renderSelection();
    }

    if (state.rows.length) {
      const suffix = reset && !summaryRefreshed ? " Summary refresh failed." : "";
      const tone = summaryRefreshed || !reset ? "success" : "warn";
      setStatus(`Loaded ${state.rows.length} rows from ${$("index_name").value.trim()}.${suffix}`, tone);
    } else {
      setStatus("The selected index returned no vectors for this page.", "warn");
    }
  } catch (err) {
    setStatus(err.message, "error");
  }
}

async function querySimilar() {
  const key = similarityInputKey() || state.selectedKey || "";
  if (!key) {
    setStatus("Select a vector row or enter a key first.", "warn");
    return;
  }
  if (!hasCompleteConfig()) {
    setStatus("Choose region, vector bucket, and index before querying similarity.", "warn");
    return;
  }

  try {
    if (!similarityInputKey() && state.selectedKey) {
      $("similarity_key").value = state.selectedKey;
    }
    setStatus(`Querying similar vectors for ${key}...`, "info");
    const data = await apiGet("/api/query-by-key", {
      ...getConfigParams(),
      key,
      top_k: $("top_k").value,
      return_metadata: true,
    });
    state.similarResults = data;
    renderSimilarityResults();
    setStatus("Similarity query complete.", "success");
  } catch (err) {
    setStatus(err.message, "error");
  }
}

async function refreshSummary(options = {}) {
  const { silent = false, raiseOnError = true } = options;

  try {
    if (!hasCompleteConfig()) {
      throw new Error("Choose region, vector bucket, and index before refreshing summary.");
    }

    if (!silent) {
      setStatus("Refreshing sample summary...", "info");
    }
    const data = await apiGet("/api/data-source-summary", {
      ...getConfigParams(),
      sample_size: 200,
    });
    state.summary = data;
    state.envContext = data.env_context || state.envContext;
    state.validationError = null;
    renderSummary();
    renderContext();
    if (!silent) {
      setStatus("Sample summary refreshed.", "success");
    }
    return true;
  } catch (err) {
    if (!silent) {
      setStatus(err.message, "error");
    }
    if (raiseOnError) {
      throw err;
    }
    return false;
  }
}

async function refreshIndexesForBucket() {
  try {
    state.indexDetails = null;
    state.indexes = [];
    populateDatalist("index_options", []);
    $("index_name").value = "";

    if (!$("vector_bucket_name").value.trim()) {
      renderContext();
      return;
    }

    setStatus("Loading indexes for selected vector bucket...", "info");
    await loadIndexes();
    renderContext();
    setStatus("Indexes refreshed.", "success");
  } catch (err) {
    setStatus(err.message, "error");
  }
}

function invalidateLoadedStateIfConfigChanged() {
  const liveConfig = getConfigParams();
  renderContext();

  if (!state.loadedConfig || sameConfig(liveConfig, state.loadedConfig)) {
    return;
  }

  state.rows = [];
  state.nextToken = null;
  state.selectedKey = null;
  state.selectedVector = null;
  state.similarResults = null;
  state.summary = null;
  state.indexDetails = null;
  state.loadedConfig = null;
  $("similarity_key").value = "";

  renderRows();
  renderSelection();
  renderSummary();
  renderPageState();
  setStatus("Config changed. Reload vectors to inspect the new index.", "warn");
}

function bindEvents() {
  $("discover_resources").addEventListener("click", discoverResources);
  $("load_vectors").addEventListener("click", () => loadVectors(true));
  $("load_more").addEventListener("click", () => loadVectors(false));
  $("find_similar").addEventListener("click", querySimilar);
  $("search").addEventListener("input", renderRows);
  $("similarity_key").addEventListener("input", () => {
    state.similarResults = null;
    renderSimilarityResults();
  });
  $("similarity_key").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      querySimilar();
    }
  });
  $("vector_bucket_name").addEventListener("change", refreshIndexesForBucket);
  $("include_vector_data").addEventListener("change", () => {
    if (state.selectedKey) {
      loadSelectedVector();
    }
  });
  ["region", "vector_bucket_name", "index_name"].forEach((id) => {
    $(id).addEventListener("input", invalidateLoadedStateIfConfigChanged);
  });
}

async function init() {
  bindEvents();
  renderPageState();
  renderContext();
  renderSelection();
  renderSummary();

  await loadDefaultConfig();

  try {
    await loadVectorBuckets();
    await loadIndexes();
  } catch (err) {
    setStatus(err.message, "error");
  }

  if (hasCompleteConfig()) {
    await loadVectors(true);
  }
}

init();
