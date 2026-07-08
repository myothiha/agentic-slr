import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bar, BarChart, Cell, LabelList, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "../api.js";
import { exportAllChartsPng, exportChartPng } from "../chartExport.js";
import { ErrorBox } from "./Dashboard.jsx";

// Small reusable "download PNG" button.
function PngButton({ onClick, className = "" }) {
  return (
    <button
      onClick={onClick}
      title="Download this chart as a high-resolution PNG"
      className={`inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 ${className}`}
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="7 10 12 15 17 10" />
        <line x1="12" y1="15" x2="12" y2="3" />
      </svg>
      PNG
    </button>
  );
}

const COLORS = [
  "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899",
  "#14b8a6", "#f97316", "#6366f1", "#84cc16", "#06b6d4", "#a855f7",
];

const YEAR = "year";

export default function KeywordAnalysis() {
  const [dims, setDims] = useState(null);
  const [views, setViews] = useState([]);
  const [error, setError] = useState(null);

  // config
  const [topField, setTopField] = useState("");
  const [topUnit, setTopUnit] = useState("category");
  const [topValues, setTopValues] = useState([]);
  const [brkField, setBrkField] = useState("");
  const [brkUnit, setBrkUnit] = useState("category");
  const [chart, setChart] = useState("bar");
  const [normalize, setNormalize] = useState(false);
  const [minCount, setMinCount] = useState(1);

  const [result, setResult] = useState(null);
  const [activeView, setActiveView] = useState(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const PAGE = 20;

  const overviewRef = useRef(null);
  const chartsRef = useRef(null);
  const panelRefs = useRef({});

  const unitOf = (f, u) => (f === YEAR ? "year" : u);

  // Open the detailed paper list (abstract + tags) in a new browser tab.
  const openPapers = (title, filters) => {
    const qs = `title=${encodeURIComponent(title)}&f=${encodeURIComponent(JSON.stringify(filters))}`;
    window.open(`/analysis/papers?${qs}`, "_blank");
  };

  useEffect(() => {
    Promise.all([api.getAnalysisDimensions(), api.listAnalysisViews()])
      .then(([d, v]) => {
        setDims(d.dimensions);
        setViews(v);
      })
      .catch((e) => setError(e.message));
  }, []);

  const dimOf = (f) => dims?.find((d) => d.field === f);
  const isYear = (f) => f === YEAR;

  // value options for the top-level multiselect
  const topOptions = useMemo(() => {
    const d = dimOf(topField);
    if (!d) return [];
    if (d.type === "year") return d.values.map((v) => ({ label: v, count: null }));
    return topUnit === "tag"
      ? d.tags.map((t) => ({ label: t.tag, count: t.count }))
      : d.categories.map((c) => ({ label: c.name, count: c.count }));
  }, [dims, topField, topUnit]);

  // recompute whenever config is complete
  useEffect(() => {
    if (!topField || !brkField) {
      setResult(null);
      return;
    }
    const config = {
      top: { dimension: topField, unit: isYear(topField) ? "year" : topUnit, values: topValues },
      breakdown: { dimension: brkField, unit: isYear(brkField) ? "year" : brkUnit },
      options: { normalize, min_count: Number(minCount) || 1 },
    };
    api.computeAnalysis(config).then(setResult).catch((e) => setError(e.message));
  }, [topField, topUnit, JSON.stringify(topValues), brkField, brkUnit, normalize, minCount]);

  if (error) return <ErrorBox message={error} />;
  if (!dims) return <p className="text-slate-500">Loading…</p>;

  const toggleTopValue = (label) =>
    setTopValues((v) => (v.includes(label) ? v.filter((x) => x !== label) : [...v, label]));

  const currentConfig = () => ({
    top: { dimension: topField, unit: topUnit, values: topValues },
    breakdown: { dimension: brkField, unit: brkUnit },
    chart, options: { normalize, min_count: Number(minCount) || 1 },
  });

  const applyView = (view) => {
    const c = view.config || {};
    setActiveView(view.id);
    setTopField(c.top?.dimension || "");
    setTopUnit(c.top?.unit || "category");
    setTopValues(c.top?.values || []);
    setBrkField(c.breakdown?.dimension || "");
    setBrkUnit(c.breakdown?.unit || "category");
    setChart(c.chart || "bar");
    setNormalize(!!c.options?.normalize);
    setMinCount(c.options?.min_count || 1);
  };

  const saveNew = async () => {
    const name = prompt("Name this view");
    if (!name || !name.trim()) return;
    try {
      const v = await api.createAnalysisView({ name: name.trim(), config: currentConfig() });
      setViews(await api.listAnalysisViews());
      setActiveView(v.id);
    } catch (e) {
      alert(e.message);
    }
  };
  const saveExisting = async () => {
    try {
      await api.updateAnalysisView(activeView, { config: currentConfig() });
      setViews(await api.listAnalysisViews());
    } catch (e) {
      alert(e.message);
    }
  };
  const deleteView = async (id) => {
    if (!confirm("Delete this view?")) return;
    try {
      await api.deleteAnalysisView(id);
      setViews(await api.listAnalysisViews());
      if (activeView === id) setActiveView(null);
    } catch (e) {
      alert(e.message);
    }
  };

  const filteredPapers = (result?.matching_papers || []).filter(
    (p) => !search.trim() || (p.title || "").toLowerCase().includes(search.toLowerCase())
  );
  const pagePapers = filteredPapers.slice(page * PAGE, page * PAGE + PAGE);
  const pages = Math.ceil(filteredPapers.length / PAGE);

  const exportCsv = () => {
    const rows = [["index", "title", "year", "database", "top", "breakdown"]];
    filteredPapers.forEach((p) =>
      rows.push([p.index, `"${(p.title || "").replace(/"/g, '""')}"`, p.year, p.database,
        `"${p.top_values.join("; ")}"`, `"${p.breakdown_values.join("; ")}"`]));
    const blob = new Blob([rows.map((r) => r.join(",")).join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "matching_papers.csv";
    a.click();
  };

  const barValue = (b) => (normalize ? b.percent ?? b.count : b.count);
  const chartData = (bars) => bars.map((b) => ({ name: b.label, value: barValue(b), count: b.count }));

  // Shared x-axis maximum across all per-value charts, so bars are on the same
  // scale and can be compared directly. `nice()` rounds up to a clean number.
  const niceCeil = (v) => {
    if (!v || v <= 0) return normalize ? 100 : 1;
    const pow = Math.pow(10, Math.floor(Math.log10(v)));
    const step = pow <= 2 ? pow / 2 || 1 : pow;
    return Math.ceil(v / step) * step;
  };
  const panelMax = niceCeil(
    Math.max(0, ...((result?.panels || []).flatMap((p) => (p.bars || []).map(barValue))))
  );

  return (
    <div>
      <header className="mb-5">
        <h2 className="text-2xl font-semibold text-slate-900">Keyword Analysis</h2>
        <p className="text-slate-500 mt-1">
          Pick a top dimension and a breakdown dimension. Each selected top value gets its own
          chart of the breakdown distribution.
        </p>
      </header>

      {/* Saved views */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-slate-600">Saved views:</span>
        {views.length === 0 && <span className="text-xs text-slate-400">none yet</span>}
        {views.map((v) => (
          <span key={v.id} className={`flex items-center gap-1 rounded-full border px-3 py-1 text-xs ${activeView === v.id ? "border-blue-400 bg-blue-50 text-blue-700" : "border-slate-200 bg-white text-slate-600"}`}>
            <button onClick={() => applyView(v)}>{v.name}</button>
            <button onClick={() => deleteView(v.id)} className="text-slate-300 hover:text-red-500">✕</button>
          </span>
        ))}
      </div>

      {/* Config */}
      <div className="mb-5 grid gap-4 rounded-lg border border-slate-200 bg-white p-4 md:grid-cols-2">
        <div>
          <p className="text-xs font-medium text-slate-500">Top level (one chart per value)</p>
          <div className="mt-1 flex gap-2">
            <select className="input" value={topField} onChange={(e) => { setTopField(e.target.value); setTopValues([]); }}>
              <option value="">Select dimension…</option>
              {dims.map((d) => <option key={d.field} value={d.field}>{d.name}</option>)}
            </select>
            {topField && !isYear(topField) && (
              <select className="input w-32" value={topUnit} onChange={(e) => { setTopUnit(e.target.value); setTopValues([]); }}>
                <option value="category">Categories</option>
                <option value="tag">Raw tags</option>
              </select>
            )}
          </div>
          {topField && (
            <div className="mt-2 flex items-center gap-2 text-xs">
              <button onClick={() => setTopValues(topOptions.map((o) => o.label))}
                className="rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50">Select all</button>
              <button onClick={() => setTopValues([])}
                className="rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50">Clear</button>
              <span className="text-slate-400">{topValues.length} selected</span>
            </div>
          )}
          {topField && (
            <div className="mt-2 flex max-h-32 flex-wrap gap-1.5 overflow-auto">
              {topOptions.map((o) => (
                <button key={o.label} onClick={() => toggleTopValue(o.label)}
                  className={`rounded-full px-2.5 py-0.5 text-xs ${topValues.includes(o.label) ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}>
                  {o.label}{o.count != null ? ` · ${o.count}` : ""}
                </button>
              ))}
            </div>
          )}
        </div>
        <div>
          <p className="text-xs font-medium text-slate-500">Breakdown (chart axis)</p>
          <div className="mt-1 flex gap-2">
            <select className="input" value={brkField} onChange={(e) => setBrkField(e.target.value)}>
              <option value="">Select dimension…</option>
              {dims.filter((d) => d.field !== topField).map((d) => <option key={d.field} value={d.field}>{d.name}</option>)}
            </select>
            {brkField && !isYear(brkField) && (
              <select className="input w-32" value={brkUnit} onChange={(e) => setBrkUnit(e.target.value)}>
                <option value="category">Categories</option>
                <option value="tag">Raw tags</option>
              </select>
            )}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-600">
            <label className="flex items-center gap-1">Chart
              <select className="input py-1" value={chart} onChange={(e) => setChart(e.target.value)}>
                <option value="bar">Bar</option>
                <option value="pie">Pie</option>
              </select>
            </label>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={normalize} onChange={(e) => setNormalize(e.target.checked)} /> %
            </label>
            <label className="flex items-center gap-1">min count
              <input type="number" min="1" value={minCount} onChange={(e) => setMinCount(e.target.value)} className="input w-16 py-1" />
            </label>
            <button onClick={saveNew} className="btn-primary py-1">Save as new view</button>
            {activeView && <button onClick={saveExisting} className="rounded-md border border-slate-300 px-3 py-1 hover:bg-slate-50">Update view</button>}
          </div>
        </div>
      </div>

      {/* Charts */}
      {!result ? (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-400">
          Select a top dimension and a breakdown dimension to see the overview.
        </div>
      ) : (
        <div ref={chartsRef}>
          {/* Overview (always shown) */}
          <div className="mb-4 rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-slate-800">
                Overview · {dimOf(topField)?.name} distribution
              </h3>
              <div className="flex items-center gap-2">
                <PngButton onClick={() => exportChartPng(overviewRef.current, `overview-${dimOf(topField)?.name || "chart"}`)} />
                <button
                  onClick={() => exportAllChartsPng(chartsRef.current, `keyword-analysis-${dimOf(topField)?.name || "charts"}`)}
                  className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
                  title="Download every chart on this page as separate high-res PNGs"
                >
                  Download all
                </button>
              </div>
            </div>
            <div ref={overviewRef}>
              <ResponsiveContainer width="100%" height={Math.max(260, (result.overview?.dim1_bars.length || 1) * 30)}>
                <BarChart data={(result.overview?.dim1_bars || []).map((b) => ({ name: b.label, value: b.count }))}
                  layout="vertical" margin={{ left: 8, right: 40, top: 8, bottom: 8 }}
                  onClick={(e) => e?.activeLabel && openPapers(
                    `${dimOf(topField)?.name}: ${e.activeLabel}`,
                    [{ dimension: topField, unit: unitOf(topField, topUnit), value: e.activeLabel }])}>
                  <XAxis type="number" tick={{ fontSize: 12, fill: "#475569" }} axisLine={{ stroke: "#cbd5e1" }} tickLine={false} />
                  <YAxis type="category" dataKey="name" width={190} tick={{ fontSize: 12, fill: "#334155" }} axisLine={false} tickLine={false} />
                  <Tooltip cursor={{ fill: "rgba(148,163,184,0.12)" }} />
                  <Bar dataKey="value" fill="#3b82f6" radius={[0, 4, 4, 0]} cursor="pointer">
                    <LabelList dataKey="value" position="right" style={{ fontSize: 11, fill: "#475569" }} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {result.panels.length > 0 && (
            <p className="mb-2 text-xs font-medium uppercase text-slate-400">
              Per-value charts
            </p>
          )}
          <div className="grid gap-4 grid-cols-1">
            {result.panels.map((p, pi) => (
              <div key={p.value} className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="flex items-start justify-between gap-2">
                  <button
                    onClick={() => openPapers(
                      `${dimOf(topField)?.name}: ${p.value}`,
                      [{ dimension: topField, unit: unitOf(topField, topUnit), value: p.value }])}
                    className="text-left"
                    title="Open the paper list for this value"
                  >
                    <h3 className="text-sm font-semibold text-blue-700 hover:underline">{p.value}</h3>
                    <p className="text-xs text-blue-600 hover:underline">{p.paper_count} papers →</p>
                  </button>
                  {p.bars.length > 0 && (
                    <PngButton onClick={() => exportChartPng(panelRefs.current[p.value], `${p.value}-${dimOf(brkField)?.name || "breakdown"}`)} />
                  )}
                </div>
                {p.bars.length === 0 ? (
                  <p className="mt-6 text-center text-xs text-slate-400">No data.</p>
                ) : (
                  <div ref={(el) => { panelRefs.current[p.value] = el; }}>
                    <ResponsiveContainer width="100%" height={Math.max(220, p.bars.length * (chart === "pie" ? 20 : 26))}>
                      {chart === "pie" ? (
                        <PieChart>
                          <Pie data={chartData(p.bars)} dataKey="value" nameKey="name" innerRadius={55} outerRadius={110}
                            paddingAngle={1} stroke="#ffffff" strokeWidth={1.5}
                            label={(e) => e.name} cursor="pointer"
                            onClick={(d) => d?.name && openPapers(
                              `${p.value} → ${d.name}`,
                              [{ dimension: topField, unit: unitOf(topField, topUnit), value: p.value },
                               { dimension: brkField, unit: unitOf(brkField, brkUnit), value: d.name }])}>
                            {p.bars.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                          </Pie>
                          <Tooltip />
                        </PieChart>
                      ) : (
                        <BarChart data={chartData(p.bars)} layout="vertical" margin={{ left: 8, right: 40, top: 4, bottom: 4 }}
                          onClick={(e) => e?.activeLabel && openPapers(
                            `${p.value} → ${e.activeLabel}`,
                            [{ dimension: topField, unit: unitOf(topField, topUnit), value: p.value },
                             { dimension: brkField, unit: unitOf(brkField, brkUnit), value: e.activeLabel }])}>
                          <XAxis type="number" domain={[0, panelMax]} allowDataOverflow tick={{ fontSize: 12, fill: "#475569" }} axisLine={{ stroke: "#cbd5e1" }} tickLine={false} />
                          <YAxis type="category" dataKey="name" width={190} tick={{ fontSize: 12, fill: "#334155" }} axisLine={false} tickLine={false} />
                          <Tooltip cursor={{ fill: "rgba(148,163,184,0.12)" }} />
                          <Bar dataKey="value" fill={COLORS[pi % COLORS.length]} radius={[0, 4, 4, 0]} cursor="pointer">
                            <LabelList dataKey="value" position="right" style={{ fontSize: 11, fill: "#475569" }} />
                          </Bar>
                        </BarChart>
                      )}
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Matching papers */}
          {topValues.length > 0 && (
          <div className="mt-5 rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-slate-700">Matching papers ({filteredPapers.length})</h3>
              <div className="flex items-center gap-2">
                <input className="input py-1 text-sm" placeholder="search title…" value={search} onChange={(e) => { setSearch(e.target.value); setPage(0); }} />
                <button onClick={exportCsv} className="rounded-md border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50">CSV</button>
              </div>
            </div>
            <table className="mt-3 w-full text-sm">
              <thead className="text-left text-xs uppercase text-slate-500">
                <tr><th className="py-1">Index</th><th>Title</th><th>Year</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {pagePapers.map((p) => (
                  <tr key={p.index}>
                    <td className="py-1.5 pr-2 align-top text-slate-500">{p.index}</td>
                    <td className="py-1.5 pr-2 align-top text-slate-800">{p.title}</td>
                    <td className="py-1.5 align-top text-slate-500">{p.year}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {pages > 1 && (
              <div className="mt-3 flex items-center justify-end gap-2 text-xs">
                <button disabled={page === 0} onClick={() => setPage((n) => n - 1)} className="rounded border px-2 py-1 disabled:opacity-40">Prev</button>
                <span>{page + 1} / {pages}</span>
                <button disabled={page >= pages - 1} onClick={() => setPage((n) => n + 1)} className="rounded border px-2 py-1 disabled:opacity-40">Next</button>
              </div>
            )}
          </div>
          )}
        </div>
      )}
    </div>
  );
}
