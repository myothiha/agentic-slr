import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";

const DEFAULT_URL = "http://localhost:8010";

export default function ConferenceImport() {
  const [url, setUrl] = useState(DEFAULT_URL);
  const [venues, setVenues] = useState(null); // null = not loaded yet
  const [selected, setSelected] = useState(() => new Set());
  const [keyword, setKeyword] = useState("");
  const [keywordEdited, setKeywordEdited] = useState(false);

  // Default the keyword box to the project's Context Configuration keyword
  // string, until the user edits it.
  useEffect(() => {
    api
      .getContext()
      .then((ctx) => {
        if (!keywordEdited && ctx?.keyword_string) setKeyword(ctx.keyword_string);
      })
      .catch(() => {
        /* non-fatal: leave the box empty */
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [loadingVenues, setLoadingVenues] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const navigate = useNavigate();

  const loadVenues = async () => {
    setError(null);
    setResult(null);
    setLoadingVenues(true);
    try {
      const list = await api.listToolkitConferences(url.trim());
      setVenues(list);
      // Preselect venues that actually have fetched papers.
      setSelected(new Set(list.filter((v) => v.paper_count > 0).map((v) => v.id)));
    } catch (e) {
      setVenues(null);
      setError(e.message);
    } finally {
      setLoadingVenues(false);
    }
  };

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const allSelected = venues && venues.length > 0 && selected.size === venues.length;
  const toggleAll = () => {
    if (!venues) return;
    setSelected(allSelected ? new Set() : new Set(venues.map((v) => v.id)));
  };

  const runImport = async () => {
    setError(null);
    setResult(null);
    setImporting(true);
    try {
      const res = await api.importConferencePapers({
        url: url.trim(),
        keywordString: keyword,
        venueIds: [...selected],
      });
      setResult(res);
    } catch (e) {
      setError(e.message);
    } finally {
      setImporting(false);
    }
  };

  const canImport = keyword.trim() && selected.size > 0 && !importing;

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-semibold text-slate-900">Conference Import</h2>
        <p className="text-slate-500 mt-1 max-w-3xl">
          Pull papers from a running{" "}
          <span className="font-medium">conference-toolkit</span> instance: it keyword-filters the
          venues you select and returns the matches, which land in a{" "}
          <span className="font-mono">DBLP Conferences</span> database and flow through the normal
          pipeline (deduplication, screening, …).
        </p>
      </header>

      {error && (
        <div className="mb-4">
          <ErrorBox message={error} />
        </div>
      )}

      {/* Step 1 — toolkit URL */}
      <div className="mb-4 rounded-lg border border-slate-200 bg-white p-4">
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Conference-toolkit URL</span>
          <span className="block text-xs text-slate-400 mb-1">
            The toolkit's backend address (its API is served under <span className="font-mono">/api</span>).
          </span>
          <div className="flex gap-3">
            <input
              className="input flex-1"
              placeholder="http://localhost:8010"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
            <button onClick={loadVenues} disabled={loadingVenues || !url.trim()} className="btn-primary">
              {loadingVenues ? "Loading…" : "Load conferences"}
            </button>
          </div>
        </label>
      </div>

      {/* Step 2 — keyword + venue selection */}
      {venues && (
        <>
          <div className="mb-4 rounded-lg border border-slate-200 bg-white p-4">
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Boolean keyword string</span>
              <span className="block text-xs text-slate-400 mb-1">
                e.g. <span className="font-mono">("graph neural network" OR GNN) AND recommendation</span>
              </span>
              <textarea
                className="input w-full font-mono text-sm"
                rows={2}
                placeholder='("large language model" OR LLM) AND agent'
                value={keyword}
                onChange={(e) => {
                  setKeywordEdited(true);
                  setKeyword(e.target.value);
                }}
              />
            </label>
          </div>

          <div className="mb-4 overflow-hidden rounded-lg border border-slate-200 bg-white">
            <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-4 py-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Conferences ({selected.size}/{venues.length} selected)
              </span>
              <button onClick={toggleAll} className="text-xs text-blue-600 hover:underline">
                {allSelected ? "Clear all" : "Select all"}
              </button>
            </div>
            <div className="max-h-80 overflow-y-auto divide-y divide-slate-100">
              {venues.map((v) => (
                <label
                  key={v.id}
                  className="flex cursor-pointer items-center gap-3 px-4 py-2 text-sm hover:bg-slate-50"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(v.id)}
                    onChange={() => toggle(v.id)}
                  />
                  <span className="font-medium text-slate-800">{v.display}</span>
                  {v.rank && (
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-500">
                      {v.rank}
                    </span>
                  )}
                  <span className="ml-auto text-xs text-slate-500">
                    {v.paper_count} papers
                    {v.with_abstract != null ? ` · ${v.with_abstract} w/ abstract` : ""}
                  </span>
                </label>
              ))}
              {venues.length === 0 && (
                <p className="px-4 py-6 text-center text-sm text-slate-400">
                  The toolkit has no venues registered.
                </p>
              )}
            </div>
          </div>

          <div className="mb-6 flex items-center gap-3">
            <button onClick={runImport} disabled={!canImport} className="btn-primary">
              {importing ? "Importing…" : "Filter & import matching papers"}
            </button>
            {!keyword.trim() && (
              <span className="text-xs text-slate-400">Enter a keyword string to enable import.</span>
            )}
            {keyword.trim() && selected.size === 0 && (
              <span className="text-xs text-slate-400">Select at least one conference.</span>
            )}
          </div>
        </>
      )}

      {/* Result */}
      {result && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4">
          <p className="text-sm text-emerald-900">
            Matched <span className="font-semibold">{result.matched}</span> papers ·{" "}
            added <span className="font-semibold">{result.added}</span> new to{" "}
            <span className="font-mono">{result.database}</span>
            {result.skipped ? (
              <>
                {" "}· skipped <span className="font-semibold">{result.skipped}</span> duplicate
                {result.skipped === 1 ? "" : "s"}
              </>
            ) : null}
            {result.index_range ? (
              <>
                {" "}
                · <span className="font-mono">{result.index_range}</span>
              </>
            ) : null}
          </p>

          {result.per_venue && Object.keys(result.per_venue).length > 0 && (
            <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-emerald-900 sm:grid-cols-3">
              {Object.entries(result.per_venue).map(([id, v]) => (
                <div key={id} className="flex justify-between">
                  <span>{v.display}</span>
                  <span className="font-semibold">{v.matched}</span>
                </div>
              ))}
            </div>
          )}

          <div className="mt-4 flex gap-4">
            <button
              onClick={() => navigate(`/databases/${result.database_id}`)}
              className="text-sm text-blue-700 hover:underline"
            >
              View imported papers →
            </button>
            <button
              onClick={() => navigate("/deduplication")}
              className="text-sm text-blue-700 hover:underline"
            >
              Go to Deduplication →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
