import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";

export default function DatabaseManagement() {
  const [dbs, setDbs] = useState(null);
  const [error, setError] = useState(null);
  const [name, setName] = useState("");
  const [prefix, setPrefix] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  const load = () => api.getDatabases().then(setDbs).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (!dbs) return <p className="text-slate-500">Loading…</p>;

  const add = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      await api.addDatabase({ name: name.trim(), prefix: prefix.trim() || null });
      setName("");
      setPrefix("");
      await load();
    } catch (err) {
      alert(err.message);
    } finally {
      setBusy(false);
    }
  };

  const empty = async (db) => {
    if (!db.paper_count) return;
    if (
      !confirm(
        `Empty the paper list for "${db.name}"? This deletes all ${db.paper_count} ingested paper(s). The database itself stays.\n\n` +
          "Only these papers are removed from the pipeline — deduplication is " +
          "re-reconciled automatically, and every other database's screening, " +
          "tagging and full-text decisions are preserved."
      )
    )
      return;
    try {
      await api.clearPapers(db.id);
      await load();
    } catch (err) {
      alert(err.message);
    }
  };

  const editProxy = async (db) => {
    const next = window.prompt(
      `Institutional proxy host suffix for "${db.name}" (optional).\n\n` +
        "EZproxy hostname-remapping style. Enter EITHER just the suffix:\n" +
        "  mediaproxy.imtbs-tsp.eu\n" +
        "OR the full proxied host copied from your browser:\n" +
        "  ieeexplore-ieee-org.mediaproxy.imtbs-tsp.eu\n\n" +
        "Download links are rewritten, e.g.\n" +
        "  ieeexplore.ieee.org → ieeexplore-ieee-org.mediaproxy.imtbs-tsp.eu\n\n" +
        "Leave blank to clear.",
      db.proxy_suffix || ""
    );
    if (next === null) return; // cancelled
    try {
      await api.updateDatabase(db.id, { proxy_suffix: next.trim() });
      await load();
    } catch (err) {
      alert(err.message);
    }
  };

  const remove = async (db) => {
    if (
      !confirm(
        `Remove "${db.name}"? This also deletes its ${db.paper_count} ingested paper(s).`
      )
    )
      return;
    try {
      await api.deleteDatabase(db.id);
      await load();
    } catch (err) {
      alert(err.message);
    }
  };

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-semibold text-slate-900">Database Management</h2>
        <p className="text-slate-500 mt-1">
          Configure the data sources for your review. Use “Check Raw paper list” to view and search a database’s papers.
        </p>
      </header>

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3">Priority</th>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Prefix</th>
              <th className="px-4 py-3">Proxy</th>
              <th className="px-4 py-3">Papers</th>
              <th className="px-4 py-3">Index range</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {dbs.map((db) => (
              <tr key={db.id}>
                <td className="px-4 py-3 text-slate-500">{db.priority}</td>
                <td className="px-4 py-3 font-medium text-slate-800">{db.name}</td>
                <td className="px-4 py-3">
                  <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                    {db.prefix}
                  </span>
                </td>
                <td className="px-4 py-3">
                  {db.proxy_suffix ? (
                    <span className="font-mono text-xs text-slate-600" title={db.proxy_suffix}>
                      {db.proxy_suffix}
                    </span>
                  ) : (
                    <span className="text-slate-400">—</span>
                  )}
                </td>
                <td className="px-4 py-3">{db.paper_count}</td>
                <td className="px-4 py-3 text-slate-400">{db.index_range || "—"}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-3">
                    <button
                      onClick={() => navigate(`/databases/${db.id}`)}
                      className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                    >
                      Check Raw paper list
                    </button>
                    <button
                      onClick={() => editProxy(db)}
                      className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                    >
                      Edit proxy
                    </button>
                    <button
                      onClick={() => empty(db)}
                      disabled={!db.paper_count}
                      className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      Empty
                    </button>
                    <button
                      onClick={() => remove(db)}
                      className="text-xs text-red-600 hover:underline"
                    >
                      Remove
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <form
        onSubmit={add}
        className="mt-6 flex items-end gap-3 rounded-lg border border-slate-200 bg-white p-4"
      >
        <label className="flex-1">
          <span className="text-sm font-medium text-slate-700">Add custom database</span>
          <input
            className="input mt-1"
            placeholder="Database name (e.g. SpringerLink)"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="w-40">
          <span className="text-sm font-medium text-slate-700">Prefix (optional)</span>
          <input
            className="input mt-1 uppercase"
            placeholder="auto"
            value={prefix}
            onChange={(e) => setPrefix(e.target.value)}
          />
        </label>
        <button type="submit" disabled={busy} className="btn-primary">
          {busy ? "Adding…" : "Add"}
        </button>
      </form>
    </div>
  );
}
