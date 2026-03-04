const state = {
  rows: [],
  nextToken: null,
  selectedKey: null,
};

const $ = (id) => document.getElementById(id);

function setStatus(message, isError = false) {
  const el = $("status");
  el.textContent = message;
  el.style.background = isError ? "#fde8e8" : "#e3f2f7";
  el.style.borderColor = isError ? "#f0b0b0" : "#b8ddeb";
  el.style.color = isError ? "#8a1f1f" : "#05556d";
}

function getConfigParams() {
  return {
    region: $("region").value.trim(),
    vector_bucket_name: $("vector_bucket_name").value.trim(),
    index_name: $("index_name").value.trim(),
  };
}

function buildQuery(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && String(v).trim() !== "") {
      search.set(k, String(v));
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

function toPretty(value) {
  return JSON.stringify(value, null, 2);
}

function renderRows() {
  const tbody = $("vectors_body");
  const filter = $("search").value.trim().toLowerCase();
  tbody.innerHTML = "";

  const filtered = state.rows.filter((row) => {
    if (!filter) return true;
    return [
      row.key,
      row.data_source_id,
      row.modality,
      row.source_uri,
      row.text_preview,
    ]
      .map((v) => (v == null ? "" : String(v).toLowerCase()))
      .some((v) => v.includes(filter));
  });

  filtered.forEach((row) => {
    const tr = document.createElement("tr");
    if (row.key === state.selectedKey) {
      tr.classList.add("selected");
    }
    tr.innerHTML = `
      <td>${row.key ?? ""}</td>
      <td>${row.data_source_id ?? ""}</td>
      <td>${row.modality ?? ""}</td>
      <td>${row.page_number ?? ""}</td>
      <td>${row.related_asset_count ?? 0}</td>
      <td title="${row.source_uri ?? ""}">${(row.source_uri ?? "").slice(0, 80)}</td>
    `;
    tr.addEventListener("click", async () => {
      state.selectedKey = row.key;
      renderRows();
      await loadSelectedVector();
    });
    tbody.appendChild(tr);
  });

  $("metric_rows").textContent = String(filtered.length);
}

function applyConfig(config) {
  $("region").value = config.region || "";
  $("vector_bucket_name").value = config.vector_bucket_name || "";
  $("index_name").value = config.index_name || "";
}

async function loadDefaultConfig() {
  try {
    const data = await apiGet("/api/config");
    applyConfig(data.config);
    setStatus("Loaded config from environment");
  } catch (err) {
    setStatus(err.message, true);
  }
}

async function loadVectors(reset = true) {
  try {
    setStatus("Loading vectors...");
    const params = {
      ...getConfigParams(),
      max_results: $("max_results").value,
      return_metadata: true,
      return_data: false,
    };
    if (!reset && state.nextToken) {
      params.next_token = state.nextToken;
    }

    const data = await apiGet("/api/vectors", params);
    if (reset) {
      state.rows = data.rows || [];
    } else {
      state.rows = state.rows.concat(data.rows || []);
    }
    state.nextToken = data.next_token || null;
    renderRows();
    setStatus(`Loaded ${state.rows.length} rows`);
  } catch (err) {
    setStatus(err.message, true);
  }
}

async function loadSelectedVector() {
  if (!state.selectedKey) {
    return;
  }
  try {
    const data = await apiGet("/api/vector", {
      ...getConfigParams(),
      key: state.selectedKey,
      return_metadata: true,
      return_data: false,
    });

    $("selected_summary").textContent = toPretty(data.summary || {});
    $("selected_payload").textContent = toPretty({
      vector: data.vector,
      parsed_bedrock_metadata: data.parsed_bedrock_metadata,
    });
    setStatus(`Selected ${state.selectedKey}`);
  } catch (err) {
    setStatus(err.message, true);
  }
}

async function querySimilar() {
  if (!state.selectedKey) {
    setStatus("Select a row first", true);
    return;
  }
  try {
    setStatus("Querying similar vectors...");
    const data = await apiGet("/api/query-by-key", {
      ...getConfigParams(),
      key: state.selectedKey,
      top_k: $("top_k").value,
      return_metadata: true,
    });
    $("similar_results").textContent = toPretty(data);
    setStatus("Similarity query complete");
  } catch (err) {
    setStatus(err.message, true);
  }
}

async function refreshSummary() {
  try {
    const data = await apiGet("/api/data-source-summary", {
      ...getConfigParams(),
      sample_size: 200,
    });
    const dsCounts = data.data_source_counts || {};
    const modalityCounts = data.modality_counts || {};

    $("metric_ds").textContent = String(Object.keys(dsCounts).length);
    $("metric_modalities").textContent = String(Object.keys(modalityCounts).length);
    $("data_source_summary").textContent = toPretty(dsCounts);
    $("modality_summary").textContent = toPretty(modalityCounts);
    setStatus("Summary refreshed");
  } catch (err) {
    setStatus(err.message, true);
  }
}

function bindEvents() {
  $("load_vectors").addEventListener("click", () => loadVectors(true));
  $("load_more").addEventListener("click", () => loadVectors(false));
  $("refresh_summary").addEventListener("click", refreshSummary);
  $("find_similar").addEventListener("click", querySimilar);
  $("search").addEventListener("input", renderRows);
}

async function init() {
  bindEvents();
  await loadDefaultConfig();
  await loadVectors(true);
  await refreshSummary();
}

init();
