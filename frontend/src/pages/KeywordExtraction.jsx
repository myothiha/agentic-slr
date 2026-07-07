import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";

const PALETTE = [
  "#fde68a", "#bbf7d0", "#bfdbfe", "#fbcfe8",
  "#ddd6fe", "#fed7aa", "#a7f3d0", "#c7d2fe",
];
const colorFor = (i) => PALETTE[i % PALETTE.length];

function highlightSegments(text, marks) {
  if (!text) return [{ text: "" }];
  const lower = text.toLowerCase();
  const ranges = [];
  for (const m of marks) {
    const q = (m.evidence || "").trim().toLowerCase();
    if (q.length < 4) continue;
    const at = lower.indexOf(q);
    if (at !== -1) ranges.push({ start: at, end: at + q.length, color: m.color, tag: m.tag });
  }
  ranges.sort((a, b) => a.start - b.start);
  const clean = [];
  let lastEnd = 0;
  for (const r of ranges) {
    if (r.start >= lastEnd) {
      clean.push(r);
      lastEnd = r.end;
    }
  }
  const segs = [];
  let pos = 0;
  for (const r of clean) {
    if (r.start > pos) segs.push({ text: text.slice(pos, r.start) });
    segs.push({ text: text.slice(r.start, r.end), color: r.color, tag: r.tag });
    pos = r.end;
  }
  if (pos < text.length) segs.push({ text: text.slice(pos) });
  return segs;
}

