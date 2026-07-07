import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";

export default function KeywordGrouping() {
  const [dims, setDims] = useState(null);
  const [field, setField] = useState(null);
  const [state, setState] = useState(null);
  const [cats, setCats] = useState(null);
  const [error, setError] = useState(null);
  const [newName, setNewName] = useState("");
  const [newMembers, setNewMembers] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [addingTo, setAddingTo] = useState(null);

  const loadDims = () =>
    api.listTaggingDimensions().then((d) => {
      setDims(d);
      setField((prev) => {
        if (prev && d.dimensions.some((x) => x.field === prev)) return prev;
        return d.dimensions[0]?.field || null;
      });
    }).catch((e) => setError(e.message));

  const loadDim = (f) =>
    Promise.all([api.getTagging(f), api.getTaggingCategories(f)])
      .then(([s, c]) => {
        setState(s);
        setCats(c);
        setNewName("");
        setNewMembers(new Set());
        setAddingTo(null);
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    loadDims();
  }, []);
  useEffect(() => {
    if (field) loadDim(field);
    else {
      setState(null);
      setCats(null);
    }
  }, [field]);

  if (error) return <ErrorBox message={error} />;
  if (!dims) return <p className="text-slate-500">Loading…</p>;

  const toggle = (set, value) => {
    const next = new Set(set);
    next.has(value) ? next.delete(value) : next.add(value);
    return next;
  };

  const createGroup = async () => {
    if (!newName.trim()) return;
    setBusy(true);
    try {
      await api.createTaggingGroup(field, { name: newName.trim(), members: [...newMembers] });
      await loadDim(field);
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  };

  // `group.members` from the categories endpoint are {tag, paper_count} objects;
  // the API expects a plain list of tag strings.
  const memberTags = (group) => group.members.map((m) => (typeof m === "string" ? m : m.tag));

  const removeMember = async (group, tag) => {
    try {
      await api.updateTaggingGroup(field, group.id, {
        members: memberTags(group).filter((t) => t !== tag),
      });
      await loadDim(field);
    } catch (e) {
      alert(e.message);
    }
  };

  const addMembers = async (group, tags) => {
    try {
      await api.updateTaggingGroup(field, group.id, {
        members: [...memberTags(group), ...tags],
      });
      await loadDim(field);
    } catch (e) {
      alert(e.message);
    }
  };

  const renameGroup = async (group) => {
    const name = prompt("Rename category", group.name);
    if (name == null || !name.trim() || name.trim() === group.name) return;
    try {
      await api.updateTaggingGroup(field, group.id, { name: name.trim() });
      await loadDim(field);
    } catch (e) {
      alert(e.message);
    }
  };

  const deleteGroup = async (group) => {
    if (!confirm(`Delete category "${group.name}"? Its tags become standalone again.`)) return;
    try {
      await api.deleteTaggingGroup(field, group.id);
      await loadDim(field);
    } catch (e) {
      alert(e.message);
    }
  };

  const groupedTags = state ? new Set(state.groups.flatMap((g) => g.members)) : new Set();
  const ungrouped = state ? state.tag_pool.filter((t) => !groupedTags.has(t.tag)) : [];

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-semibold text-slate-900">Keyword Grouping</h2>
        <p className="text-slate-500 mt-1">
          Group similar tags into a canonical category (originals are kept, just mapped). Each
          definition is grouped independently.{" "}
          <Link to="/tagging" className="text-blue-600 hover:underline">
            ← Back to extraction
          </Link>
        </p>
      </header>

      {/* Dimension selector */}
      <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white p-3">
        <span className="text-sm font-medium text-slate-600">Definition:</span>
        {dims.dimensions.length > 0 ? (
          <select className="input max-w-xs" value={field || ""} onChange={(e) => setField(e.target.value)}>
            {dims.dimensions.map((d) => (
              <option key={d.field} value={d.field}>
                {d.name} ({d.field})
              </option>
            ))}
          </select>
        ) : (
          <span className="text-sm text-slate-400">
            No definitions yet —{" "}
            <Link to="/tagging" className="text-blue-600 hover:underline">
              create one on the extraction page
            </Link>
            .
          </span>
        )}
      </div>

      {field && state && cats && (
        <>
          {state.tag_pool.length === 0 ? (
            <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-500">
              No tags yet for this definition. Run extraction first on the{" "}
              <Link to="/tagging" className="text-blue-600 hover:underline">
                Keyword Extraction
              </Link>{" "}
              page.
            </div>
          ) : (
            <>
              {/* Create category */}
              <div className="mb-5 rounded-lg border border-slate-200 bg-white p-4">
                <h3 className="text-sm font-medium text-slate-700">New category</h3>
                <input
                  className="input mt-3"
                  placeholder="Category name (e.g. product search)"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                />
                <p className="mt-3 text-xs font-medium text-slate-500">
                  Select tags to map into it ({newMembers.size} selected)
                </p>
                <div className="mt-2 flex max-h-40 flex-wrap gap-2 overflow-auto">
                  {ungrouped.length === 0 ? (
                    <span className="text-xs text-slate-400">All tags are already grouped.</span>
                  ) : (
                    ungrouped.map((t) => (
                      <button
                        key={t.tag}
                        onClick={() => setNewMembers((s) => toggle(s, t.tag))}
                        className={`rounded-full px-3 py-1 text-xs ${
                          newMembers.has(t.tag)
                            ? "bg-blue-600 text-white"
                            : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                        }`}
                      >
                        {t.tag} · {t.count}
                      </button>
                    ))
                  )}
                </div>
                <button onClick={createGroup} disabled={busy || !newName.trim()} className="btn-primary mt-3">
                  {busy ? "Creating…" : "Create category"}
                </button>
              </div>

              <div className="mb-3 flex items-baseline justify-between">
                <h3 className="text-sm font-semibold text-slate-700">Categories ({cats.category_total})</h3>
                <span className="text-xs text-slate-400">
                  {cats.processed_total} papers · {cats.unique_tags} unique tags
                </span>
              </div>

              {/* Group categories */}
              <div className="space-y-3">
                {(cats.groups || []).map((c) => (
                  <div key={c.id} className="rounded-lg border border-slate-200 bg-white p-4">
                    <div className="flex items-start justify-between">
                      <div>
                        <span className="text-base font-semibold text-slate-900">{c.name}</span>
                        <span className="ml-2 rounded bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
                          {c.paper_count} papers
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-xs">
                        <button onClick={() => renameGroup(c)} className="text-slate-500 hover:underline">
                          rename
                        </button>
                        <button
                          onClick={() => setAddingTo(addingTo === c.id ? null : c.id)}
                          className="text-slate-500 hover:underline"
                        >
                          add tags
                        </button>
                        <button onClick={() => deleteGroup(c)} className="text-red-600 hover:underline">
                          delete
                        </button>
                      </div>
                    </div>
                    <ul className="mt-3 space-y-1">
                      {c.members.length === 0 ? (
                        <li className="text-xs text-slate-400">No tags mapped yet.</li>
                      ) : (
                        c.members.map((m) => (
                          <li key={m.tag} className="flex items-center justify-between text-sm text-slate-600">
                            <span className="flex items-center gap-2">
                              <button
                                onClick={() => removeMember(c, m.tag)}
                                className="text-slate-300 hover:text-red-500"
                                title="Remove from category"
                              >
                                ✕
                              </button>
                              {m.tag}
                            </span>
                            <span className="text-slate-400">{m.paper_count}</span>
                          </li>
                        ))
                      )}
                    </ul>
                    {addingTo === c.id && (
                      <div className="mt-3 border-t border-slate-100 pt-3">
                        {ungrouped.length === 0 ? (
                          <span className="text-xs text-slate-400">No ungrouped tags to add.</span>
                        ) : (
                          <div className="flex flex-wrap gap-2">
                            {ungrouped.map((t) => (
                              <button
                                key={t.tag}
                                onClick={() => addMembers(c, [t.tag])}
                                className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-700 hover:bg-blue-600 hover:text-white"
                              >
                                + {t.tag} · {t.count}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* Standalone categories */}
              {cats.standalone.length > 0 && (
                <div className="mt-5 rounded-lg border border-slate-200 bg-white p-4">
                  <h3 className="text-sm font-medium text-slate-700">
                    Standalone tags ({cats.standalone.length})
                  </h3>
                  <p className="mt-0.5 text-xs text-slate-400">
                    Not in any category — each counts as its own category.
                  </p>
                  <ul className="mt-3 divide-y divide-slate-100">
                    {cats.standalone.map((s) => (
                      <li key={s.tag} className="flex items-center justify-between py-1.5 text-sm">
                        <span className="text-slate-700">{s.name}</span>
                        <span className="text-slate-400">{s.paper_count}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
