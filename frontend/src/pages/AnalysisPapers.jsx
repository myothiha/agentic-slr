import { Fragment, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";

const DIM_COLORS = ["#dbeafe", "#dcfce7", "#fef3c7", "#fce7f3", "#ede9fe", "#ffedd5"];

export default function AnalysisPapers() {
  const [params] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);

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

  if (error) return <ErrorBox message={error} />;
  if (!data) return <p className="text-slate-500">Loading…</p>;

  const dimName = Object.fromEntries(data.dimensions.map((d) => [d.field, d.name]));
  const dimColor = Object.fromEntries(data.dimensions.map((d, i) => [d.field, DIM_COLORS[i % DIM_COLORS.length]]));

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
          <p className="text-slate-500 mt-1">{data.papers.length} papers</p>
        </div>
        <button onClick={exportCsv} className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50">
          Export CSV
        </button>
      </header>

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
            {data.papers.map((p) => {
              const isOpen = open === p.index;
              return (
                <Fragment key={p.index}>
                  <tr className="cursor-pointer hover:bg-slate-50" onClick={() => setOpen(isOpen ? null : p.index)}>
                    <td className="px-4 py-3 align-top text-slate-400">{isOpen ? "▾" : "▸"}</td>
                    <td className="px-4 py-3 align-top text-slate-500">{p.index}</td>
                    <td className="px-4 py-3 align-top text-slate-800">
                      {p.title}
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
