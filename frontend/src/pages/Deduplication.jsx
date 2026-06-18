import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";

export default function Deduplication() {
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [running, setRunning] = useState(false);
  const [busyIndex, setBusyIndex] = useState(null);

  const load = () => api.getDeduplication().then(setReport).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (!report) return <p className="text-slate-500">Loading…</p>;

  const run = async () => {
    setRunning(true);
    try {
      const r = await api.runDeduplication();
      setReport(r);
    } catch (e) {
      alert(e.message);
    } finally {
      setRunning(false);
    }
  };

  const restore = async (index) => {
    setBusyIndex(index);
    try {
      setReport(await api.restoreDuplicate(index));
    } catch (e) {
      alert(e.message);
    } finally {
      setBusyIndex(null);
    }
  };

  return (
    <div>
      <header className="mb-6 flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-slate-900">Deduplication</h2>
          <p className="text-slate-500 mt-1">
            Removes duplicates across databases by priority (DOI, then title+year).
          </p>
        </div>
        <div className="flex items-center gap-3">
          {report.has_run && (
            <Link
              to="/deduplication/papers"
              className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              View deduplicated list
            </Link>
          )}
          <button onClick={run} disabled={running} className="btn-primary">
            {running ? "Running…" : report.has_run ? "Re-run deduplication" : "Run deduplication"}
          </button>
        </div>
      </header>

      {!report.has_run ? (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-500">
          No deduplication run yet. Click “Run deduplication” to process the ingested papers.
        </div>
      ) : (
        <>
          <Summary report={report} />
          <Matrix matrix={report.matrix} />
          <DuplicatesTable
            duplicates={report.duplicates}
            restored={report.restored}
            originals={report.originals || {}}
            busyIndex={busyIndex}
            onRestore={restore}
          />
        </>
      )}
    </div>
  );
}

function Summary({ report }) {
  const s = report.summary || {};
  const runAt = report.run_at ? new Date(report.run_at).toLocaleString() : "—";
  return (
    <section className="mb-6">
      <div className="grid grid-cols-4 gap-4">
        <Stat label="Input papers" value={s.total_input} />
        <Stat label="Unique (kept)" value={report.kept_count} accent="text-green-600" />
        <Stat label="Duplicates removed" value={s.total_duplicates} accent="text-red-600" />
        <Stat label="Restored" value={(report.restored || []).length} accent="text-amber-600" />
      </div>
      <p className="text-xs text-slate-400 mt-2">Last run: {runAt}</p>
    </section>
  );
}

function Stat({ label, value, accent = "text-slate-900" }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className={`text-3xl font-bold mt-1 ${accent}`}>{value ?? 0}</p>
    </div>
  );
}

