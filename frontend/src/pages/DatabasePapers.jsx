import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";
import PaperTable from "../components/PaperTable.jsx";

export default function DatabasePapers() {
  const { id } = useParams();
  const [papers, setPapers] = useState(null);
  const [db, setDb] = useState(null);
  const [error, setError] = useState(null);
  const [includeEarlyAccess, setIncludeEarlyAccess] = useState(true);

  useEffect(() => {
    Promise.all([api.getPapers(id), api.getDatabases()])
      .then(([ps, dbs]) => {
        setPapers(ps);
        setDb(dbs.find((d) => d.id === id) || { name: id, prefix: "" });
      })
      .catch((e) => setError(e.message));
  }, [id]);

  if (error) return <ErrorBox message={error} />;
  if (!papers) return <p className="text-slate-500">Loading…</p>;

  const rawFiles = db?.raw_files || [];
  const fmtSize = (n) => {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  };

  // Only databases whose exports carry an early-access field (WoS, Scopus) will
  // have any flagged papers; the toggle is hidden otherwise (e.g. IEEE).
  const earlyAccessCount = papers.filter((p) => p.early_access).length;
  const hasEarlyAccess = earlyAccessCount > 0;

  // Papers-per-year, sorted ascending with unknown years last.
  const yearStats = (() => {
    const counts = new Map();
    for (const p of papers) {
      if (!includeEarlyAccess && p.early_access) continue;
      const y = p.year || "Unknown";
      counts.set(y, (counts.get(y) || 0) + 1);
    }
    const known = [...counts.keys()]
      .filter((y) => y !== "Unknown")
      .sort((a, b) => a - b);
    const ordered = counts.has("Unknown") ? [...known, "Unknown"] : known;
    const max = Math.max(1, ...counts.values());
    return ordered.map((y) => ({
      year: y,
      count: counts.get(y),
      pct: (counts.get(y) / max) * 100,
    }));
  })();

  return (
    <div>
      <div className="mb-2">
        <Link to="/databases" className="text-sm text-blue-600 hover:underline">
          ← Database Management
        </Link>
      </div>
      <header className="mb-5">
        <h2 className="text-2xl font-semibold text-slate-900">{db?.name}</h2>
        <p className="text-slate-500 mt-1">Raw ingested papers · {papers.length} total</p>
      </header>

      {rawFiles.length > 0 && (
        <div className="mb-5 rounded-lg border border-slate-200 bg-white p-4">
          <h3 className="text-sm font-medium text-slate-700">
            Original uploaded files
          </h3>
          <p className="mt-0.5 text-xs text-slate-400">
            The most recent upload batch, kept on the server for reference.
          </p>
          <ul className="mt-3 divide-y divide-slate-100">
            {rawFiles.map((f) => (
              <li
                key={f.filename}
                className="flex items-center justify-between py-2 text-sm"
              >
                <span className="truncate text-slate-700">{f.filename}</span>
                <span className="ml-4 flex shrink-0 items-center gap-3">
                  <span className="text-xs text-slate-400">{fmtSize(f.size)}</span>
                  <a
                    href={api.rawFileUrl(id, f.filename)}
                    download
                    className="rounded-md border border-slate-300 bg-white px-3 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Download
                  </a>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {papers.length > 0 && (
        <div className="mb-5 rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-baseline justify-between">
            <h3 className="text-sm font-medium text-slate-700">Papers by year</h3>
            <span className="text-xs text-slate-400">
              {yearStats.length} year{yearStats.length === 1 ? "" : "s"} ·{" "}
              {yearStats.reduce((a, s) => a + s.count, 0)} papers
            </span>
          </div>

          {hasEarlyAccess && (
            <label className="mt-2 flex cursor-pointer items-center gap-2 text-xs text-slate-500">
              <input
                type="checkbox"
                checked={includeEarlyAccess}
                onChange={(e) => setIncludeEarlyAccess(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-slate-300"
              />
              Include early-access papers ({earlyAccessCount})
              <span className="text-slate-400">
                — off matches the source's “final publication year”
              </span>
            </label>
          )}

          <ul className="mt-3 space-y-1.5">
            {yearStats.map((s) => (
              <li key={s.year} className="flex items-center gap-3 text-sm">
                <span className="w-16 shrink-0 text-slate-500">{s.year}</span>
                <span className="relative h-4 flex-1 rounded bg-slate-100">
                  <span
                    className="absolute inset-y-0 left-0 rounded bg-blue-500"
                    style={{ width: `${s.pct}%` }}
                  />
                </span>
                <span className="w-10 shrink-0 text-right font-medium text-slate-700">
                  {s.count}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {papers.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-500">
          No papers ingested for this database yet.{" "}
          <Link to="/ingestion" className="text-blue-600 hover:underline">
            Upload exports →
          </Link>
        </div>
      ) : (
        <PaperTable papers={papers} />
      )}
    </div>
  );
}
