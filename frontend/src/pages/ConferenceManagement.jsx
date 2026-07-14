import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";

export default function ConferenceManagement() {
  const [confs, setConfs] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null); // `${id}:fetch` | `${id}:enrich`
  const [display, setDisplay] = useState("");
  const [fullName, setFullName] = useState("");
  const [dblpKey, setDblpKey] = useState("");
  const [defStart, setDefStart] = useState(2020);
  const [defEnd, setDefEnd] = useState(2025);
  const [runLog, setRunLog] = useState(null); // { title, lines }
  const [orCookie, setOrCookie] = useState(""); // OpenReview captcha cookie (session-only)
  const navigate = useNavigate();

  const load = () => api.getConferences().then(setConfs).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    api
      .getConferenceDefaults()
      .then((d) => {
        setDefStart(d.year_start);
        setDefEnd(d.year_end);
      })
      .catch(() => {});
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (!confs) return <p className="text-slate-500">Loading…</p>;

  const runFetch = async (c) => {
    setBusy(`${c.id}:fetch`);
    try {
      const r = await api.fetchConference(c.id);
      setRunLog({ title: `Fetch ${c.display}`, lines: r.log || [] });
      const failed = (r.failed_tocs || []).length;
      alert(
        `Fetched ${c.display}: ${r.total} papers` +
          (failed ? `\n${failed} year(s) failed — re-run to retry.` : "")
      );
      await load();
    } catch (e) {
      alert(`Fetch failed: ${e.message}`);
    } finally {
      setBusy(null);
    }
  };

  const runEnrich = async (c) => {
    setBusy(`${c.id}:enrich`);
    try {
      const r = await api.enrichConference(c.id, { openreviewCookie: orCookie.trim() || null });
      setRunLog({ title: `Enrich ${c.display}`, lines: r.log || [] });
      alert(
        `Enriched ${c.display}: +${r.enriched} abstracts ` +
          `(${r.with_abstract}/${r.total} now have abstracts, ${r.unmatched} unmatched).`
      );
      await load();
    } catch (e) {
      alert(`Enrich failed: ${e.message}`);
    } finally {
      setBusy(null);
    }
  };

  const editYears = async (c) => {
    const next = window.prompt(
      `Year range for "${c.display}" (format: start-end):`,
      `${c.year_start}-${c.year_end}`
    );
    if (!next) return;
    const m = next.match(/^\s*(\d{4})\s*-\s*(\d{4})\s*$/);
    if (!m) return alert("Enter a range like 2020-2025.");
    try {
      await api.updateConference(c.id, {
        year_start: Number(m[1]),
        year_end: Number(m[2]),
      });
      await load();
    } catch (e) {
      alert(e.message);
    }
  };

  const toggleEnabled = async (c) => {
    try {
      await api.updateConference(c.id, { enabled: !c.enabled });
      await load();
    } catch (e) {
      alert(e.message);
    }
  };

  const clearAbstracts = async (c) => {
    if (!c.with_abstract) return;
    if (!confirm(`Clear all ${c.with_abstract} enriched abstracts for "${c.display}"? The papers stay; re-enrich to refill.`))
      return;
    try {
      const r = await api.clearConferenceAbstracts(c.id);
      alert(`Cleared ${r.cleared} abstracts for ${c.display}.`);
      await load();
    } catch (e) {
      alert(e.message);
    }
  };

  const empty = async (c) => {
    if (!c.paper_count) return;
    if (!confirm(`Empty the fetched papers for "${c.display}"? The venue stays; you can re-fetch.`))
      return;
    try {
      await api.clearConferencePapers(c.id);
      await load();
    } catch (e) {
      alert(e.message);
    }
  };

  const remove = async (c) => {
    if (
      !confirm(
        `Remove the WHOLE venue "${c.display}" from the list? ` +
          `This deletes the venue and its ${c.paper_count} fetched paper(s).\n\n` +
          `If you only want to clear the papers, use “Empty” instead.`
      )
    )
      return;
    try {
      await api.deleteConference(c.id);
      await load();
    } catch (e) {
      alert(e.message);
    }
  };

  const saveDefaults = async (applyToAll) => {
    if (!(defStart >= 1990 && defEnd >= defStart)) {
      return alert("Enter a valid year range (start ≤ end).");
    }
    try {
      await api.setConferenceDefaults(Number(defStart), Number(defEnd), applyToAll);
      await load();
      if (applyToAll) alert(`Applied ${defStart}–${defEnd} to all venues.`);
    } catch (e) {
      alert(e.message);
    }
  };

  const add = async (e) => {
    e.preventDefault();
    if (!display.trim() || !dblpKey.trim()) return;
    try {
      await api.addConference({
        display: display.trim(),
        full_name: fullName.trim() || null,
        dblp_key: dblpKey.trim(),
      });
      setDisplay("");
      setFullName("");
      setDblpKey("");
      await load();
    } catch (err) {
      alert(err.message);
    }
  };

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-semibold text-slate-900">Conference Management</h2>
        <p className="text-slate-500 mt-1">
          Enumerate accepted papers from top venues via DBLP. Use “Fetch” to pull a venue’s
          papers, “Enrich” to attach abstracts, and “Check papers” to view the list.
        </p>
      </header>

      {runLog && (
        <div className="mb-5 rounded-lg border border-slate-200 bg-slate-900 p-4">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-300">
              {runLog.title} — run log ({runLog.lines.length} lines)
            </p>
            <div className="flex items-center gap-3">
              <button
                onClick={() => navigator.clipboard?.writeText(runLog.lines.join("\n"))}
                className="text-xs text-slate-300 hover:text-white"
              >
                Copy
              </button>
              <button
                onClick={() => setRunLog(null)}
                className="text-xs text-slate-400 hover:text-white"
              >
                Dismiss
              </button>
            </div>
          </div>
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words text-[11px] leading-relaxed text-slate-200">
            {runLog.lines.length ? runLog.lines.join("\n") : "(no log lines returned)"}
          </pre>
        </div>
      )}

      <div className="mb-5 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-4">
        <div>
          <span className="text-sm font-medium text-slate-700">Default year range</span>
          <div className="mt-1 flex items-center gap-2">
            <input
              type="number"
              className="input w-24"
              value={defStart}
              onChange={(e) => setDefStart(e.target.value)}
            />
            <span className="text-slate-400">–</span>
            <input
              type="number"
              className="input w-24"
              value={defEnd}
              onChange={(e) => setDefEnd(e.target.value)}
            />
          </div>
        </div>
        <button onClick={() => saveDefaults(false)} className="btn-secondary">
          Save default
        </button>
        <button onClick={() => saveDefaults(true)} className="btn-primary">
          Apply to all venues
        </button>
        <p className="basis-full text-xs text-slate-400">
          “Save default” sets the range used for newly added venues. “Apply to all venues” also
          overwrites every existing venue’s range (then re-fetch to pull those years).
        </p>
      </div>

      <div className="mb-5 rounded-lg border border-slate-200 bg-white p-4">
        <div className="mb-2 flex items-center justify-between gap-3">
          <span className="text-sm font-medium text-slate-700">
            OpenReview cookie{" "}
            <span className="font-normal text-slate-400">(optional — for ICLR abstract enrichment)</span>
          </span>
          <button
            type="button"
            onClick={() =>
              window.open(
                "https://api2.openreview.net/notes?content.venueid=ICLR.cc/2024/Conference&limit=2",
                "_blank",
                "noopener"
              )
            }
            className="btn-secondary whitespace-nowrap"
          >
            1. Open OpenReview to get token ↗
          </button>
        </div>
        <textarea
          className="input h-16 w-full font-mono text-xs"
          placeholder="2. Solve the captcha, then copy openreview.clearanceToken (DevTools → Application → Cookies) and paste it here. 3. Click Enrich on a venue — do it within ~5 min, the token expires fast."
          value={orCookie}
          onChange={(e) => setOrCookie(e.target.value)}
        />
        <p className="mt-1 text-xs text-slate-400">
          Kept in memory for this session only (not saved). Used for the next Enrich you run. You
          can paste just the token — the app wraps it automatically.
        </p>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-3">Venue</th>
              <th className="px-4 py-3">Venue Name</th>
              <th className="px-4 py-3">DBLP key</th>
              <th className="px-4 py-3">Track</th>
              <th className="px-4 py-3">Years</th>
              <th className="px-4 py-3">Papers (by year)</th>
              <th className="px-4 py-3">Abstracts</th>
              <th className="px-4 py-3">Last fetched</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {confs.map((c) => (
              <tr key={c.id} className={c.enabled ? "" : "opacity-50"}>
                <td className="px-4 py-3 font-medium text-slate-800">{c.display}</td>
                <td className="px-4 py-3 text-slate-600 max-w-[16rem]">{c.full_name}</td>
                <td className="px-4 py-3">
                  <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-600">
                    {c.dblp_key}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-500">{c.track}</td>
                <td className="px-4 py-3 text-slate-600 whitespace-nowrap">
                  {c.year_start}–{c.year_end}
                </td>
                <td className="px-4 py-3">
                  <div className="font-medium text-slate-800">{c.paper_count}</div>
                  {c.per_year && Object.keys(c.per_year).length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {Object.entries(c.per_year).map(([y, n]) => (
                        <span
                          key={y}
                          className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600"
                        >
                          {y}: {n}
                        </span>
                      ))}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 whitespace-nowrap">
                  {c.paper_count ? (
                    <span
                      className={
                        c.with_abstract === c.paper_count
                          ? "text-green-700"
                          : c.with_abstract
                          ? "text-slate-700"
                          : "text-slate-400"
                      }
                      title={`${c.with_abstract} of ${c.paper_count} papers have an abstract`}
                    >
                      {c.with_abstract}/{c.paper_count}
                      <span className="ml-1 text-xs text-slate-400">
                        ({Math.round((100 * c.with_abstract) / c.paper_count)}%)
                      </span>
                    </span>
                  ) : (
                    <span className="text-slate-400">—</span>
                  )}
                </td>
                <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">
                  {c.last_fetched ? new Date(c.last_fetched).toLocaleDateString() : "—"}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    <button
                      onClick={() => navigate(`/conferences/${c.id}`)}
                      disabled={!c.paper_count}
                      className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"
                    >
                      Check papers
                    </button>
                    <button
                      onClick={() => runFetch(c)}
                      disabled={busy !== null}
                      className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"
                    >
                      {busy === `${c.id}:fetch` ? "Fetching…" : "Fetch"}
                    </button>
                    <button
                      onClick={() => runEnrich(c)}
                      disabled={busy !== null || !c.paper_count}
                      className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"
                    >
                      {busy === `${c.id}:enrich` ? "Enriching…" : "Enrich"}
                    </button>
                    <button
                      onClick={() => clearAbstracts(c)}
                      disabled={busy !== null || !c.with_abstract}
                      className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"
                      title="Clear enriched abstracts (keeps papers)"
                    >
                      Clear abstracts
                    </button>
                    <button
                      onClick={() => editYears(c)}
                      className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                    >
                      Years
                    </button>
                    <button
                      onClick={() => toggleEnabled(c)}
                      className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                    >
                      {c.enabled ? "Disable" : "Enable"}
                    </button>
                    <button
                      onClick={() => empty(c)}
                      disabled={!c.paper_count}
                      className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"
                    >
                      Empty
                    </button>
                    <button onClick={() => remove(c)} className="text-xs text-red-600 hover:underline">
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
        className="mt-6 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-4"
      >
        <label className="flex-1 min-w-[10rem]">
          <span className="text-sm font-medium text-slate-700">Add venue — short name</span>
          <input
            className="input mt-1"
            placeholder="e.g. AISTATS"
            value={display}
            onChange={(e) => setDisplay(e.target.value)}
          />
        </label>
        <label className="flex-1 min-w-[12rem]">
          <span className="text-sm font-medium text-slate-700">Venue name (optional)</span>
          <input
            className="input mt-1"
            placeholder="e.g. Artificial Intelligence and Statistics"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
          />
        </label>
        <label className="flex-1 min-w-[10rem]">
          <span className="text-sm font-medium text-slate-700">DBLP key</span>
          <input
            className="input mt-1 font-mono"
            placeholder="e.g. conf/aistats"
            value={dblpKey}
            onChange={(e) => setDblpKey(e.target.value)}
          />
        </label>
        <button type="submit" className="btn-primary">
          Add
        </button>
      </form>

      <p className="mt-3 text-xs text-slate-400">
        Fetch and Enrich call external services (DBLP, OpenReview, OpenAlex) and can take a while
        for large venues. The button stays disabled until the run finishes.
      </p>
    </div>
  );
}
