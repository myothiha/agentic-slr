import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";
import { LABELS, ScreeningFilters, matchesScreeningFilters } from "../components/screeningFilters.jsx";

const ROW_TINT = {
  Include: "bg-green-50",
  Exclude: "bg-red-50",
  Maybe: "bg-amber-50",
};
const LABEL_BTN = {
  Include: "bg-green-100 text-green-700 border-green-300",
  Exclude: "bg-red-100 text-red-700 border-red-300",
  Maybe: "bg-amber-100 text-amber-700 border-amber-300",
};
const STATUS_DISPLAY = {
  pending: ["Pending", "bg-slate-100 text-slate-500"],
  llm_labeled: ["AI labeled", "bg-slate-100 text-slate-600"],
  user_confirmed: ["User confirmed", "bg-green-100 text-green-700"],
  user_modified: ["User modified", "bg-blue-100 text-blue-700"],
};

export default function ScreenedReview() {
  const [papers, setPapers] = useState(null);
  const [hasSource, setHasSource] = useState(true);
  const [error, setError] = useState(null);
  const [labelFilter, setLabelFilter] = useState(new Set());
  const [statusFilter, setStatusFilter] = useState(new Set());
  const [perPage, setPerPage] = useState(20);
  const [page, setPage] = useState(1);

  const load = () =>
    api
      .getScreening()
      .then((s) => {
        setHasSource(s.has_source);
        setPapers(s.papers);
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  const filtered = useMemo(() => {
    if (!papers) return [];
    return papers.filter((p) => matchesScreeningFilters(p, labelFilter, statusFilter));
  }, [papers, labelFilter, statusFilter]);

  useEffect(() => {
    setPage(1);
  }, [labelFilter, statusFilter, perPage]);

  if (error) return <ErrorBox message={error} />;
  if (!papers) return <p className="text-slate-500">Loading…</p>;

  const relabel = async (index, label) => {
    try {
      const rec = await api.labelScreening(index, label, undefined);
      setPapers((prev) => prev.map((p) => (p.index === index ? rec : p)));
    } catch (e) {
      alert(e.message);
    }
  };

  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / perPage));
  const current = Math.min(page, totalPages);
  const start = (current - 1) * perPage;
  const pageItems = filtered.slice(start, start + perPage);

  return (
    <div>
      <header className="mb-4 flex items-end justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-slate-900">Screened Papers Review</h2>
          <p className="text-slate-500 mt-1">
            Showing <span className="font-semibold text-slate-700">{filtered.length}</span> of{" "}
            {papers.length} papers
          </p>
        </div>
        <Link
          to="/screening"
          className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          ← Back to screening
        </Link>
      </header>

      {!hasSource && (
        <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
          No deduplicated set yet — run deduplication to populate the screening list.
        </div>
      )}

      {/* Filters: two lists, AND across lists, OR within a list */}
      <div className="mb-4">
        <ScreeningFilters
          labelFilter={labelFilter}
          setLabelFilter={setLabelFilter}
          statusFilter={statusFilter}
          setStatusFilter={setStatusFilter}
          right={
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
          }
        />
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-3">Title</th>
              <th className="px-3 py-3">Author</th>
              <th className="px-3 py-3">Year</th>
              <th className="px-3 py-3">AI label</th>
              <th className="px-3 py-3">Label</th>
              <th className="px-3 py-3">Status</th>
              <th className="px-3 py-3">AI reasoning</th>
              <th className="px-3 py-3">Comment</th>
              <th className="px-3 py-3">Set label</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {pageItems.map((p) => (
              <tr key={p.index} className={p.label ? ROW_TINT[p.label] : ""}>
                <td className="px-3 py-3 align-top">
                  <p className="text-slate-800">{p.title || "(no title)"}</p>
                  <p className="text-xs text-slate-400 font-mono mt-0.5">{p.index}</p>
                </td>
                <td className="px-3 py-3 align-top text-slate-600 max-w-[10rem]">
                  <span className="line-clamp-2">{(p.authors || []).join(", ") || "—"}</span>
                </td>
                <td className="px-3 py-3 align-top text-slate-600">{p.year || "—"}</td>
                <td className="px-3 py-3 align-top">
                  {p.llm_label ? (
                    <span className={`rounded border px-2 py-0.5 text-xs ${LABEL_BTN[p.llm_label]}`}>
                      {p.llm_label}
                    </span>
                  ) : (
                    <span className="text-xs text-slate-400">—</span>
                  )}
                </td>
                <td className="px-3 py-3 align-top">
                  {p.label ? (
                    <span className={`rounded border px-2 py-0.5 text-xs ${LABEL_BTN[p.label]}`}>
                      {p.label}
                    </span>
                  ) : (
                    <span className="text-xs text-slate-400">unlabeled</span>
                  )}
                </td>
                <td className="px-3 py-3 align-top">
                  <StatusCell status={p.status} />
                </td>
                <td className="px-3 py-3 align-top text-slate-600 max-w-xs">
                  <span className="line-clamp-3">{p.llm_reasoning || "—"}</span>
                </td>
                <td className="px-3 py-3 align-top text-slate-600 max-w-[12rem]">
                  <span className="line-clamp-3">{p.user_comment || "—"}</span>
                </td>
                <td className="px-3 py-3 align-top">
                  <div className="flex gap-1">
                    {LABELS.map((lab) => (
                      <button
                        key={lab}
                        onClick={() => relabel(p.index, lab)}
                        className={`rounded border px-2 py-0.5 text-xs ${
                          p.label === lab
                            ? LABEL_BTN[lab]
                            : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
                        }`}
                      >
                        {lab[0]}
                      </button>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
            {total === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-8 text-center text-slate-400">
                  No papers match the current filters.
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

function StatusCell({ status }) {
  const [text, cls] = STATUS_DISPLAY[status] || STATUS_DISPLAY.pending;
  return <span className={`rounded px-2 py-0.5 text-xs whitespace-nowrap ${cls}`}>{text}</span>;
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
