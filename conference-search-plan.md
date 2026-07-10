# Conference Search — Integrated Implementation Plan

A new feature area inside the existing agentic-slr app (FastAPI backend + React/Vite frontend),
under its **own sidebar section with two sub-menus**:

1. **Conference Management** — an editable list of conferences (like Database Management): add /
   edit / remove venues, fetch their accepted papers from DBLP, see the paper count per venue,
   and "Check raw paper list" to view/search a venue's papers.
2. **Keyword Filtering** — define keywords on the page, apply them over the fetched conference
   corpus, and see the list of relevant papers with a **per-venue relevant-paper count shown
   on top of the table**.

> Supersedes the standalone `conf-paper-fetcher/` plans. The methodology (DBLP enumeration, not
> keyword-search) is unchanged; only the packaging moves from a separate service into the app.

---

## 1. Methodological stance (unchanged, and why it matters)

Reliability comes from **enumerating** each venue-year from DBLP (its complete table of contents
under a stable venue key) and filtering **locally**, rather than searching the conferences by
keyword. This is what makes a recall claim defensible and makes next year's review a
re-execution, not a re-search. Invariants that hold across the whole feature:

- The `venue` field of OpenAlex / Semantic Scholar is **never** used to scope. Enumeration is
  DBLP venue-key only; external APIs supply abstracts, never membership.
- A **snapshot** (DBLP access date + exact venue keys + raw responses) is recorded per fetch — the
  reproducibility anchor.
- **Findings of ACL ≠ ACL**; workshops and companion volumes have separate keys and are excluded
  unless a venue explicitly opts in. Each registry entry carries that decision.

---

## 2. Where things live (mirrors existing conventions)

### Backend
```
backend/
├── conference_service.py     # NEW: registry CRUD, DBLP enumeration, abstract enrichment,
│                             #      keyword filtering, per-venue counts
├── dblp_client.py            # NEW: DBLP TOC fetch + parse (stdlib urllib/xml), on-disk cache
├── abstract_sources.py       # NEW: venue-native -> OpenAlex -> S2 cascade + fuzzy matching
├── near_duplicates.py        # NEW: report-only cross-year duplicate candidate detection (§5b)
├── main.py                   # add /api/conferences/* and /api/conference-filter/* routes
├── models.py                 # add ConferenceCreate / ConferenceUpdate / FilterRequest
├── paths.py                  # add CONFERENCE_DIR paths
└── storage.py                # venue paper-list I/O (parallels load_papers/save_papers)
```

### Data (new stage folders, kept separate from the upload pipeline)
```
data/
├── 00c_conference_papers/
│   ├── <venue_id>.json          # enumerated + enriched frame for a venue (e.g. neurips.json)
│   ├── snapshots/<run_id>.json  # manifest: dump date, resolved keys, raw response hashes
│   └── _raw/<venue><year>.xml   # cached raw DBLP TOC responses (the snapshot)
├── 00d_conference_filter/
│   ├── filter_state.json        # current keyword string + compiled regex
│   └── relevant.json            # papers matching the filter + per-venue counts
└── 00e_conference_duplicates/
    └── candidates.json          # report-only near-duplicate pairs for manual review (§5b)
```

Conference papers land here, **not** in `01_raw_paper_list/`, so they stay a distinct feature and
don't silently merge into the upload-based review. (An optional "Send relevant papers to review
pipeline" action can later export `relevant.json` as `01_raw_paper_list/dblp_conf.json` to feed
the existing dedup/screening stages — noted as a follow-up, not part of this build.)

### Venue registry — stored in `context/metadata.json`
Parallels the existing `databases` array. New `conferences` array; **editable** from the
Conference Management page and by hand.

