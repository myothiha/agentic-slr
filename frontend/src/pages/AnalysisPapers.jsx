import { Fragment, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { paperMatches } from "../paperSearch.js";
import { ErrorBox } from "./Dashboard.jsx";

const DIM_COLORS = ["#dbeafe", "#dcfce7", "#fef3c7", "#fce7f3", "#ede9fe", "#ffedd5"];

export default function AnalysisPapers() {
  const [params] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const [query, setQuery] = useState("");
  const [pdfSet, setPdfSet] = useState(new Set());
  const [zipBusy, setZipBusy] = useState(false);

  const title = params.get("title") || "Papers";
  let filters = [];
  try {
    filters = JSON.parse(params.get("f") || "[]");
  } catch {
    filters = [];
  }

  useEffect(() => {
    api.getAnalysisPaperDetail(filters).then(setData).catch((e) => setError(e.message));
    document.title = title;
  }, [params]);

  // Which papers have a stored PDF (from the full-text stage), so we only offer
  // a download where a file actually exists.
  useEffect(() => {
    api
      .getFullText()
      .then((ft) => {
        const s = new Set(
          (ft.papers || []).filter((p) => p.has_pdf).map((p) => p.index)
        );
        setPdfSet(s);
      })
      .catch(() => setPdfSet(new Set()));
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (!data) return <p className="text-slate-500">Loading…</p>;

  const dimName = Object.fromEntries(data.dimensions.map((d) => [d.field, d.name]));
  const dimColor = Object.fromEntries(data.dimensions.map((d, i) => [d.field, DIM_COLORS[i % DIM_COLORS.length]]));
  const shown = query.trim() ? data.papers.filter((p) => paperMatches(p, query)) : data.papers;
  const shownWithPdf = shown.filter((p) => pdfSet.has(p.index));

  const downloadPdfs = async () => {
    setZipBusy(true);
    try {
      await api.downloadPdfsZip(shownWithPdf.map((p) => p.index));
    } catch (e) {
      setError(e.message);
    } finally {
      setZipBusy(false);
    }
  };

  const exportCsv = () => {
    const fields = data.dimensions.map((d) => d.field);
    const head = ["index", "title", "year", "database", ...fields.map((f) => dimName[f])];
    const rows = [head];
    data.papers.forEach((p) => {
      rows.push([
        p.index, `"${(p.title || "").replace(/"/g, '""')}"`, p.year, p.database,
        ...fields.map((f) => `"${(p.tags?.[f] || []).join("; ")}"`),
      ]);
    });
    const blob = new Blob([rows.map((r) => r.join(",")).join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "papers.csv";
    a.click();
  };

  return (
    <div>
      <header className="mb-5 flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-slate-900">{title}</h2>
          <p className="text-slate-500 mt-1">
            {shown.length}
            {query.trim() ? ` of ${data.papers.length}` : ""} papers
          </p>
        </div>
        <div className="flex items-center gap-2">
          {shownWithPdf.length > 0 && (
            <button
              onClick={downloadPdfs}
              disabled={zipBusy}
              title="Download the stored PDFs for these papers as a zip, each named by its title"
              className="rounded-md border border-blue-300 bg-white px-3 py-1.5 text-sm text-blue-600 hover:bg-blue-50 disabled:opacity-50"
            >
              {zipBusy ? "Zipping…" : `Download All PDFs (${shownWithPdf.length})`}
            </button>
          )}
          <button onClick={exportCsv} className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50">
            Export CSV
          </button>
        </div>
      </header>

      <div className="mb-3">
        <input
          className="input w-full"
          placeholder="Search papers — title, index, year, abstract, tags…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3 w-8"></th>
              <th className="px-4 py-3">Index</th>
              <th className="px-4 py-3">Title</th>
              <th className="px-4 py-3">Year</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {shown.map((p) => {
              const isOpen = open === p.index;
              return (
                <Fragment key={p.index}>
                  <tr className="cursor-pointer hover:bg-slate-50" onClick={() => setOpen(isOpen ? null : p.index)}>
                    <td className="px-4 py-3 align-top text-slate-400">{isOpen ? "▾" : "▸"}</td>
                    <td className="px-4 py-3 align-top text-slate-500">{p.index}</td>
                    <td className="px-4 py-3 align-top text-slate-800">
                      {p.title}
                      {pdfSet.has(p.index) && (
                        <a
                          href={api.pdfDownloadUrl(p.index)}
                          onClick={(e) => e.stopPropagation()}
                          title="Download the stored PDF, named by paper title"
                          className="ml-2 whitespace-nowrap text-xs text-blue-600 hover:underline"
                        >
                          Download PDF
                        </a>
                      )}
                      <div className="mt-1 flex flex-wrap gap-1">
                        {data.dimensions.map((d) =>
                          (p.tags?.[d.field] || []).map((t) => (
                            <span key={d.field + t} title={data.tag_descriptions?.[d.field]?.[t] || ""}
                              className="rounded px-2 py-0.5 text-xs text-slate-700" style={{ backgroundColor: dimColor[d.field] }}>
                              {t}
                            </span>
                          ))
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 align-top text-slate-500">{p.year}</td>
                  </tr>
                  {isOpen && (
                    <tr className="bg-slate-50/60">
                      <td></td>
                      <td colSpan={3} className="px-4 py-4">
                        <p className="text-xs text-slate-400">{p.database}</p>
                        {data.dimensions.map((d) => {
                          const tags = p.tags?.[d.field] || [];
                          if (tags.length === 0) return null;
                          return (
                            <div key={d.field} className="mt-2">
                              <span className="text-xs font-semibold text-slate-600">{dimName[d.field]}:</span>
                              <ul className="mt-1 space-y-0.5">
                                {tags.map((t) => (
                                  <li key={t} className="text-sm">
                                    <span className="mr-2 rounded px-2 py-0.5 text-xs text-slate-700" style={{ backgroundColor: dimColor[d.field] }}>{t}</span>
                                    {p.evidence?.[d.field]?.[t] && (
                                      <span className="text-slate-500">“{p.evidence[d.field][t]}”</span>
                                    )}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          );
                        })}
                        <div className="mt-3 rounded-md border border-slate-200 bg-white p-3 text-sm leading-relaxed text-slate-700">
                          <p className="mb-1 text-xs font-medium text-slate-400">Abstract</p>
                          {p.abstract || <span className="text-slate-400">(none)</span>}
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
    </div>
  );
}
