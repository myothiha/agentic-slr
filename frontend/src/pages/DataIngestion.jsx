import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";

export default function DataIngestion() {
  const [dbs, setDbs] = useState(null);
  const [error, setError] = useState(null);
  const [target, setTarget] = useState("");
  const [files, setFiles] = useState([]);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const inputRef = useRef(null);

  const load = () =>
    api
      .getDatabases()
      .then((d) => {
        setDbs(d);
        if (!target && d.length) setTarget(d[0].id);
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    load();
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (!dbs) return <p className="text-slate-500">Loading…</p>;

  const onPick = (fileList) => {
    setFiles((prev) => [...prev, ...Array.from(fileList)]);
  };

  const removeFile = (i) => setFiles(files.filter((_, idx) => idx !== i));

  const upload = async () => {
    if (!target || !files.length) return;
    setUploading(true);
    setResult(null);
    try {
      const res = await api.ingest(target, files);
      setResult(res);
      setFiles([]);
      await load();
    } catch (e) {
      setResult({ error: e.message });
    } finally {
      setUploading(false);
    }
  };

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-semibold text-slate-900">Data Ingestion</h2>
        <p className="text-slate-500 mt-1">
          Upload RIS, CSV, or BibTeX exports. Multiple files for one database are combined
          and indexed sequentially.
        </p>
      </header>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2 space-y-4">
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Target database</span>
            <select
              className="input mt-1"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              {dbs.map((db) => (
                <option key={db.id} value={db.id}>
                  {db.name} ({db.prefix}) — {db.paper_count} papers
                </option>
              ))}
            </select>
          </label>

          {/* Dropzone */}
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              onPick(e.dataTransfer.files);
            }}
            onClick={() => inputRef.current?.click()}
            className={`cursor-pointer rounded-lg border-2 border-dashed p-10 text-center transition ${
              dragging ? "border-blue-400 bg-blue-50" : "border-slate-300 bg-white"
            }`}
          >
            <p className="text-slate-600 font-medium">
              Drag &amp; drop files here, or click to browse
            </p>
            <p className="text-xs text-slate-400 mt-1">.ris · .csv · .tsv · .bib</p>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept=".ris,.csv,.tsv,.bib,.bibtex,.txt"
              className="hidden"
              onChange={(e) => onPick(e.target.files)}
            />
          </div>

          {files.length > 0 && (
            <div className="rounded-lg border border-slate-200 bg-white p-3">
              <p className="text-sm font-medium text-slate-700 mb-2">
                {files.length} file(s) selected
              </p>
              <ul className="space-y-1">
                {files.map((f, i) => (
                  <li
                    key={i}
                    className="flex items-center justify-between text-sm text-slate-600"
                  >
                    <span>
                      {f.name}{" "}
                      <span className="text-slate-400">({(f.size / 1024).toFixed(1)} KB)</span>
                    </span>
                    <button
                      onClick={() => removeFile(i)}
                      className="text-xs text-red-500 hover:underline"
                    >
                      remove
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <button
            onClick={upload}
            disabled={uploading || !files.length}
            className="btn-primary"
          >
            {uploading ? "Ingesting…" : `Ingest into ${dbs.find((d) => d.id === target)?.name || ""}`}
          </button>

          {result && (
            <div
              className={`rounded-md border p-3 text-sm ${
                result.error
                  ? "border-red-200 bg-red-50 text-red-700"
                  : "border-green-200 bg-green-50 text-green-700"
              }`}
            >
              {result.error ? (
                <p>Error: {result.error}</p>
              ) : (
                <div>
                  <p className="font-semibold">
                    Added {result.added} new paper(s) to {result.database}
                    {result.skipped > 0 && (
                      <> · skipped {result.skipped} already present</>
                    )}
                    .
                  </p>
                  <p className="mt-1">
                    Total now {result.total} · Index range {result.index_range}
                  </p>
                  <ul className="mt-1 text-green-600">
                    {result.files.map((f, i) => (
                      <li key={i}>
                        {f.filename}: {f.parsed} parsed → {f.added} added
                        {f.skipped > 0 && `, ${f.skipped} skipped`}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Ingested overview */}
        <div>
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <h3 className="text-sm font-semibold text-slate-700 mb-3">Ingested databases</h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-400">
                  <th className="pb-2">Database</th>
                  <th className="pb-2 text-right">Papers</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {dbs.map((db) => (
                  <tr key={db.id}>
                    <td className="py-2">
                      <p className="font-medium text-slate-700">{db.name}</p>
                      <p className="text-xs text-slate-400">{db.index_range || "—"}</p>
                    </td>
                    <td className="py-2 text-right font-semibold text-slate-800">
                      {db.paper_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
