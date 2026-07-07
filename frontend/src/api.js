// Thin wrapper around the FastAPI backend. All paths go through the Vite proxy.
const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // Context
  getContext: () => request("/context"),
  updateContext: (payload) =>
    request("/context", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  recomputeHighlights: (useLlm = true) =>
    request(`/context/recompute-highlights?use_llm=${useLlm}`, { method: "POST" }),

  // Databases
  getDatabases: () => request("/databases"),
  addDatabase: (payload) =>
    request("/databases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteDatabase: (id) => request(`/databases/${id}`, { method: "DELETE" }),

  // Ingestion / papers
  ingest: (id, files) => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    return request(`/ingest/${id}`, { method: "POST", body: form });
  },
  getPapers: (id) => request(`/papers/${id}`),
  clearPapers: (id, cascade = false) =>
    request(`/papers/${id}${cascade ? "?cascade=true" : ""}`, { method: "DELETE" }),
  getRawFiles: (id) => request(`/papers/${id}/raw-files`),
  rawFileUrl: (id, filename) =>
    `${BASE}/papers/${id}/raw-files/${encodeURIComponent(filename)}`,

  // Deduplication
  runDeduplication: (priorityOrder = null) =>
    request("/deduplicate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ priority_order: priorityOrder }),
    }),
  getDeduplication: () => request("/deduplication"),
  getDeduplicatedPapers: () => request("/deduplication/papers"),
  restoreDuplicate: (index) =>
    request(`/deduplication/restore/${encodeURIComponent(index)}`, { method: "POST" }),
  removeDuplicate: (index) =>
    request(`/deduplication/remove/${encodeURIComponent(index)}`, { method: "POST" }),

  // Page filter
  getPageFilter: () => request("/page-filter"),
  setPageFilter: (payload) =>
    request("/page-filter", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  setPageOverride: (index, mode) =>
    request(`/page-filter/override/${encodeURIComponent(index)}?mode=${mode}`, { method: "POST" }),

  // Screening
  getScreening: () => request("/screening"),
  suggestScreening: (index) =>
    request(`/screening/suggest/${encodeURIComponent(index)}`, { method: "POST" }),
  suggestBatch: (limit = 25) =>
    request(`/screening/suggest-batch?limit=${limit}`, { method: "POST" }),
  labelScreening: (index, label, comment) =>
    request(`/screening/label/${encodeURIComponent(index)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label, comment }),
    }),
  commentScreening: (index, comment) =>
    request(`/screening/comment/${encodeURIComponent(index)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ comment }),
    }),
  resetScreening: (index) =>
    request(`/screening/reset/${encodeURIComponent(index)}`, { method: "POST" }),

  // Keyword tagging (Phase 5) — multiple independent dimensions
  listTaggingDimensions: () => request("/tagging/dimensions"),
  createTaggingDimension: (payload) =>
    request("/tagging/dimensions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateTaggingDimension: (field, payload) =>
    request(`/tagging/dimensions/${field}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteTaggingDimension: (field) =>
    request(`/tagging/dimensions/${field}`, { method: "DELETE" }),
  getTagging: (field) => request(`/tagging/dimensions/${field}`),
  suggestTagging: (field, payload) =>
    request(`/tagging/dimensions/${field}/suggest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  runTaggingExtraction: (field, payload = {}) =>
    request(`/tagging/dimensions/${field}/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  getTaggingPapers: (field) => request(`/tagging/dimensions/${field}/papers`),
  getTaggingCategories: (field) => request(`/tagging/dimensions/${field}/categories`),
  createTaggingGroup: (field, payload) =>
    request(`/tagging/dimensions/${field}/groups`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateTaggingGroup: (field, id, payload) =>
    request(`/tagging/dimensions/${field}/groups/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteTaggingGroup: (field, id) =>
    request(`/tagging/dimensions/${field}/groups/${id}`, { method: "DELETE" }),

  // Keyword Analysis (Phase 6)
  getAnalysisDimensions: () => request("/analysis/dimensions"),
  computeAnalysis: (config) =>
    request("/analysis/compute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    }),
  getAnalysisPapers: (filters) =>
    request("/analysis/papers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filters }),
    }),
  getAnalysisPaperDetail: (filters) =>
    request("/analysis/papers/detail", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filters }),
    }),
  listAnalysisViews: () => request("/analysis/views"),
  createAnalysisView: (payload) =>
    request("/analysis/views", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updateAnalysisView: (id, payload) =>
    request(`/analysis/views/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteAnalysisView: (id) => request(`/analysis/views/${id}`, { method: "DELETE" }),

  // Backup & Restore
  listBackups: () => request("/backups"),
  createBackup: (label) =>
    request(`/backups${label ? `?label=${encodeURIComponent(label)}` : ""}`, { method: "POST" }),
  restoreBackup: (name) =>
    request(`/backups/restore/${encodeURIComponent(name)}`, { method: "POST" }),
  deleteBackup: (name) => request(`/backups/${encodeURIComponent(name)}`, { method: "DELETE" }),

  // Dashboard
  getDashboard: () => request("/dashboard"),
};
