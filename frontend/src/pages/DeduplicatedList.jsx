import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";
import PaperTable from "../components/PaperTable.jsx";

export default function DeduplicatedList() {
  const [papers, setPapers] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getDeduplicatedPapers().then(setPapers).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (!papers) return <p className="text-slate-500">Loading…</p>;

  return (
    <div>
      <div className="mb-2">
        <Link to="/deduplication" className="text-sm text-blue-600 hover:underline">
          ← Deduplication
        </Link>
      </div>
      <header className="mb-5">
        <h2 className="text-2xl font-semibold text-slate-900">Deduplicated list</h2>
        <p className="text-slate-500 mt-1">
          Final unique papers kept after deduplication · {papers.length} total
        </p>
      </header>

      {papers.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-500">
          No deduplicated papers yet. Run deduplication first on the{" "}
          <Link to="/deduplication" className="text-blue-600 hover:underline">
            Deduplication page
          </Link>
          .
        </div>
      ) : (
        <PaperTable
          papers={papers}
          searchPlaceholder="Search the deduplicated papers — title, index, DOI, author…"
        />
      )}
    </div>
  );
}
