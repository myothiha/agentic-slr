import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";

const STATUS_STYLE = {
  included: "bg-green-100 text-green-700",
  excluded: "bg-red-100 text-red-700",
  unknown: "bg-amber-100 text-amber-700",
};

export default function PageFilter() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [min, setMin] = useState("");
  const [max, setMax] = useState("");
  const [excludeUnknown, setExcludeUnknown] = useState(false);
  const [applying, setApplying] = useState(false);
  const [statusView, setStatusView] = useState("all");
  const [perPage, setPerPage] = useState(20);
  const [page, setPage] = useState(1);

  const apply = (payload) => {
    setData(payload);
    setMin(payload.config?.min_pages ?? "");
    setMax(payload.config?.max_pages ?? "");
    setExcludeUnknown(!!payload.config?.exclude_unknown);
  };

  useEffect(() => {
    api.getPageFilter().then(apply).catch((e) => setError(e.message));
  }, []);

  const papers = data?.papers || [];
  const filtered = useMemo(
    () => (statusView === "all" ? papers : papers.filter((p) => p.status === statusView)),
    [papers, statusView]
  );

  useEffect(() => {
    setPage(1);
  }, [statusView, perPage]);

  if (error) return <ErrorBox message={error} />;
  if (!data) return <p className="text-slate-500">Loading…</p>;

  if (!data.has_source) {
    return (
      <div>
        <h2 className="text-2xl font-semibold text-slate-900 mb-4">Page Filter</h2>
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-500">
          No deduplicated papers yet. Run{" "}
          <Link to="/deduplication" className="text-blue-600 hover:underline">
            deduplication
          </Link>{" "}
          first.
        </div>
      </div>
    );
  }

  const applyFilter = async () => {
    setApplying(true);
    try {
      const payload = await api.setPageFilter({
        min_pages: min === "" ? null : Number(min),
        max_pages: max === "" ? null : Number(max),
        exclude_unknown: excludeUnknown,
      });
      apply(payload);
    } catch (e) {
      alert(e.message);
    } finally {
      setApplying(false);
    }
  };

  const override = async (index, mode) => {
    try {
      apply(await api.setPageOverride(index, mode));
    } catch (e) {
      alert(e.message);
    }
  };

  const c = data.counts || {};
  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / perPage));
  const current = Math.min(page, totalPages);
  const start = (current - 1) * perPage;
  const pageItems = filtered.slice(start, start + perPage);

  return (
    <div>
      <header className="mb-4">
        <h2 className="text-2xl font-semibold text-slate-900">Page Filter</h2>
        <p className="text-slate-500 mt-1">
          Exclude papers outside a page-count range before screening. Included &amp; unknown
          papers proceed to{" "}
          <Link to="/screening" className="text-blue-600 hover:underline">
            screening
          </Link>
          .
        </p>
      </header>

      {/* Range controls */}
      <div className="mb-5 flex flex-wrap items-end gap-4 rounded-lg border border-slate-200 bg-white p-4">
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Min pages</span>
          <input
            type="number"
            min="0"
            className="input mt-1 w-28"
            placeholder="e.g. 8"
            value={min}
            onChange={(e) => setMin(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Max pages</span>
          <input
            type="number"
            min="0"
            className="input mt-1 w-28"
            placeholder="none"
            value={max}
            onChange={(e) => setMax(e.target.value)}
          />
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={excludeUnknown}
            onChange={(e) => setExcludeUnknown(e.target.checked)}
          />
          Exclude papers with unknown page count
        </label>
        <button onClick={applyFilter} disabled={applying} className="btn-primary ml-auto">
          {applying ? "Applying…" : "Apply filter"}
        </button>
      </div>

      {/* Summary */}
      <div className="mb-3 grid grid-cols-4 gap-4">
        <Stat label="Total" value={c.total} onClick={() => setStatusView("all")} active={statusView === "all"} />
        <Stat label="Included" value={c.included} tone="text-green-600" onClick={() => setStatusView("included")} active={statusView === "included"} />
        <Stat label="Excluded" value={c.excluded} tone="text-red-600" onClick={() => setStatusView("excluded")} active={statusView === "excluded"} />
        <Stat label="Unknown" value={c.unknown} tone="text-amber-600" onClick={() => setStatusView("unknown")} active={statusView === "unknown"} />
      </div>

      <div className="mb-5 rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
        <strong>{(c.included || 0) + (c.unknown || 0)}</strong> paper(s) will proceed to screening
        {" "}— {c.included || 0} included
        {(c.unknown || 0) > 0 && (
          <> + {c.unknown} unknown (kept because their page count couldn’t be read; tick
          “Exclude papers with unknown page count” above to drop them)</>
        )}
        .
      </div>

      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm text-slate-500">
          {statusView === "all" ? "All papers" : `Status: ${statusView}`} · {total} shown
        </p>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          Per page
          <select
            className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
            value={perPage}
            onChange={(e) => setPerPage(Number(e.target.value))}
          >
            {[10, 20, 50, 100].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-3">Index</th>
              <th className="px-3 py-3">Title</th>
              <th className="px-3 py-3">Year</th>
              <th className="px-3 py-3">Pages</th>
              <th className="px-3 py-3">Status</th>
              <th className="px-3 py-3">Reason</th>
              <th className="px-3 py-3">Override</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {pageItems.map((p) => (
              <tr key={p.index} className="align-top">
                <td className="px-3 py-3 font-mono text-xs text-slate-500 whitespace-nowrap">
                  {p.index}
                </td>
                <td className="px-3 py-3 text-slate-800">{p.title || "(no title)"}</td>
                <td className="px-3 py-3 text-slate-600">{p.year || "—"}</td>
                <td className="px-3 py-3 text-slate-700 whitespace-nowrap">
                  {p.page_count != null ? (
                    <>
                      <span className="font-medium">{p.page_count}</span>
                      {p.page_start != null && p.page_end != null && (
                        <span className="text-xs text-slate-400"> ({p.page_start}–{p.page_end})</span>
                      )}
                    </>
                  ) : (
                    <span className="text-slate-400">—</span>
                  )}
                </td>
                <td className="px-3 py-3">
                  <span className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLE[p.status]}`}>
                    {p.status}
                  </span>
                </td>
                <td className="px-3 py-3 text-xs text-slate-500">
                  {p.reason}
                  {p.override && <span className="ml-1 text-blue-600">(manual)</span>}
                </td>
                <td className="px-3 py-3">
                  <div className="flex gap-1">
                    {["auto", "include", "exclude"].map((m) => (
                      <button
                        key={m}
                        onClick={() => override(p.index, m)}
                        className={`rounded border px-2 py-0.5 text-xs ${
                          (m === "auto" && !p.override) || p.override === m
                            ? "border-blue-400 bg-blue-50 text-blue-700"
                            : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
                        }`}
                      >
                        {m}
                      </button>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
            {total === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-slate-400">
                  No papers in this view.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {total > 0 && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm">
          <p className="text-slate-500">
            Showing {start + 1}–{start + pageItems.length} of {total}
          </p>
          <div className="flex items-center gap-1">
            <PageBtn disabled={current <= 1} onClick={() => setPage(1)}>« First</PageBtn>
            <PageBtn disabled={current <= 1} onClick={() => setPage(current - 1)}>‹ Prev</PageBtn>
            <span className="px-3 text-slate-600">Page {current} of {totalPages}</span>
            <PageBtn disabled={current >= totalPages} onClick={() => setPage(current + 1)}>Next ›</PageBtn>
            <PageBtn disabled={current >= totalPages} onClick={() => setPage(totalPages)}>Last »</PageBtn>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, tone = "text-slate-900", onClick, active }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-lg border p-4 text-left ${
        active ? "border-blue-400 ring-1 ring-blue-300" : "border-slate-200"
      } bg-white hover:bg-slate-50`}
    >
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className={`text-3xl font-bold mt-1 ${tone}`}>{value ?? 0}</p>
    </button>
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
