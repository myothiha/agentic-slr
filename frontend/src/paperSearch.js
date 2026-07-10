// Shared free-text search over a paper's metadata.
//
// Builds one lowercase "blob" of every value on the paper (recursively, so
// nested raw records and arrays like authors/keywords are included too) and
// requires every whitespace-separated term to appear somewhere in it.

function blob(v) {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.map(blob).join(" ");
  if (typeof v === "object") return Object.values(v).map(blob).join(" ");
  return "";
}

/** True when every term in `query` is found somewhere in the paper's metadata. */
export function paperMatches(paper, query) {
  const terms = (query || "").toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const hay = blob(paper).toLowerCase();
  return terms.every((t) => hay.includes(t));
}

/** Convenience: filter a list of papers by a query. */
export function filterPapers(papers, query) {
  const terms = (query || "").trim();
  if (!terms) return papers;
  return papers.filter((p) => paperMatches(p, query));
}