function Matrix({ matrix }) {
  if (!matrix || !matrix.rows) return null;
  const order = matrix.priority_order || [];
  return (
    <section className="mb-8">
      <h3 className="text-sm font-semibold text-slate-700 mb-2">Traceability matrix</h3>
      <p className="text-xs text-slate-400 mb-3">
        Each cell shows how many papers in the row database were duplicates of an
        original from the column database (diagonal = duplicates within the same database).
      </p>
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">Database</th>
              <th className="px-4 py-3 text-right">Total</th>
              {order.map((id) => (
                <th key={id} className="px-3 py-3 text-right">
                  vs {matrix.names[id]}
                </th>
              ))}
              <th className="px-4 py-3 text-right">Dups</th>
              <th className="px-4 py-3 text-right">Unique</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {matrix.rows.map((row) => (
              <tr key={row.database_id}>
                <td className="px-4 py-3 font-medium text-slate-800">{row.database}</td>
                <td className="px-4 py-3 text-right text-slate-600">{row.total}</td>
                {order.map((id) => {
                  const v = row.against[id] || 0;
                  const diag = id === row.database_id;
                  return (
                    <td
                      key={id}
                      className={`px-3 py-3 text-right ${
                        v ? (diag ? "text-amber-600 font-medium" : "text-red-600 font-medium") : "text-slate-300"
                      }`}
                    >
                      {v || "·"}
                    </td>
                  );
                })}
                <td className="px-4 py-3 text-right font-semibold text-red-600">
                  {row.duplicates}
                </td>
                <td className="px-4 py-3 text-right font-semibold text-green-600">
                  {row.unique}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function DuplicatesTable({ duplicates, restored, originals, busyIndex, onRestore }) {
  const [open, setOpen] = useState(null);
  const [perPage, setPerPage] = useState(20);
  const [page, setPage] = useState(1);
  const all = [...(duplicates || []), ...(restored || [])];

  const total = all.length;
  const totalPages = Math.max(1, Math.ceil(total / perPage));
  const current = Math.min(page, totalPages);
  const start = (current - 1) * perPage;
  const pageItems = all.slice(start, start + perPage);

  if (all.length === 0) {
    return (
      <section>
        <h3 className="text-sm font-semibold text-slate-700 mb-2">Removed duplicates</h3>
        <div className="rounded-lg border border-slate-200 bg-white p-6 text-center text-slate-500">
          No duplicates were found. 🎉
        </div>
      </section>
    );
  }
  return (
    <section>
      <h3 className="text-sm font-semibold text-slate-700 mb-2">
        Removed duplicates ({duplicates.length})
        {restored.length > 0 && (
          <span className="ml-2 text-amber-600 font-normal">· {restored.length} restored</span>
        )}
      </h3>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-400">Click a row to compare the two papers side by side.</p>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          Per page
          <select
            className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
            value={perPage}
            onChange={(e) => {
              setPerPage(Number(e.target.value));
              setPage(1);
            }}
          >
            {[10, 20, 50, 100].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm table-fixed">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left w-[42%]">Removed paper</th>
              <th className="px-4 py-3 text-left w-[42%]">Matched original</th>
              <th className="px-4 py-3 text-left w-[8%]">Match</th>
              <th className="px-4 py-3 w-[8%]"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {pageItems.map((p) => {
              const isRestored = p.dedup_status === "restored";
              const original = originals[p.duplicate_of?.index];
              const isOpen = open === p.index;
              return (
                <Fragment key={p.index}>
                  <tr
                    onClick={() => setOpen(isOpen ? null : p.index)}
                    className={`cursor-pointer align-top ${
                      isRestored ? "bg-amber-50" : "hover:bg-slate-50"
                    }`}
                  >
                    <td className="px-4 py-3">
                      <p className="text-slate-800">{p.title || "(no title)"}</p>
                      <p className="mt-1 text-xs text-slate-400">
                        <span className="font-mono">{p.index}</span> · {p.database}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <p className="text-slate-800">
                        {original?.title || p.duplicate_of?.title || "(no title)"}
                      </p>
                      <p className="mt-1 text-xs text-slate-400">
                        <span className="font-mono">{p.duplicate_of?.index}</span> ·{" "}
                        {p.duplicate_of?.database}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded px-2 py-0.5 text-xs ${
                          p.duplicate_of?.match_type === "doi"
                            ? "bg-blue-100 text-blue-700"
                            : "bg-slate-100 text-slate-600"
                        }`}
                      >
                        {p.duplicate_of?.match_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {isRestored ? (
                        <span className="text-xs text-amber-600 whitespace-nowrap">restored ✓</span>
                      ) : (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onRestore(p.index);
                          }}
                          disabled={busyIndex === p.index}
                          className="text-xs text-blue-600 hover:underline disabled:opacity-50"
                        >
                          {busyIndex === p.index ? "…" : "Restore"}
                        </button>
                      )}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="bg-slate-50">
                      <td colSpan={4} className="px-4 py-4">
                        <div className="grid grid-cols-2 gap-4">
                          <PaperDetail title="Removed paper" p={p} tone="red" />
                          <PaperDetail title="Matched original" p={original} tone="green" />
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm">
        <p className="text-slate-500">
          Showing {start + 1}–{start + pageItems.length} of {total}
        </p>
        <div className="flex items-center gap-1">
          <PageBtn disabled={current <= 1} onClick={() => setPage(1)}>
            « First
          </PageBtn>
          <PageBtn disabled={current <= 1} onClick={() => setPage(current - 1)}>
            ‹ Prev
          </PageBtn>
          <span className="px-3 text-slate-600">
            Page {current} of {totalPages}
          </span>
          <PageBtn disabled={current >= totalPages} onClick={() => setPage(current + 1)}>
            Next ›
          </PageBtn>
          <PageBtn disabled={current >= totalPages} onClick={() => setPage(totalPages)}>
            Last »
          </PageBtn>
        </div>
      </div>
    </section>
  );
}

function PageBtn({ disabled, onClick, children }) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}

function PaperDetail({ title, p, tone }) {
  const ring = tone === "red" ? "border-red-200" : "border-green-200";
  const head = tone === "red" ? "text-red-600" : "text-green-600";
  if (!p) {
    return (
      <div className={`rounded-md border ${ring} bg-white p-3`}>
        <p className={`text-xs font-semibold uppercase ${head} mb-2`}>{title}</p>
        <p className="text-sm text-slate-400">Original record unavailable.</p>
      </div>
    );
  }
  return (
    <div className={`rounded-md border ${ring} bg-white p-3`}>
      <p className={`text-xs font-semibold uppercase ${head} mb-2`}>{title}</p>
      <Detail label="Index" value={p.index} mono />
      <Detail label="Database" value={p.database} />
      <Detail label="Year" value={p.year} />
      <Detail label="Authors" value={(p.authors || []).join(", ")} />
      <Detail label="DOI" value={p.doi} mono />
      {p.url && <Detail label="URL" value={p.url} />}
      <div className="mt-2">
        <p className="text-[11px] font-semibold uppercase text-slate-500">Abstract</p>
        <p className="text-sm text-slate-700 whitespace-pre-wrap">
          {p.abstract || "(no abstract)"}
        </p>
      </div>
      {p.keywords && p.keywords.length > 0 && (
        <div className="mt-2">
          <p className="text-[11px] font-semibold uppercase text-slate-500 mb-1">Keywords</p>
          <div className="flex flex-wrap gap-1">
            {p.keywords.map((k, i) => (
              <span key={i} className="rounded bg-slate-200 px-2 py-0.5 text-xs text-slate-700">
                {k}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Detail({ label, value, mono }) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <p className="text-sm text-slate-700 mb-0.5">
      <span className="text-[11px] font-semibold uppercase text-slate-500">{label}:</span>{" "}
      <span className={mono ? "font-mono text-xs" : ""}>{value}</span>
    </p>
  );
}