export default function KeywordExtraction() {
  const [dims, setDims] = useState(null);
  const [field, setField] = useState(null);
  const [state, setState] = useState(null);
  const [papers, setPapers] = useState([]);
  const [error, setError] = useState(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [prefRows, setPrefRows] = useState([]);
  const [newName, setNewName] = useState("");
  const [newOpen, setNewOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [suggesting, setSuggesting] = useState(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [expanded, setExpanded] = useState(null);

  const loadDims = () =>
    api.listTaggingDimensions().then((d) => {
      setDims(d);
      setField((prev) => {
        if (prev && d.dimensions.some((x) => x.field === prev)) return prev;
        return d.dimensions[0]?.field || null;
      });
    }).catch((e) => setError(e.message));

  const loadDim = (f) =>
    Promise.all([api.getTagging(f), api.getTaggingPapers(f)])
      .then(([s, p]) => {
        setState(s);
        setPapers(p);
        setName(s.name || "");
        setDescription(s.description || "");
        const descs = s.tag_descriptions || {};
        setPrefRows((s.preferred || []).map((t) => ({ tag: t, description: descs[t] || "" })));
        setResult(null);
        setExpanded(null);
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    loadDims();
  }, []);
  useEffect(() => {
    if (field) loadDim(field);
    else {
      setState(null);
      setPapers([]);
    }
  }, [field]);

  if (error) return <ErrorBox message={error} />;
  if (!dims) return <p className="text-slate-500">Loading…</p>;

  const createDimension = async () => {
    if (!newName.trim()) return;
    setSaving(true);
    try {
      const dim = await api.createTaggingDimension({ name: newName.trim() });
      setNewName("");
      setNewOpen(false);
      await loadDims();
      setField(dim.field);
    } catch (e) {
      alert(e.message);
    } finally {
      setSaving(false);
    }
  };

  const cleanRows = () =>
    prefRows
      .map((r) => ({ tag: r.tag.trim(), description: r.description.trim() }))
      .filter((r) => r.tag);
  const updateRow = (i, key, val) =>
    setPrefRows((rows) => rows.map((r, idx) => (idx === i ? { ...r, [key]: val } : r)));
  const addRow = () => setPrefRows((rows) => [...rows, { tag: "", description: "" }]);
  const removeRow = (i) => setPrefRows((rows) => rows.filter((_, idx) => idx !== i));

  const suggestField = async (target) => {
    setSuggesting(target);
    try {
      const res = await api.suggestTagging(field, {
        target,
        name: name.trim(),
        description: description.trim(),
      });
      if (!res.available) {
        alert(res.error || "Suggestion is not available.");
        return;
      }
      if (target === "description" && res.description) setDescription(res.description);
      if (target === "keywords" && res.keywords)
        setPrefRows(res.keywords.map((k) => ({ tag: k.tag, description: k.description || "" })));
    } catch (e) {
      alert(e.message);
    } finally {
      setSuggesting(null);
    }
  };

  const SuggestBtn = ({ target }) => (
    <button
      type="button"
      onClick={() => suggestField(target)}
      disabled={suggesting !== null || !name.trim() || !state?.llm_available}
      title={
        !state?.llm_available
          ? "LLM not configured"
          : "Suggest from the Include papers' metadata"
      }
      className="rounded-md border border-violet-200 bg-violet-50 px-2 py-0.5 text-xs font-medium text-violet-700 hover:bg-violet-100 disabled:opacity-40"
    >
      {suggesting === target ? "Suggesting…" : "✨ LLM Suggest"}
    </button>
  );

  const saveDefinition = async () => {
    setSaving(true);
    try {
      const rows = cleanRows();
      const tag_descriptions = {};
      rows.forEach((r) => {
        tag_descriptions[r.tag] = r.description;
      });
      await api.updateTaggingDimension(field, {
        name: name.trim(),
        description: description.trim(),
        preferred: rows.map((r) => r.tag),
        tag_descriptions,
      });
      await loadDims();
      await loadDim(field);
    } catch (e) {
      alert(e.message);
    } finally {
      setSaving(false);
    }
  };

  const deleteDimension = async () => {
    if (!confirm(`Delete definition "${state.name}" and all its tags/groups? Other definitions are unaffected.`))
      return;
    try {
      await api.deleteTaggingDimension(field);
      setField(null);
      await loadDims();
    } catch (e) {
      alert(e.message);
    }
  };

  const runExtraction = async (force = false) => {
    setRunning(true);
    setResult(null);
    try {
      const res = await api.runTaggingExtraction(field, { force });
      setResult(res);
      await loadDim(field);
      await loadDims();
    } catch (e) {
      setResult({ error: e.message });
    } finally {
      setRunning(false);
    }
  };

  const rowsKey = (rows) =>
    rows.map((r) => `${r.tag.trim().toLowerCase()}::${r.description.trim()}`).join("|");
  const stateRowsKey = state
    ? (state.preferred || [])
        .map((t) => `${t}::${(state.tag_descriptions || {})[t] || ""}`)
        .join("|")
    : "";
  const dirty =
    !!state &&
    (name.trim() !== (state.name || "") ||
      description.trim() !== (state.description || "") ||
      rowsKey(cleanRows()) !== stateRowsKey);

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-semibold text-slate-900">Keyword Extraction</h2>
        <p className="text-slate-500 mt-1">
          Define one or more independent keyword dimensions (e.g. E-commerce task, LLM technique).
          Each runs and stores its tags separately.{" "}
          <Link to="/tagging/groups" className="text-blue-600 hover:underline">
            Group &amp; categorize →
          </Link>
        </p>
      </header>

      {/* Dimension selector */}
      <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white p-3">
        <span className="text-sm font-medium text-slate-600">Definition:</span>
        {dims.dimensions.length > 0 ? (
          <select
            className="input max-w-xs"
            value={field || ""}
            onChange={(e) => setField(e.target.value)}
          >
            {dims.dimensions.map((d) => (
              <option key={d.field} value={d.field}>
                {d.name} ({d.field}) · {d.processed_total} tagged
              </option>
            ))}
          </select>
        ) : (
          <span className="text-sm text-slate-400">none yet</span>
        )}
        {!newOpen ? (
          <button
            onClick={() => setNewOpen(true)}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            ＋ New definition
          </button>
        ) : (
          <span className="flex items-center gap-2">
            <input
              className="input"
              placeholder="e.g. LLM technique"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && createDimension()}
              autoFocus
            />
            <button onClick={createDimension} disabled={saving || !newName.trim()} className="btn-primary">
              Create
            </button>
            <button onClick={() => setNewOpen(false)} className="text-sm text-slate-500 hover:underline">
              cancel
            </button>
          </span>
        )}
      </div>

      {!field && (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-500">
          Create a definition to start extracting keywords.
        </div>
      )}

      {field && state && (
        <>
          {!state.llm_available && (
            <div className="mb-5 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              The LLM provider ({state.provider}) is not configured — set an API key in{" "}
              <code>.env</code> to run extraction.
            </div>
          )}

          {/* Definition editor */}
          <div className="mb-5 rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-slate-700">
                Definition
                <span className="ml-2 rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                  field: {state.field}
                </span>
              </h3>
              <button onClick={deleteDimension} className="text-xs text-red-600 hover:underline">
                delete definition
              </button>
            </div>
            <label className="mt-3 block">
              <span className="text-xs font-medium text-slate-500">Name</span>
              <input className="input mt-1" value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <div className="mt-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-slate-500">Description</span>
                <SuggestBtn target="description" />
              </div>
              <textarea
                className="input mt-1 h-24"
                placeholder="e.g. the E-commerce task such as recommendation, product search, sale assistant, shopping cart"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <div className="mt-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-slate-500">
                  Preferred keywords{" "}
                  <span className="font-normal text-slate-400">(optional — tag + short description)</span>
                </span>
                <SuggestBtn target="keywords" />
              </div>
              <div className="mt-2 space-y-2">
                {prefRows.length === 0 && (
                  <p className="text-xs text-slate-400">
                    None yet — add rows or use ✨ LLM Suggest.
                  </p>
                )}
                {prefRows.map((r, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <input
                      className="input w-48 shrink-0"
                      placeholder="tag (e.g. fine-tuning)"
                      value={r.tag}
                      onChange={(e) => updateRow(i, "tag", e.target.value)}
                    />
                    <input
                      className="input flex-1"
                      placeholder="short description — what it means / when to apply"
                      value={r.description}
                      onChange={(e) => updateRow(i, "description", e.target.value)}
                    />
                    <button
                      type="button"
                      onClick={() => removeRow(i)}
                      className="mt-2 text-slate-300 hover:text-red-500"
                      title="Remove"
                    >
                      ✕
                    </button>
                  </div>
                ))}
                <button type="button" onClick={addRow} className="text-xs text-blue-600 hover:underline">
                  ＋ Add keyword
                </button>
              </div>
              <span className="mt-1 block text-xs text-slate-400">
                The agent reuses these labels (with their meanings) when they fit, and only invents a
                new tag when none apply. New tags it creates are auto-described.
              </span>
            </div>
            <div className="mt-3 flex items-center gap-3">
              <button onClick={saveDefinition} disabled={saving || !dirty} className="btn-primary">
                {saving ? "Saving…" : "Save definition"}
              </button>
              {!dirty && state.updated_at && <span className="text-xs text-slate-400">Saved</span>}
            </div>
          </div>

          {/* Run */}
          <div className="mb-5 rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="text-sm text-slate-600">
                <span className="font-medium text-slate-800">{state.include_total}</span>{" "}
                {state.include_source === "ai" ? (
                  <span
                    className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800"
                    title="No papers are user-confirmed yet, so extraction uses the LLM's screening suggestions."
                  >
                    AI-labeled Include
                  </span>
                ) : (
                  "Include"
                )}{" "}
                papers · <span className="font-medium text-slate-800">{state.processed_total}</span>{" "}
                processed · <span className="font-medium text-slate-800">{state.unique_tags}</span>{" "}
                unique tags
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => runExtraction(false)}
                  disabled={running || !description.trim() || dirty}
                  className="btn-primary"
                  title={dirty ? "Save the definition first" : ""}
                >
                  {running ? "Extracting…" : "Run extraction"}
                </button>
                <button
                  onClick={() => runExtraction(true)}
                  disabled={running || !description.trim() || dirty}
                  className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"
                  title="Re-extract all Include papers for this dimension"
                >
                  Force re-run
                </button>
              </div>
            </div>
            {result && (
              <div
                className={`mt-3 rounded-md border p-3 text-sm ${
                  result.error || result.failed > 0 || result.processed === 0
                    ? "border-amber-200 bg-amber-50 text-amber-800"
                    : "border-green-200 bg-green-50 text-green-700"
                }`}
              >
                {result.error ? (
                  <p>Error: {result.error}</p>
                ) : (
                  <p>
                    Processed {result.processed} · tagged {result.tagged} · skipped {result.skipped}{" "}
                    (already done) · failed {result.failed}.
                    {result.note && <span className="block text-amber-700 mt-1">{result.note}</span>}
                  </p>
                )}
              </div>
            )}
          </div>

          {/* Tag pool */}
          {state.tag_pool.length > 0 && (
            <div className="mb-5 rounded-lg border border-slate-200 bg-white p-4">
              <h3 className="text-sm font-medium text-slate-700">Tag pool ({state.tag_pool.length})</h3>
              <ul className="mt-3 divide-y divide-slate-100">
                {state.tag_pool.map((t) => (
                  <li key={t.tag} className="flex items-start justify-between gap-4 py-1.5">
                    <div>
                      <span className="text-sm font-medium text-slate-800">{t.tag}</span>
                      {t.description && (
                        <span className="ml-2 text-xs text-slate-500">— {t.description}</span>
                      )}
                    </div>
                    <span className="shrink-0 text-xs text-slate-400">{t.count}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Processed papers with evidence */}
          {papers.length > 0 && (
            <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-3 w-8"></th>
                    <th className="px-4 py-3">Index</th>
                    <th className="px-4 py-3">Title</th>
                    <th className="px-4 py-3">Tags</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {papers.map((p) => {
                    const tags = p.tags || [];
                    const marks = tags.map((t, i) => ({
                      tag: t,
                      evidence: (p.evidence || {})[t] || "",
                      color: colorFor(i),
                    }));
                    const isOpen = expanded === p.index;
                    return (
                      <Fragment key={p.index}>
                        <tr className="cursor-pointer hover:bg-slate-50" onClick={() => setExpanded(isOpen ? null : p.index)}>
                          <td className="px-4 py-3 align-top text-slate-400">{isOpen ? "▾" : "▸"}</td>
                          <td className="px-4 py-3 align-top text-slate-500">{p.index}</td>
                          <td className="px-4 py-3 align-top text-slate-800">{p.title}</td>
                          <td className="px-4 py-3 align-top">
                            <div className="flex flex-wrap gap-1">
                              {tags.length === 0 ? (
                                <span className="text-xs text-slate-400">— none —</span>
                              ) : (
                                tags.map((t, i) => (
                                  <span
                                    key={t}
                                    title={(state.tag_descriptions || {})[t] || ""}
                                    className="rounded px-2 py-0.5 text-xs text-slate-800"
                                    style={{ backgroundColor: colorFor(i) }}
                                  >
                                    {t}
                                  </span>
                                ))
                              )}
                            </div>
                          </td>
                        </tr>
                        {isOpen && (
                          <tr className="bg-slate-50/60">
                            <td></td>
                            <td colSpan={3} className="px-4 py-4">
                              {tags.length > 0 && (
                                <ul className="mb-3 space-y-1.5">
                                  {marks.map((m) => (
                                    <li key={m.tag} className="text-sm">
                                      <span className="mr-2 rounded px-2 py-0.5 text-xs text-slate-800" style={{ backgroundColor: m.color }}>
                                        {m.tag}
                                      </span>
                                      {m.evidence ? (
                                        <span className="text-slate-600">“{m.evidence}”</span>
                                      ) : (
                                        <span className="text-slate-400 text-xs">(no evidence quote returned)</span>
                                      )}
                                    </li>
                                  ))}
                                </ul>
                              )}
                              <div className="rounded-md border border-slate-200 bg-white p-3 text-sm leading-relaxed text-slate-700">
                                <p className="mb-1 text-xs font-medium text-slate-400">Abstract</p>
                                {p.abstract ? (
                                  highlightSegments(p.abstract, marks).map((s, i) =>
                                    s.color ? (
                                      <mark key={i} title={s.tag} style={{ backgroundColor: s.color, padding: "0 1px" }}>
                                        {s.text}
                                      </mark>
                                    ) : (
                                      <span key={i}>{s.text}</span>
                                    )
                                  )
                                ) : (
                                  <span className="text-slate-400">(no abstract stored)</span>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
