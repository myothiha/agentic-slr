import { useEffect, useState } from "react";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";
import PaperTable from "../components/PaperTable.jsx";

export default function ConferenceFilter() {
  const [keywords, setKeywords] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  // Load the last computed filter on mount.
  useEffect(() => {
    api
      .getConferenceFilter()
      .then((r) => {
        setResult(r);
        if (r.keyword_string) setKeywords(r.keyword_string);
      })
      .catch((e) => setError(e.message));
  }, []);

  const run = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(await api.runConferenceFilter(keywords));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const perVenue = result?.per_venue || {};
  const venueRows = Object.entries(perVenue)
    .filter(([, v]) => v.enumerated > 0)
    .sort((a, b) => b[1].relevant - a[1].relevant);

  return (
    <div>
      <header className="mb-4">
        <h2 className="text-2xl font-semibold text-slate-900">Keyword Filtering</h2>
        <p className="text-slate-500 mt-1">
          Define a Boolean keyword string; it’s matched over each paper’s title, abstract, and
          keywords across all fetched venues. (Titles alone already match usefully before abstracts
          are enriched.)
        </p>
      </header>

      <form onSubmit={run} className="mb-5 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-4">
        <label className="flex-1 min-w-[20rem]">
          <span className="text-sm font-medium text-slate-700">Keywords</span>
          <input
            className="input mt-1"
            placeholder='e.g.  ("graph neural network" OR GNN) AND recommendation'
            value={keywords}
            onChange={(e) => setKeywords(e.target.value)}
          />
        </label>
        <button type="submit" disabled={busy} className="btn-primary">
          {busy ? "Filtering…" : "Apply filter"}
        </button>
      </form>

      {error && <ErrorBox message={error} />}

      {result && result.computed_at && (
        <>
          {/* Per-venue relevant-count bar */}
          <div className="mb-4 rounded-lg border border-slate-200 bg-white p-4">
            <div className="mb-3 flex items-baseline justify-between">
              <p className="text-sm font-semibold text-slate-700">
                Relevant papers per venue
              </p>
              <p className="text-sm text-slate-500">
                <span className="font-semibold text-slate-800">{result.total_relevant}</span> of{" "}
                {result.total} total
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {venueRows.map(([id, v]) => (
                <span
                  key={id}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs"
                  title={`${v.relevant} relevant of ${v.enumerated} enumerated`}
                >
                  <span className="font-medium text-slate-700">{v.display}</span>
                  <span className="font-semibold text-blue-700">{v.relevant}</span>
                  <span className="text-slate-400">/ {v.enumerated}</span>
                </span>
              ))}
              {venueRows.length === 0 && (
                <span className="text-sm text-slate-400">No fetched venues yet.</span>
              )}
            </div>
          </div>

          <PaperTable
            papers={result.relevant || []}
            searchPlaceholder="Search within relevant papers…"
          />
        </>
      )}

      {result && !result.computed_at && (
        <p className="text-slate-400">Enter keywords and apply to see relevant papers.</p>
      )}
    </div>
  );
}
