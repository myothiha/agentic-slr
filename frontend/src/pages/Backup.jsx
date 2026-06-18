import { useEffect, useState } from "react";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";

function fmtSize(bytes) {
  if (bytes == null) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let n = bytes;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

export default function Backup() {
  const [backups, setBackups] = useState(null);
  const [error, setError] = useState(null);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [working, setWorking] = useState(null); // name being restored/deleted

  const load = () => api.listBackups().then(setBackups).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (!backups) return <p className="text-slate-500">Loading…</p>;

  const create = async () => {
    setBusy(true);
    try {
      await api.createBackup(label.trim() || undefined);
      setLabel("");
      await load();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  };

  const restore = async (name) => {
    if (
      !confirm(
        `Restore from "${name}"?\n\nThis overwrites current project files with the ` +
          `backup's contents. A safety backup of the current state is taken first.`
      )
    )
      return;
    setWorking(name);
    try {
      const res = await api.restoreBackup(name);
      await load();
      alert(
        `Restored "${name}".\nA safety snapshot was saved as "${res.safety_backup}".\n\n` +
          `Restart the backend and refresh the app to load the restored data.`
      );
    } catch (e) {
      alert(e.message);
    } finally {
      setWorking(null);
    }
  };

  const remove = async (name) => {
    if (!confirm(`Delete backup "${name}"? This cannot be undone.`)) return;
    setWorking(name);
    try {
      await api.deleteBackup(name);
      await load();
    } catch (e) {
      alert(e.message);
    } finally {
      setWorking(null);
    }
  };

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-semibold text-slate-900">Backup &amp; Restore</h2>
        <p className="text-slate-500 mt-1">
          Snapshot the entire project (context, data, agents, code) into a zip you can
          restore later.
        </p>
      </header>

      {/* Create */}
      <div className="mb-6 flex items-end gap-3 rounded-lg border border-slate-200 bg-white p-4">
        <label className="flex-1">
          <span className="text-sm font-medium text-slate-700">Optional label</span>
          <input
            className="input mt-1"
            placeholder="e.g. after-screening-round-1"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
        </label>
        <button onClick={create} disabled={busy} className="btn-primary">
          {busy ? "Creating…" : "Create backup"}
        </button>
      </div>

      {/* List */}
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3">Backup</th>
              <th className="px-4 py-3">Created</th>
              <th className="px-4 py-3">Size</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {backups.map((b) => (
              <tr key={b.name}>
                <td className="px-4 py-3 font-mono text-xs text-slate-700">{b.name}</td>
                <td className="px-4 py-3 text-slate-600">
                  {new Date(b.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-3 text-slate-600">{fmtSize(b.size)}</td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-3">
                    <button
                      onClick={() => restore(b.name)}
                      disabled={working === b.name}
                      className="text-xs text-blue-600 hover:underline disabled:opacity-50"
                    >
                      {working === b.name ? "…" : "Restore"}
                    </button>
                    <button
                      onClick={() => remove(b.name)}
                      disabled={working === b.name}
                      className="text-xs text-red-600 hover:underline disabled:opacity-50"
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {backups.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-slate-400">
                  No backups yet. Click “Create backup” to make one.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Notes */}
      <div className="mt-6 grid grid-cols-2 gap-4">
        <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-700">
          <p className="font-semibold text-slate-800">Where backups are stored</p>
          <p className="mt-1">
            Zips are saved in the <span className="font-mono">backups/</span> folder inside your
            project. For safety, your <span className="font-mono">.env</span> file (API keys) is{" "}
            <span className="font-medium">excluded</span> — only{" "}
            <span className="font-mono">.env.example</span> is kept. After restoring, re-enter your
            API key in <span className="font-mono">.env</span>.
          </p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-700">
          <p className="font-semibold text-slate-800">Recommended cloud storage</p>
          <ul className="mt-1 list-disc pl-5 space-y-1">
            <li>
              <span className="font-medium">Google Drive / OneDrive / Dropbox</span> — simplest;
              your university likely gives you a large free quota. Put the{" "}
              <span className="font-mono">backups/</span> folder in a synced location.
            </li>
            <li>
              <span className="font-medium">Private GitHub repo</span> — great for the code; pair
              with Drive for the large data zips (or use Git LFS).
            </li>
            <li>
              <span className="font-medium">Backblaze B2 / AWS S3</span> — cheap, durable object
              storage if you want versioned offsite copies.
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
}