```json
"conferences": [
  { "id": "neurips", "display": "NeurIPS", "dblp_key": "conf/nips",
    "track": "main", "include_workshops": false, "include_companion": false,
    "year_start": 2020, "year_end": 2025,
    "abstract_sources": ["openreview", "openalex", "s2"], "enabled": true },
  { "id": "icml",  "display": "ICML",  "dblp_key": "conf/icml",  "abstract_sources": ["pmlr","openalex","s2"], "year_start": 2020, "year_end": 2025, "enabled": true },
  { "id": "iclr",  "display": "ICLR",  "dblp_key": "conf/iclr",  "abstract_sources": ["openreview","openalex","s2"], "year_start": 2020, "year_end": 2025, "enabled": true },
  { "id": "acl",   "display": "ACL",   "dblp_key": "conf/acl",   "abstract_sources": ["acl_anthology","openalex","s2"], "year_start": 2020, "year_end": 2025, "enabled": true },
  { "id": "emnlp", "display": "EMNLP", "dblp_key": "conf/emnlp", "abstract_sources": ["acl_anthology","openalex","s2"], "year_start": 2020, "year_end": 2025, "enabled": true },
  { "id": "naacl", "display": "NAACL", "dblp_key": "conf/naacl", "abstract_sources": ["acl_anthology","openalex","s2"], "year_start": 2020, "year_end": 2025, "enabled": true },
  { "id": "cvpr",  "display": "CVPR",  "dblp_key": "conf/cvpr",  "abstract_sources": ["cvf","openalex","s2"], "year_start": 2020, "year_end": 2025, "enabled": true },
  { "id": "iccv",  "display": "ICCV",  "dblp_key": "conf/iccv",  "abstract_sources": ["cvf","openalex","s2"], "year_start": 2019, "year_end": 2025, "enabled": true },
  { "id": "eccv",  "display": "ECCV",  "dblp_key": "conf/eccv",  "abstract_sources": ["openalex","s2"], "year_start": 2020, "year_end": 2024, "enabled": true },
  { "id": "aaai",  "display": "AAAI",  "dblp_key": "conf/aaai",  "abstract_sources": ["openalex","s2"], "year_start": 2020, "year_end": 2025, "enabled": true },
  { "id": "ijcai", "display": "IJCAI", "dblp_key": "conf/ijcai", "abstract_sources": ["openalex","s2"], "year_start": 2020, "year_end": 2025, "enabled": true },
  { "id": "kdd",   "display": "KDD",   "dblp_key": "conf/kdd",   "abstract_sources": ["openalex","s2"], "year_start": 2020, "year_end": 2025, "enabled": true },
  { "id": "www",   "display": "WWW (The Web Conf)", "dblp_key": "conf/www", "abstract_sources": ["openalex","s2"], "year_start": 2020, "year_end": 2025, "enabled": true },
  { "id": "sigir", "display": "SIGIR", "dblp_key": "conf/sigir", "abstract_sources": ["openalex","s2"], "year_start": 2020, "year_end": 2025, "enabled": true }
]
```

> The `dblp_key` values are the expected keys but must be **verified per venue-year at fetch time**
> — DBLP occasionally splits a venue across keys, and workshop/companion keys differ from the
> main-track proceedings key. The fetch resolves the venue's stream index first and logs every
> proceedings key it will read, so mis-mappings surface immediately instead of under-counting.

---

## 3. Menu 1 — Conference Management (`/conferences`)

Page `frontend/src/pages/ConferenceManagement.jsx`, modeled on `DatabaseManagement.jsx`.

