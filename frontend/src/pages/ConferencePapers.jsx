import { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";
import PaperTable from "../components/PaperTable.jsx";

export default function ConferencePapers() {
  const { id } = useParams();
  const [papers, setPapers] = useState(null);
  const [error, setError] = useState(null);
  const [year, setYear] = useState("all");
  const [absStatus, setAbsStatus] = useState("all"); // all | with | without
  const [source, setSource] = useState("all");
  const navigate = useNavigate();

  useEffect(() => {
    api.getConferencePapers(id).then(setPapers).catch((e) => setError(e.message));
  }, [id]);

  const years = useMemo(
    () => (papers ? [...new Set(papers.map((p) => p.year).filter(Boolean))].sort((a, b) => b - a) : []),
    [papers]
  );
  const sources = useMemo(
    () => (papers ? [...new Set(papers.map((p) => p.abstract_source).filter(Boolean))].sort() : []),
    [papers]
  );

  const filtered = useMemo(() => {
    if (!papers) return [];
    return papers.filter((p) => {
      if (year !== "all" && String(p.year) !== String(year)) return false;
      if (absStatus === "with" && !p.abstract) return false;
      if (absStatus === "without" && p.abstract) return false;
      if (source !== "all" && (p.abstract_source || "—") !== source) return false;
      return true;
    });
  }, [papers, year, absStatus, source]);

  if (error) return <ErrorBox message={error} />;
  if (!papers) return <p className="text-slate-500">Loading…</p>;

  const withAbstract = papers.filter((p) => p.abstract).length;
  const filteredWithAbs = filtered.filter((p) => p.abstract).length;

  const selectCls =
    "rounded-md border border-slate-300 bg-white px-2 py-2 text-sm text-slate-700";

  return (
    <div>
      <button
        onClick={() => navigate("/conferences")}
        className="mb-4 text-sm text-blue-600 hover:underline"
      >
        ← Conference Management
      </button>
      <header className="mb-4">
        <h2 className="text-2xl font-semibold text-slate-900">
          {papers[0]?.venue || id} — {papers.length} papers
        </h2>
        <p className="text-slate-500 mt-1">
          {withAbstract} of {papers.length} have abstracts.
        </p>
      </header>

      <div className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white p-3">
        <label className="flex items-center gap-2 text-sm text-slate-600">
          Year
          <select className={selectCls} value={year} onChange={(e) => setYear(e.target.value)}>
            <option value="all">All</option>
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          Abstract
          <select
            className={selectCls}
            value={absStatus}
            onChange={(e) => setAbsStatus(e.target.value)}
          >
            <option value="all">All</option>
            <option value="with">Has abstract</option>
            <option value="without">Missing (not enriched)</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-600">
          Source
          <select className={selectCls} value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="all">All</option>
            {sources.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <span className="ml-auto text-sm text-slate-500">
          {filtered.length} shown · {filteredWithAbs} with abstract
        </span>
      </div>

      <PaperTable
        papers={filtered}
        searchPlaceholder="Search — title, author, year, keyword, DOI…"
      />
    </div>
  );
}
