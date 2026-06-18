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
