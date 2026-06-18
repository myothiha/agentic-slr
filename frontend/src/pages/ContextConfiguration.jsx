import { useEffect, useState } from "react";
import { api } from "../api.js";
import { ErrorBox } from "./Dashboard.jsx";

// Helpers to convert between a textarea (one item per line) and a list.
const toLines = (arr) => (arr || []).join("\n");
const fromLines = (str) =>
  str
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);

export default function ContextConfiguration() {
  const [form, setForm] = useState(null);
  const [rules, setRules] = useState({ terms: [], source: null });
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .getContext()
      .then((m) => {
        setForm({
          title: m.title || "",
          research_questions: m.research_questions || "",
          keyword_string: m.keyword_string || "",
          inclusion_criteria: toLines(m.inclusion_criteria),
          exclusion_criteria: toLines(m.exclusion_criteria),
        });
        setRules(m.highlight_rules || { terms: [], source: null });
      })
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (!form) return <p className="text-slate-500">Loading…</p>;

  const update = (k, v) => setForm({ ...form, [k]: v });

  const save = async () => {
    setSaving(true);
    setStatus(null);
    try {
      const payload = {
        title: form.title,
        research_questions: form.research_questions,
        keyword_string: form.keyword_string,
        inclusion_criteria: fromLines(form.inclusion_criteria),
        exclusion_criteria: fromLines(form.exclusion_criteria),
      };
      const updated = await api.updateContext(payload);
      setRules(updated.highlight_rules || { terms: [], source: null });
      setStatus("Saved. Highlighting rules recompiled.");
    } catch (e) {
      setStatus(`Error: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const recompute = async () => {
    setStatus(null);
    try {
      const r = await api.recomputeHighlights(true);
      setRules(r);
      setStatus("Highlighting rules recompiled.");
    } catch (e) {
      setStatus(`Error: ${e.message}`);
    }
  };

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-2xl font-semibold text-slate-900">Context Configuration</h2>
        <p className="text-slate-500 mt-1">
          Define the review scope. Saving recompiles keyword highlighting rules.
        </p>
      </header>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2 space-y-5">
          <Field label="Review title">
            <input
              className="input"
              value={form.title}
              onChange={(e) => update("title", e.target.value)}
              placeholder="e.g. Machine Learning for Network Security: A Systematic Review"
            />
          </Field>

          <Field label="Research questions" hint="Free text — paste your RQs and notes">
            <textarea
              className="input h-48"
              value={form.research_questions}
              onChange={(e) => update("research_questions", e.target.value)}
              placeholder={"RQ1: ...\nRQ2: ..."}
            />
          </Field>

          <Field label="Boolean keyword string" hint="Feeds the Highlighting Agent">
            <textarea
              className="input h-28 font-mono text-sm"
              value={form.keyword_string}
              onChange={(e) => update("keyword_string", e.target.value)}
              placeholder={'("machine learning" OR ML) AND (secur* OR privacy)'}
            />
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Inclusion criteria" hint="One per line">
              <textarea
                className="input h-32"
                value={form.inclusion_criteria}
                onChange={(e) => update("inclusion_criteria", e.target.value)}
              />
            </Field>
            <Field label="Exclusion criteria" hint="One per line">
              <textarea
                className="input h-32"
                value={form.exclusion_criteria}
                onChange={(e) => update("exclusion_criteria", e.target.value)}
              />
            </Field>
          </div>

          <div className="flex items-center gap-3">
            <button onClick={save} disabled={saving} className="btn-primary">
              {saving ? "Saving…" : "Save & recompile highlights"}
            </button>
            {status && (
              <span
                className={`text-sm ${
                  status.startsWith("Error") ? "text-red-600" : "text-green-600"
                }`}
              >
                {status}
              </span>
            )}
          </div>
        </div>

        {/* Highlight rules preview */}
        <div>
          <div className="rounded-lg border border-slate-200 bg-white p-4 sticky top-8">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-slate-700">Highlight terms</h3>
              <button onClick={recompute} className="text-xs text-blue-600 hover:underline">
                Recompute
              </button>
            </div>
            <p className="text-xs text-slate-400 mb-3">
              Source: {rules.source || "—"}
              {rules.compiled_at ? ` · ${new Date(rules.compiled_at).toLocaleString()}` : ""}
            </p>
            {rules.terms && rules.terms.length ? (
              <div className="flex flex-wrap gap-2">
                {rules.terms.map((t, i) => (
                  <span
                    key={i}
                    className="rounded bg-yellow-100 px-2 py-0.5 text-xs text-yellow-800 border border-yellow-200"
                  >
                    {t}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-400">
                No terms yet. Enter a keyword string and save.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-sm font-medium text-slate-700">{label}</span>
        {hint && <span className="text-xs text-slate-400">{hint}</span>}
      </div>
      {children}
    </label>
  );
}
