// Shared screening filter logic + UI, used by both the Screening page and the
// Screened Review page so the two stay consistent.
//
// Two lists:
//   1. Label  — Include / Exclude / Maybe / Not screened (matches the effective
//      label = user label if set, otherwise the AI label).
//   2. Status — Pending / AI labeled / User confirmed / User modified.
// Chips within a list combine with OR; the two lists combine with AND.

export const LABELS = ["Include", "Exclude", "Maybe"];

export const STATUSES = [
  ["pending", "Pending"],
  ["llm_labeled", "AI labeled"],
  ["user_confirmed", "User confirmed"],
  ["user_modified", "User modified"],
];

// "User confirmed" also matches "User modified" (a modification is still a user
// decision). "User modified" stays exact.
export function statusMatches(filterKey, status) {
  if (filterKey === "user_confirmed") {
    return status === "user_confirmed" || status === "user_modified";
  }
  return status === filterKey;
}

export function effectiveLabel(p) {
  return p.label || p.llm_label || null;
}

export function matchesScreeningFilters(p, labelFilter, statusFilter) {
  const eff = effectiveLabel(p);
  const labelOk =
    labelFilter.size === 0 ||
    (eff && labelFilter.has(eff)) ||
    (labelFilter.has("__none__") && !eff);
  const statusOk =
    statusFilter.size === 0 ||
    [...statusFilter].some((key) => statusMatches(key, p.status));
  return labelOk && statusOk;
}

function toggle(set, setter, key) {
  const next = new Set(set);
  next.has(key) ? next.delete(key) : next.add(key);
  setter(next);
}

export function FilterGroup({ title, options, selected, onToggle }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-semibold uppercase text-slate-500 w-28 shrink-0">{title}:</span>
      <div className="flex flex-wrap gap-1">
        {options.map(([key, label]) => (
          <button
            key={key}
            onClick={() => onToggle(key)}
            className={`rounded-full border px-3 py-1 text-xs ${
              selected.has(key)
                ? "border-blue-400 bg-blue-50 text-blue-700"
                : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * The two-list filter bar. `right` is an optional slot for extra controls
 * (e.g. a per-page selector). `hint` overrides the default helper text.
 */
export function ScreeningFilters({
  labelFilter,
  setLabelFilter,
  statusFilter,
  setStatusFilter,
  right,
  hint,
}) {
  return (
    <div>
      <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-3">
        <FilterGroup
          title="Label"
          options={[...LABELS.map((l) => [l, l]), ["__none__", "Not screened"]]}
          selected={labelFilter}
          onToggle={(k) => toggle(labelFilter, setLabelFilter, k)}
        />
        <FilterGroup
          title="Status"
          options={STATUSES}
          selected={statusFilter}
          onToggle={(k) => toggle(statusFilter, setStatusFilter, k)}
        />
        <div className="flex flex-wrap items-center gap-4 border-t border-slate-100 pt-3">
          <button
            onClick={() => {
              setLabelFilter(new Set());
              setStatusFilter(new Set());
            }}
            className="text-xs text-slate-500 hover:underline"
          >
            Clear all
          </button>
          {right && <div className="ml-auto flex items-center gap-2">{right}</div>}
        </div>
      </div>
      <p className="mt-2 text-xs text-slate-400">
        {hint ||
          "Pick from either list to filter; selecting from both combines with AND. “User confirmed” also includes “User modified”."}
      </p>
    </div>
  );
}