**Table columns:** Venue · DBLP key · Track · Years · Papers · Last fetched · actions.
**Row actions:** *Fetch papers* (enumerate + enrich for the venue's year range), *Check raw paper
list* (→ `/conferences/:id`, reuses `PaperTable`), *Edit* (display / dblp_key / track / year
range / enabled), *Empty* (clear the venue's fetched papers), *Remove*.
**Add-venue form** at the bottom: display name + DBLP key (+ optional year range) — same shape as
the "Add custom database" form.

**Fetch behavior** (per venue, `POST /api/conferences/{id}/fetch`):
1. Resolve `dblp_key` → yearly proceedings keys for `year_start..year_end` (log them).
2. For each year, fetch the **per-proceedings TOC** as XML — **not** the DBLP search API, which
   paginates and silently truncates. Cache each raw response under `_raw/`.
3. Parse into records (title, authors, year, DOI/ee, dblp key, venue display).
4. Enrich abstracts via the venue's `abstract_sources` cascade (§5).
5. Save `00c_conference_papers/<id>.json` + a snapshot manifest; update `paper_count`.
6. Stream progress/log lines to the page (mirrors how full-text scan reports progress).

**Detail page** `ConferencePapers.jsx` (or reuse `DatabasePapers.jsx` generalized): searchable
`PaperTable` of that venue's fetched papers, with the abstract-match source and confidence shown.

---

## 4. Menu 2 — Keyword Filtering (`/conferences/filter`)

Page `frontend/src/pages/ConferenceFilter.jsx`.

- **Keyword definition on the page.** A Boolean keyword input (its own field, independent of the
  global Context keyword string) plus a "use my Context keywords" shortcut. On submit it is
  compiled to a deterministic regex via the existing `keyword_highlighter` agent — one query
  engine, shared with the rest of the app.
- **Apply filter** (`POST /api/conference-filter`): runs the compiled regex over `title +
  abstract + keywords` of every fetched conference paper across all enabled venues; saves
  `relevant.json` + counts.
- **Per-venue count bar on top of the table** — the primary ask: a summary row/chips above the
  results showing, for each venue, the number of relevant papers (and, alongside, the enumerated
  total), e.g. `NeurIPS 48 / 512 · ICML 37 / 468 · … · Total particulars`. Enumerated is the
  denominator, relevant is post-filter.
- **Results table** — `PaperTable` of the relevant papers with matched terms highlighted
  (`Highlight.jsx`), filterable by venue, each row showing which OR-block(s) it matched.
- Re-applying with a new keyword string just recomputes; nothing is destroyed (exclusion is a
  label, so counts stay recoverable).

---

## 5. Abstract enrichment & matching (`abstract_sources.py`)

Attaches abstracts to enumerated records; never grows or shrinks the enumerated set.

**Cascade, venue-native first** (per registry `abstract_sources`):
1. **Venue-native** — OpenReview (NeurIPS/ICLR), PMLR (ICML), ACL Anthology (ACL family), CVF
   Open Access (CVPR/ICCV). Best for recent proceedings, where OpenAlex/S2 lag by months.
2. **OpenAlex** — polite pool via `mailto=<email>`, no key needed; match on DOI first.
3. **Semantic Scholar** — fallback; needs an API key at volume.

**Matching order & thresholds:**
- DOI equality (normalized) → accept.
- Else fuzzy title: normalize (lowercase, strip LaTeX/markup, fold unicode, strip punctuation,
  collapse whitespace), then token-set / Levenshtein ratio — `≥0.95` auto-accept; `0.85–0.95`
  flagged for manual review (not dropped); `<0.85` retried against the next source.
- Persist `abstract_source` and `match_confidence` per record.

Exact normalized-title equality alone under-matches (LaTeX, unicode, subtitles); the fuzzy band is
what keeps the expected ~5–15% miss rate from turning into dropped papers.

Optional dependency: `rapidfuzz` for speed (`./.venv/bin/pip install rapidfuzz`), with a stdlib
`difflib` fallback so the feature runs without it.

---

## 5b. Near-duplicate candidates — report-only (`near_duplicates.py`)

Because enumeration reads only proceedings venue keys (never the `CoRR`/arXiv stream), the corpus
has no preprint/proceedings pairs to collapse. The one residual case is the **same work appearing
across two conference entries** — a workshop paper later published at the main venue, a
resubmission to a different conference, or a paper re-indexed under two DBLP keys. These are rare
and often *worth seeing* rather than silently merging, so this step **flags candidates for review
and never auto-merges or deletes anything.**

**What it does:**
- Runs after enumeration + enrichment, across all fetched conference papers.
- Pairs are flagged when normalized-title similarity is high **and** author-set overlap is
  substantial — e.g. title token-set / Levenshtein ratio ≥ 0.90 AND Jaccard author overlap ≥ 0.5.
  (Both signals required, to keep same-title-different-work pairs out.)
- Blocks by a cheap key (e.g. first author's normalized surname, or a title-token minhash) so it
  doesn't do a full O(n²) comparison across the whole corpus.
- Writes `data/00e_conference_duplicates/candidates.json`: one entry per candidate pair with both
  records' index/title/venue/year/authors, the title ratio, the author overlap, and a
  `status: "open"` field. No record is modified; counts are unaffected.

**How the user acts on it:** a small "Possible duplicates" panel (on the Conference Management
page, or its own sub-view) lists each pair side by side with a *Keep both* / *Mark as duplicate*
choice. "Mark as duplicate" only sets a flag on the losing record (`duplicate_of: <index>`) and
records the decision — it stays in the data and in the enumerated count, but can be excluded from
the optional export to the review pipeline. Nothing is destructive; every decision is reversible.

**API:** `GET /api/conferences/duplicates` (list candidates) and
`POST /api/conferences/duplicates/{pair_id}` (`{ decision: "keep_both" | "mark_duplicate" }`).

This keeps the enumerate-don't-merge principle intact: the frame stays complete and defensible,
and any de-duplication is an explicit, logged reviewer decision rather than a silent automated one.

---

## 6. API routes (added to `main.py`)

```
GET    /api/conferences                     list venues + paper_count + last_fetched
POST   /api/conferences                     add a venue
PATCH  /api/conferences/{id}                edit display/key/track/years/enabled
DELETE /api/conferences/{id}                remove venue (+ its fetched papers)
POST   /api/conferences/{id}/fetch          enumerate + enrich (streams progress)
GET    /api/conferences/{id}/papers         a venue's fetched papers
DELETE /api/conferences/{id}/papers         empty a venue's fetched papers
GET    /api/conferences/duplicates          list near-duplicate candidate pairs (report-only)
POST   /api/conferences/duplicates/{pair}   record a decision: keep_both | mark_duplicate

GET    /api/conference-filter               current keyword string + last counts
PUT    /api/conference-filter               set keyword string (compiles regex)
POST   /api/conference-filter               run filter -> relevant papers + per-venue counts
```

Pydantic models added to `models.py`: `ConferenceCreate`, `ConferenceUpdate`, `FilterRequest`.
Paths added to `paths.py`: `CONFERENCE_DIR`, `CONFERENCE_RAW_DIR`, `CONFERENCE_FILTER_DIR`
(+ registered in `ensure_dirs`).

---

## 7. Frontend wiring (`App.jsx`)

### 7.1 Grouped sidebar (main menu → indented sub-menus)

The current sidebar is a **flat** list of links. Restructure it into **main-menu groups**, each
with a non-clickable heading and **indented sub-menu items** beneath it. Conference Search becomes
one such group with two children. Proposed grouping of the whole app:

```
Overview
  Dashboard
  Context Configuration
Data Sources
  Database Management
  Data Ingestion
Conference Search          ← new group
  Conference Management    ← indented sub-menu
  Keyword Filtering        ← indented sub-menu
Processing
  Deduplication
  Page Filter
  Abstract/Title Screening
  Screened Review
  Full-Text Extraction
Analysis
  Keyword Extraction
  Keyword Grouping
  Keyword Analysis
System
  Backup & Restore
```

Replace the flat `nav` array with a `navGroups` structure:

```jsx
const navGroups = [
  { heading: "Overview", items: [
    { to: "/", label: "Dashboard", end: true },
    { to: "/context", label: "Context Configuration" },
  ]},
  { heading: "Data Sources", items: [
    { to: "/databases", label: "Database Management" },
    { to: "/ingestion", label: "Data Ingestion" },
  ]},
  { heading: "Conference Search", items: [          // new group
    { to: "/conferences", label: "Conference Management", end: true },
    { to: "/conferences/filter", label: "Keyword Filtering" },
  ]},
  { heading: "Processing", items: [
    { to: "/deduplication", label: "Deduplication" },
    { to: "/page-filter", label: "Page Filter" },
    { to: "/screening", label: "Abstract/Title Screening", end: true },
    { to: "/screening/review", label: "Screened Review" },
    { to: "/full-text", label: "Full-Text Extraction" },
  ]},
  { heading: "Analysis", items: [
    { to: "/tagging", label: "Keyword Extraction", end: true },
    { to: "/tagging/groups", label: "Keyword Grouping" },
    { to: "/analysis", label: "Keyword Analysis" },
  ]},
  { heading: "System", items: [
    { to: "/backup", label: "Backup & Restore" },
  ]},
];
```

`Sidebar()` renders each group as a small uppercase heading followed by its items; sub-menu
`NavLink`s get a left indent + a subtle left border to show grouping. The `end` flags on group
headings that share a path prefix (e.g. `/conferences` vs `/conferences/filter`, `/screening` vs
`/screening/review`) prevent both items highlighting at once:

```jsx
function Sidebar() {
  return (
    <aside className="w-64 shrink-0 bg-slate-900 text-slate-200 min-h-screen p-5">
      <div className="mb-8">
        <h1 className="text-lg font-semibold text-white">Agentic SLR</h1>
        <p className="text-xs text-slate-400 mt-1">Systematic Literature Review</p>
      </div>
      <nav className="space-y-5">
        {navGroups.map((g) => (
          <div key={g.heading}>
            <p className="px-3 mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              {g.heading}
            </p>
            <div className="space-y-1 border-l border-slate-700 ml-3 pl-2">   {/* indent + rule */}
              {g.items.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.end}
                  className={({ isActive }) =>
                    `block rounded-md px-3 py-2 text-sm font-medium transition ${
                      isActive
                        ? "bg-blue-600 text-white"
                        : "text-slate-300 hover:bg-slate-800 hover:text-white"
                    }`
                  }
                >
                  {n.label}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>
    </aside>
  );
}
```

The existing "Pipeline" summary block at the bottom of the sidebar can be removed (the group
headings now convey the same structure) or kept below the groups — cosmetic, either is fine.

> Optional enhancement (not required): make each group **collapsible** by storing an
> open/closed flag per heading in component state and toggling the items' visibility. Left out of
> the base build to keep it simple; the static indented grouping already gives the visual hierarchy.

### 7.2 Routes

```jsx
<Route path="/conferences"        element={<ConferenceManagement />} />
<Route path="/conferences/:id"    element={<ConferencePapers />} />
<Route path="/conferences/filter" element={<ConferenceFilter />} />
```

Note ordering: `/conferences/filter` is a static path and `/conferences/:id` is dynamic; with
React Router v6 exactness this is unambiguous, but keep `filter` reserved so no venue can take the
id `filter`.

### 7.3 API client

New `api.js` methods: `getConferences`, `addConference`, `updateConference`, `deleteConference`,
`fetchConference`, `getConferencePapers`, `getConferenceFilter`, `setConferenceKeywords`,
`runConferenceFilter`. Reuse `PaperTable.jsx` and `Highlight.jsx`.

---

## 8. Traps → mechanisms (checklist)

| Trap | Handled by |
|---|---|
| Venue-string filtering in S2/OpenAlex | DBLP-key enumeration only; APIs used for abstracts (§1, §5) |
| DBLP search-API truncation | Per-proceedings TOC, not `/search/publ/api` (§3) |
| Findings ≠ ACL / workshop bleed-in | Registry `track`/`include_*` flags, separate keys (§2) |
| Under-matching abstracts | Fuzzy band + manual-review interval (§5) |
| Recent-year abstract & DBLP-index lag | Venue-native first; zero/low-count venue-year flagged in fetch log (§3, §5) |
| arXiv/CoRR duplicates | Enumerate proceedings keys only (not CoRR); optional export routes through existing cross-DB dedup |
| Cross-year / re-indexed conference duplicates | Report-only candidate flagging, reviewer decides — never auto-merges (§5b) |
| Reproducibility | Snapshot manifest per fetch: dump date + resolved keys + raw responses (§2) |

---

## 9. Build phases

1. **Backend registry + DBLP enumeration.** `paths.py`, `models.py`, `conference_service.py`,
   `dblp_client.py`; `conferences` array + CRUD routes; `POST /fetch` writing `<venue_id>.json`
   + snapshot. Verify one venue-year count against the published proceedings size.
2. **Abstract enrichment.** `abstract_sources.py` cascade + fuzzy matching; wire into fetch.
3. **Sidebar regroup + Conference Management page.** Refactor `App.jsx` nav from the flat list to
   grouped main-menu/indented sub-menu structure (§7.1); add the Conference Management page +
   detail (`PaperTable`) + routes + `api.js` methods.
4. **Keyword Filtering page** — compile keywords via `keyword_highlighter`, run filter,
   render per-venue count bar + results table.
5. **Near-duplicate candidates** (§5b) — `near_duplicates.py` + routes + a "Possible duplicates"
   review panel. Report-only; no destructive ops.
6. **Verification & polish** (§10). Optional: "Send relevant to review pipeline" export
   (excludes reviewer-marked duplicates).

---

## 10. Verification plan

- **Enumeration completeness:** for one venue-year with a known accepted count (e.g. an ICML year
  from PMLR's index), assert the fetched count equals the published count.
- **No venue-string leakage:** test asserting no code path scopes on an external `venue` field.
- **Fuzzy-match bands:** seeded LaTeX/unicode/subtitle title variants land in accept / review /
  reject bands as expected.
- **Snapshot reproducibility:** re-fetch from cached raw responses reproduces identical
  `<venue_id>.json` and counts.
- **Filter counts:** per-venue relevant counts on the page equal a recomputed ground truth over
  `00c_conference_papers/*.json`.
- **Near-duplicate detection is non-destructive:** seed a known cross-year duplicate pair — it
  appears in `candidates.json`; assert enumerated counts are unchanged before and after, and that
  a `mark_duplicate` decision only sets a flag (record still present).
- **UI parity:** Conference Management behaves like Database Management (add/edit/empty/remove,
  check raw list); Keyword Filtering shows the per-venue count bar above the table.

> Per project rules, all Python runs use the venv: `./.venv/bin/python`, `./.venv/bin/pip`,
> `./.venv/bin/uvicorn backend.main:app --reload`.
