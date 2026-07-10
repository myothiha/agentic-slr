import { Fragment, useEffect, useMemo, useState } from "react";
import { paperMatches } from "../paperSearch.js";

const PER_PAGE_OPTIONS = [10, 20, 50, 100];

/**
 * Reusable, paginated, searchable paper list with expandable detail rows.
 * Used by both the raw per-database list and the deduplicated list.
 */
export default function PaperTable({ papers, searchPlaceholder }) {
  const [query, setQuery] = useState("");
  const [perPage, setPerPage] = useState(20);
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState(null);

  const filtered = useMemo(
    () => (query.trim() ? papers.filter((p) => paperMatches(p, query)) : papers),
    [papers, query]
  );

  // Reset to page 1 whenever the result set or page size changes.
  useEffect(() => {
    setPage(1);
  }, [query, perPage, papers]);

  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / perPage));
  const current = Math.min(page, totalPages);
  const start = (current - 1) * perPage;
  const pageItems = filtered.slice(start, start + perPage);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <input
          className="input flex-1 min-w-[16rem]"
          placeholder={
            searchPlaceholder ||
            "Search any column — title, index, DOI, author, year, keyword…"
          }
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label className="flex items-center gap-2 text-sm text-slate-600">
          Per page
          <select
            className="rounded-md border border-slate-300 bg-white px-2 py-2 text-sm"
            value={perPage}
            onChange={(e) => setPerPage(Number(e.target.value))}
          >
            {PER_PAGE_OPTIONS.map((n) => (
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
              <th className="px-3 py-3">Authors</th>
              <th className="px-3 py-3">Year</th>
              <th className="px-3 py-3">DOI</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {pageItems.map((p) => (
              <PaperRow
                key={p.index}
                p={p}
                open={expanded === p.index}
                onToggle={() => setExpanded(expanded === p.index ? null : p.index)}
              />
            ))}
            {total === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-8 text-center text-slate-400">
                  {query ? `No papers match “${query}”.` : "No papers."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <Pagination
        total={total}
        start={start}
        count={pageItems.length}
        page={current}
        totalPages={totalPages}
        onPage={setPage}
      />
    </div>
  );
}

function Pagination({ total, start, count, page, totalPages, onPage }) {
  if (total === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm">
      <p className="text-slate-500">
        Showing {start + 1}–{start + count} of {total}
      </p>
      <div className="flex items-center gap-1">
        <PageBtn disabled={page <= 1} onClick={() => onPage(1)}>
          « First
        </PageBtn>
        <PageBtn disabled={page <= 1} onClick={() => onPage(page - 1)}>
          ‹ Prev
        </PageBtn>
        <span className="px-3 text-slate-600">
          Page {page} of {totalPages}
        </span>
        <PageBtn disabled={page >= totalPages} onClick={() => onPage(page + 1)}>
          Next ›
        </PageBtn>
        <PageBtn disabled={page >= totalPages} onClick={() => onPage(totalPages)}>
          Last »
        </PageBtn>
      </div>
    </div>
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

function PaperRow({ p, open, onToggle }) {
  return (
    <>
      <tr className="cursor-pointer hover:bg-slate-50 align-top" onClick={onToggle}>
        <td className="px-3 py-3 font-mono text-xs text-slate-500 whitespace-nowrap">
          {p.index}
        </td>
        <td className="px-3 py-3 text-slate-800">{p.title || "(no title)"}</td>
        <td className="px-3 py-3 text-slate-600 max-w-[12rem]">
          <span className="line-clamp-2">{(p.authors || []).join(", ")}</span>
        </td>
        <td className="px-3 py-3 text-slate-600">{p.year || "—"}</td>
        <td className="px-3 py-3 text-slate-500 text-xs">{p.doi || "—"}</td>
      </tr>
      {open && (
        <tr className="bg-slate-50">
          <td colSpan={5} className="px-4 py-4">
            <div className="grid grid-cols-3 gap-4 text-sm">
              <div className="col-span-2">
                <p className="text-xs font-semibold uppercase text-slate-500 mb-1">Abstract</p>
                <p className="text-slate-700 whitespace-pre-wrap">
                  {p.abstract || "(no abstract)"}
                </p>
              </div>
              <div className="space-y-3">
                <div>
                  <p className="text-xs font-semibold uppercase text-slate-500 mb-1">Keywords</p>
                  {p.keywords && p.keywords.length ? (
                    <div className="flex flex-wrap gap-1">
                      {p.keywords.map((k, i) => (
                        <span
                          key={i}
                          className="rounded bg-slate-200 px-2 py-0.5 text-xs text-slate-700"
                        >
                          {k}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="text-slate-400 text-xs">—</p>
                  )}
                </div>
                {p.venue && (
                  <div>
                    <p className="text-xs font-semibold uppercase text-slate-500 mb-1">Venue</p>
                    <p className="text-slate-700">{p.venue}</p>
                  </div>
                )}
                {p.url && (
                  <div>
                    <p className="text-xs font-semibold uppercase text-slate-500 mb-1">URL</p>
                    <a
                      href={p.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-blue-600 hover:underline text-xs break-all"
                    >
                      {p.url}
                    </a>
                  </div>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
