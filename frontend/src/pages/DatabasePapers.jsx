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
