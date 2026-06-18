import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getDashboard().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (!data) return <p className="text-slate-500">Loading…</p>;

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-semibold text-slate-900">Dashboard</h2>
        <p className="text-slate-500 mt-1">
          {data.title ? data.title : "Configure your review context to get started."}
        </p>
      </header>

      {/* Pipeline progress */}
      <section className="mb-8">
        <h3 className="text-sm font-semibold text-slate-700 mb-3">Pipeline progress</h3>
        <div className="grid grid-cols-3 gap-4">
          {data.stages.map((s, i) => (
            <div
              key={s.key}
              className={`rounded-lg border p-4 ${
                s.done ? "border-green-300 bg-green-50" : "border-slate-200 bg-white"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-slate-500">Step {i + 1}</span>
                <span
                  className={`text-xs font-semibold ${
                    s.done ? "text-green-600" : "text-slate-400"
                  }`}
                >
                  {s.done ? "Active" : "Pending"}
                </span>
              </div>
              <p className="mt-2 font-semibold text-slate-800">{s.label}</p>
              <p className="text-2xl font-bold text-slate-900 mt-1">{s.count}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Summary cards */}
      <section className="mb-8 grid grid-cols-3 gap-4">
        <StatCard label="Total papers" value={data.total_papers} />
        <StatCard label="Databases" value={data.databases.length} />
        <StatCard
          label="Highlight terms"
          value={data.highlight_terms}
          sub={data.highlight_source ? `via ${data.highlight_source}` : "none yet"}
        />
      </section>

      {/* Per-database status */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-700">Papers per database</h3>
          <Link to="/ingestion" className="text-sm text-blue-600 hover:underline">
            Upload data →
          </Link>
        </div>
        <div className="grid grid-cols-2 gap-4">
          {data.databases.map((db) => (
            <div key={db.id} className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="flex items-center justify-between">
                <p className="font-semibold text-slate-800">{db.name}</p>
                <span className="text-xs rounded bg-slate-100 px-2 py-0.5 text-slate-600">
                  {db.prefix}
                </span>
              </div>
              <p className="text-2xl font-bold text-slate-900 mt-2">{db.paper_count}</p>
              <p className="text-xs text-slate-400 mt-1">
                {db.index_range || "No papers ingested"}
              </p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function StatCard({ label, value, sub }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className="text-3xl font-bold text-slate-900 mt-1">{value}</p>
      {sub && <p className="text-xs text-slate-400 mt-1">{sub}</p>}
    </div>
  );
}

export function ErrorBox({ message }) {
  return (
    <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
      <p className="font-semibold">Could not reach the backend.</p>
      <p className="mt-1">{message}</p>
      <p className="mt-2 text-red-500">
        Make sure the FastAPI server is running on port 8000.
      </p>
    </div>
  );
}
