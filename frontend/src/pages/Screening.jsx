import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { paperMatches } from "../paperSearch.js";
import { ErrorBox } from "./Dashboard.jsx";
import Highlight from "../components/Highlight.jsx";
import { ScreeningFilters, matchesScreeningFilters } from "../components/screeningFilters.jsx";

const LABELS = ["Include", "Exclude", "Maybe"];
const LABEL_STYLES = {
  Include: "bg-green-100 text-green-700 border-green-300",
  Exclude: "bg-red-100 text-red-700 border-red-300",
  Maybe: "bg-amber-100 text-amber-700 border-amber-300",
};
const STATUS_LABEL = {
  pending: "Pending",
  llm_labeled: "AI labeled",
  user_confirmed: "User confirmed",
  user_modified: "User modified",
};

export default function Screening() {
  const [papers, setPapers] = useState(null);
  const [context, setContext] = useState(null);
  const [hasSource, setHasSource] = useState(true);
  const [error, setError] = useState(null);
  const [pos, setPos] = useState(0);
  const [comment, setComment] = useState("");
  const [suggesting, setSuggesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [batch, setBatch] = useState(null); // { done, total } while running
  const [labelFilter, setLabelFilter] = useState(new Set());
  const [statusFilter, setStatusFilter] = useState(new Set());
  const [query, setQuery] = useState("");
  const stopRef = useRef(false);
  const [searchParams] = useSearchParams();
  const focusIndex = searchParams.get("paper");
  const appliedFocus = useRef(false);

  useEffect(() => {
    Promise.all([api.getScreening(), api.getContext()])
      .then(([s, c]) => {
        setHasSource(s.has_source);
        setPapers(s.papers);
        setContext(c);
      })
      .catch((e) => setError(e.message));
  }, []);

  const patterns = context?.highlight_rules?.patterns || [];

  // The subset to screen, narrowed by the filter; navigation walks this list.
  const filtered = useMemo(
    () =>
      (papers || []).filter(
        (p) => matchesScreeningFilters(p, labelFilter, statusFilter) && paperMatches(p, query)
      ),
    [papers, labelFilter, statusFilter, query]
  );

  // Reset to the first paper whenever the filter changes.
  useEffect(() => {
    setPos(0);
  }, [labelFilter, statusFilter, query]);

  // If navigated here with ?paper=INDEX (e.g. from Screened Review), jump to it.
  useEffect(() => {
    if (!papers || !focusIndex || appliedFocus.current) return;
    const i = filtered.findIndex((p) => p.index === focusIndex);
    if (i >= 0) {
      setPos(i);
      appliedFocus.current = true;
    }
  }, [papers, filtered, focusIndex]);

  const safePos = Math.min(pos, Math.max(filtered.length - 1, 0));
  const current = filtered[safePos];

  useEffect(() => {
    setComment(current?.user_comment || "");
  }, [safePos, current?.index]);

  const decidedCount = useMemo(
    () => (papers || []).filter((p) => p.label).length,
    [papers]
  );

  if (error) return <ErrorBox message={error} />;
  if (!papers || !context) return <p className="text-slate-500">Loading…</p>;

  if (!hasSource) {
    return (
      <EmptyState
        msg="No deduplicated papers to screen yet."
        hint={
          <>
            Run{" "}
            <Link to="/deduplication" className="text-blue-600 hover:underline">
              deduplication
            </Link>{" "}
            first.
          </>
        }
      />
    );
  }
  if (papers.length === 0) {
    return <EmptyState msg="The deduplicated set is empty." />;
  }

  const replace = (rec) =>
    setPapers((prev) => prev.map((p) => (p.index === rec.index ? rec : p)));

  const suggest = async () => {
    setSuggesting(true);
    try {
      const res = await api.suggestScreening(current.index);
      replace(res.record);
      if (!res.available) {
        alert(res.record.llm_reasoning || "AI suggestion unavailable.");
      }
    } catch (e) {
      alert(e.message);
    } finally {
      setSuggesting(false);
    }
  };

  const decide = async (label) => {
    setSaving(true);
    const base = safePos;
    try {
      const rec = await api.labelScreening(current.index, label, comment);
      const stillMatches = matchesScreeningFilters(rec, labelFilter, statusFilter);
      replace(rec);
      // Auto-advance. If a filter now excludes this paper, the next one slides
      // into the same position, so keep the index; otherwise step forward.
      const nextLen = stillMatches ? filtered.length : filtered.length - 1;
      const np = stillMatches ? base + 1 : base;
      setPos(Math.min(Math.max(np, 0), Math.max(nextLen - 1, 0)));
    } catch (e) {
      alert(e.message);
    } finally {
      setSaving(false);
    }
  };

  const go = (delta) => {
    setPos(Math.min(Math.max(safePos + delta, 0), Math.max(filtered.length - 1, 0)));
  };

  const runAll = async () => {
    stopRef.current = false;
    setBatch({ done: 0, total: papers.length });
    try {
      // Drive the chunked backend endpoint until everything has an AI label.
      // eslint-disable-next-line no-constant-condition
      while (true) {
        if (stopRef.current) break;
        const r = await api.suggestBatch(25);
        setBatch({ done: r.total - r.remaining, total: r.total });
        if (r.unavailable) {
          alert(r.message || "AI is unavailable. Check your API key / connection.");
          break;
        }
        if (r.done) break;
      }
      // Refresh the list with the new AI labels.
      const s = await api.getScreening();
      setPapers(s.papers);
    } catch (e) {
      alert(e.message);
    } finally {
      setBatch(null);
    }
  };

  const stopAll = () => {
    stopRef.current = true;
  };

  return (
    <div>
      <header className="mb-4 flex items-end justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-slate-900">Abstract &amp; Title Screening</h2>
          <p className="text-slate-500 mt-1">
            {decidedCount} of {papers.length} screened · {filtered.length} in current filter
          </p>
        </div>
        <div className="flex items-center gap-3">
          {batch ? (
            <div className="flex items-center gap-2">
              <span className="text-sm text-slate-600">
                AI screening… {batch.done}/{batch.total}
              </span>
              <button onClick={stopAll} className="btn-secondary">
                Stop
              </button>
            </div>
          ) : (
            <button onClick={runAll} className="btn-primary">
              Run AI on all
            </button>
          )}
          <Link
            to="/screening/review"
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Screened papers review →
          </Link>
        </div>
      </header>

      {batch && (
        <div className="mb-4 h-2 w-full overflow-hidden rounded bg-slate-200">
          <div
            className="h-full bg-blue-600 transition-all"
            style={{ width: `${batch.total ? (batch.done / batch.total) * 100 : 0}%` }}
          />
        </div>
      )}

      {/* Filter: choose which papers to screen */}
      <div className="mb-3">
        <input
          className="input w-full"
          placeholder="Search papers — title, authors, DOI, year, abstract, keywords…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="mb-4">
        <ScreeningFilters
          labelFilter={labelFilter}
          setLabelFilter={setLabelFilter}
          statusFilter={statusFilter}
          setStatusFilter={setStatusFilter}
          hint="Filter which papers to screen (e.g. only AI-labeled Maybe, or only Pending). Selecting from both lists combines with AND."
        />
      </div>

      {filtered.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-500">
          No papers match the current filter.
        </div>
      ) : (
        <>
          {/* Navigation bar */}
          <div className="mb-4 flex items-center justify-between rounded-lg border border-slate-200 bg-white px-4 py-2">
            <button
              onClick={() => go(-1)}
              disabled={safePos === 0}
              className="btn-secondary disabled:opacity-40"
            >
              ‹ Previous
            </button>
            <div className="text-sm text-slate-600">
              Paper <span className="font-semibold">{safePos + 1}</span> of {filtered.length} ·{" "}
              <span className="font-mono text-xs">{current.index}</span> · {current.database}
              <StatusBadge status={current.status} />
            </div>
            <button
              onClick={() => go(1)}
              disabled={safePos === filtered.length - 1}
              className="btn-secondary disabled:opacity-40"
            >
              Next ›
            </button>
          </div>

      {/* Action area (decision controls at the top) */}
      <div className="mb-4 rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xs font-semibold uppercase text-slate-500">AI suggestion</h3>
          <button onClick={suggest} disabled={suggesting} className="btn-secondary">
            {suggesting ? "Thinking…" : current.llm_label ? "Re-run AI suggestion" : "Get AI suggestion"}
          </button>
        </div>
        <div className="flex items-start gap-3">
          {current.llm_label && (
            <span className={`shrink-0 rounded border px-2 py-0.5 text-xs ${LABEL_STYLES[current.llm_label]}`}>
              {current.llm_label}
            </span>
          )}
          <p className="text-sm text-slate-600 whitespace-pre-wrap min-h-[1.5rem]">
            {current.llm_reasoning || "No AI suggestion yet."}
          </p>
        </div>

        <div className="mt-4">
          <label className="text-xs font-semibold uppercase text-slate-500">Your comment</label>
          <textarea
            className="input mt-1 h-20"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Optional note about your decision…"
          />
        </div>

        <div className="mt-3 flex items-center gap-3">
          {LABELS.map((lab) => (
            <button
              key={lab}
              onClick={() => decide(lab)}
              disabled={saving}
              className={`rounded-md border px-4 py-2 text-sm font-medium disabled:opacity-50 ${
                current.label === lab
                  ? LABEL_STYLES[lab]
                  : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              {lab}
            </button>
          ))}
          {current.label && (
            <span className="text-sm text-slate-500">
              Current: <span className="font-medium">{current.label}</span>
            </span>
          )}
        </div>
      </div>

      {/* Split view */}
      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h3 className="text-xs font-semibold uppercase text-slate-500 mb-2">Paper</h3>
          <p className="text-lg font-semibold text-slate-900 leading-snug">
            <Highlight text={current.title || "(no title)"} patterns={patterns} />
          </p>
          <p className="text-sm text-slate-500 mt-1">
            {(current.authors || []).join(", ")} {current.year ? `· ${current.year}` : ""}
          </p>
          {current.keywords && current.keywords.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1">
              {current.keywords.map((k, i) => (
                <span key={i} className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
                  <Highlight text={k} patterns={patterns} />
                </span>
              ))}
            </div>
          )}
          <div className="mt-3">
            <p className="text-xs font-semibold uppercase text-slate-500 mb-1">Abstract</p>
            <p className="text-sm text-slate-700 whitespace-pre-wrap leading-relaxed">
              <Highlight text={current.abstract || "(no abstract)"} patterns={patterns} />
            </p>
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h3 className="text-xs font-semibold uppercase text-slate-500 mb-2">Criteria</h3>
          <Criteria title="Inclusion" items={context.inclusion_criteria} tone="green" />
          <Criteria title="Exclusion" items={context.exclusion_criteria} tone="red" />
        </div>
      </div>
        </>
      )}
    </div>
  );
}

function StatusBadge({ status }) {
  if (!status || status === "pending") return null;
  const tone =
    status === "user_confirmed"
      ? "bg-green-100 text-green-700"
      : status === "user_modified"
      ? "bg-blue-100 text-blue-700"
      : "bg-slate-100 text-slate-600";
  return <span className={`ml-2 rounded px-2 py-0.5 text-xs ${tone}`}>{STATUS_LABEL[status]}</span>;
}

function Criteria({ title, items, tone }) {
  const head = tone === "green" ? "text-green-600" : "text-red-600";
  const list = Array.isArray(items) ? items : [];
  return (
    <div className="mb-4">
      <p className={`text-xs font-semibold uppercase ${head} mb-1`}>{title}</p>
      {list.length === 0 ? (
        <p className="text-sm text-slate-400">(none defined)</p>
      ) : (
        <ul className="list-disc pl-5 space-y-1 text-sm text-slate-700">
          {list.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function EmptyState({ msg, hint }) {
  return (
    <div>
      <h2 className="text-2xl font-semibold text-slate-900 mb-4">Abstract &amp; Title Screening</h2>
      <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-slate-500">
        <p>{msg}</p>
        {hint && <p className="mt-1">{hint}</p>}
      </div>
    </div>
  );
}
