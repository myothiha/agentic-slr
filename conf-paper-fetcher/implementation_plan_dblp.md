# Conference Paper Fetcher — Implementation Plan (DBLP-enumeration design)

> Supersedes the earlier `implementation_plan.md`, which queried DBLP with keyword-Boolean
> searches. That approach filters at the source and cannot support a defensible recall claim.
> This plan **enumerates** the venue-year frame from DBLP and filters **locally**, so re-running
> the review is a re-execution rather than a re-search.

---

## 1. Methodological stance (why this design)

The reliability claim for a systematic review over top AI conferences rests on one decision:
**we do not search the conferences, we enumerate them.** DBLP provides, per venue-year, the
complete table of contents of accepted papers under a stable venue key that distinguishes the
main track from workshops and companion volumes. We take that whole list, enrich it with
abstracts, and only then apply the Boolean inclusion filter — over a corpus we control,
in-memory, reproducibly.

Consequences that must hold throughout the implementation:

- **The venue field of Semantic Scholar / OpenAlex is never used as a filter.** It is
  free-text parsed from PDFs (`NeurIPS`, `Neural Information Processing Systems`, `NIPS`,
  `Advances in Neural Information Processing Systems 36` are all distinct strings). Enumeration
  comes from DBLP venue keys only; external APIs are used for abstracts, never for scoping.
- **The snapshot is the reproducible artifact.** Every run records the DBLP dump/access date,
  the exact venue keys, and the raw responses. Full metadata for a decade of the core venues is
  a few tens of MB and is stored verbatim.
- **Findings of ACL is not ACL.** Treated as a distinct, explicitly-labeled venue key. Every
  registry entry carries an explicit main-track / workshop / companion / Findings decision.

---

## 2. Chosen configuration (from review)

| Decision | Choice |
|---|---|
| Integration | **Standalone tool + uniform-schema export.** Runs isolated in `conf-paper-fetcher/`, but writes output conforming to the agentic-slr uniform paper schema so it can be dropped into `data/01_raw_paper_list/` (e.g. `dblp_conf.json`) and picked up by the existing dedup + screening stages. |
| Abstract source | **Venue-native first** (OpenReview / PMLR / ACL Anthology / CVF Open Access), then OpenAlex (polite pool), then Semantic Scholar. Best coverage for recent proceedings. |
| Venues | Core ML + NLP + CV + AI/DM, **editable** via a registry file and the portal. |
| Reporting | Per-venue **enumerated count vs. count remaining after filtering**, plus a run-level PRISMA summary. |

---

## 3. Architecture overview

```
conf-paper-fetcher/
├── registry/
│   └── venues.json          # EDITABLE venue-key registry (see §4)
├── src/
│   ├── enumerate.py         # Stage 1: DBLP TOC -> complete accepted-paper list
│   ├── enrich.py            # Stage 2: venue-native -> OpenAlex -> S2 abstract cascade
│   ├── match.py             # DOI-first then fuzzy-title matching (§6)
│   ├── filter_local.py      # Stage 3: compiled Boolean regex over the corpus (§7)
│   ├── dedup_arxiv.py       # Stage 4: arXiv/CoRR duplicate collapse (§8)
│   ├── schema.py            # uniform-schema mapping + validation
│   ├── snapshot.py          # run manifest: dump date, venue keys, raw responses
│   ├── cache.py             # on-disk cache of every raw API response
│   └── report.py            # per-venue + PRISMA counts (§9)
├── server.py                # stdlib HTTP server: portal + /api/*
├── portal/index.html        # single-page portal (venues, keywords, years, counts table)
├── runs/                    # one timestamped folder per run (snapshot + outputs)
│   └── <run_id>/
│       ├── manifest.json
│       ├── raw/dblp/<venue><year>.xml
│       ├── raw/abstracts/...
│       ├── enumerated.json      # complete frame, pre-filter
│       ├── included.json        # post-filter
│       ├── dblp_conf.json       # uniform-schema export for agentic-slr
│       └── report.json          # counts (§9)
└── README.md
```

Dependencies: Python standard library where feasible (`urllib`, `http.server`, `xml`,
`json`, `difflib`). One optional third party — `rapidfuzz` — for fast fuzzy title matching;
if unavailable the code falls back to stdlib `difflib.SequenceMatcher`. Install via the
project venv per project rules: `./.venv/bin/pip install rapidfuzz`.

---

## 4. Venue registry (editable) — `registry/venues.json`

The single source of truth for scope. Editable by hand or from the portal. Each entry is
explicit about what counts as "the venue" so the enumeration is auditable.

```json
{
  "neurips": {
    "display": "NeurIPS",
    "dblp_key": "conf/nips",
    "track": "main",
    "include_workshops": false,
    "include_companion": false,
    "abstract_sources": ["openreview", "openalex", "s2"],
    "enabled": true
  },
  "icml":   { "display": "ICML",   "dblp_key": "conf/icml",  "track": "main", "abstract_sources": ["pmlr", "openalex", "s2"], "enabled": true },
  "iclr":   { "display": "ICLR",   "dblp_key": "conf/iclr",  "track": "main", "abstract_sources": ["openreview", "openalex", "s2"], "enabled": true },
  "acl":    { "display": "ACL",    "dblp_key": "conf/acl",   "track": "main", "abstract_sources": ["acl_anthology", "openalex", "s2"], "enabled": true },
  "acl_findings": { "display": "ACL Findings", "dblp_key": "conf/acl", "track": "findings", "abstract_sources": ["acl_anthology", "openalex"], "enabled": false },
  "emnlp":  { "display": "EMNLP",  "dblp_key": "conf/emnlp", "track": "main", "abstract_sources": ["acl_anthology", "openalex", "s2"], "enabled": true },
  "naacl":  { "display": "NAACL",  "dblp_key": "conf/naacl", "track": "main", "abstract_sources": ["acl_anthology", "openalex", "s2"], "enabled": true },
  "cvpr":   { "display": "CVPR",   "dblp_key": "conf/cvpr",  "track": "main", "abstract_sources": ["cvf", "openalex", "s2"], "enabled": true },
  "iccv":   { "display": "ICCV",   "dblp_key": "conf/iccv",  "track": "main", "abstract_sources": ["cvf", "openalex", "s2"], "enabled": true },
  "eccv":   { "display": "ECCV",   "dblp_key": "conf/eccv",  "track": "main", "abstract_sources": ["openalex", "s2"], "enabled": true },
  "aaai":   { "display": "AAAI",   "dblp_key": "conf/aaai",  "track": "main", "abstract_sources": ["openalex", "s2"], "enabled": true },
  "ijcai":  { "display": "IJCAI",  "dblp_key": "conf/ijcai", "track": "main", "abstract_sources": ["openalex", "s2"], "enabled": true },
  "kdd":    { "display": "KDD",    "dblp_key": "conf/kdd",   "track": "main", "abstract_sources": ["openalex", "s2"], "enabled": true },
  "www":    { "display": "WWW (The Web Conf)", "dblp_key": "conf/www", "track": "main", "abstract_sources": ["openalex", "s2"], "enabled": true },
  "sigir":  { "display": "SIGIR",  "dblp_key": "conf/sigir", "track": "main", "abstract_sources": ["openalex", "s2"], "enabled": true }
}
```

> **Validation task, not a given:** the `dblp_key` values above are the expected keys but must be
> verified per venue-year at build time — DBLP occasionally splits a venue across keys, and
> the main-track proceedings key can differ from workshop/companion keys in the same year.
> `enumerate.py` fetches the venue's stream index first and logs every proceedings key it will
> read, so mis-mappings surface immediately rather than silently under-counting.

---

## 5. Stage 1 — Enumeration (`enumerate.py`)

**Goal:** the complete list of accepted papers for each enabled venue × year in range.

- **Do not use the DBLP search API** (`/search/publ/api`) for enumeration — it is a paginated
  search index and will silently truncate large proceedings. Use the **per-proceedings table of
  contents**: resolve the venue key to its yearly proceedings key(s) and fetch the TOC as XML/BibTeX
  (`https://dblp.org/db/<dblp_key>/<venue><year>.xml`, with the stream/`bht` index used to
  discover the exact proceedings keys for that year).
- Respect the `track` / `include_workshops` / `include_companion` flags: workshops and companion
  volumes have separate keys and are excluded unless explicitly enabled. Findings is only pulled
  when its dedicated entry is enabled.
- Save every raw TOC response verbatim under `runs/<run_id>/raw/dblp/`. Record the access date in
  `manifest.json`. This is the snapshot.
- Emit `enumerated.json`: one record per paper with DBLP-native fields (title, authors, year,
  DOI if present, dblp key, ee/url, venue display). This is the **denominator** for every count.
- **Rate/politeness:** serial requests with a small delay and on-disk caching; never re-fetch a
  proceedings already cached for the same run. DBLP will 429 on aggressive access.

Known limitation to surface in the report, not hide: **DBLP indexes recent proceedings with a
lag.** For the current year a venue may be partially or not yet indexed. The manifest records the
access date so a re-run after indexing catches up; the report flags any enabled venue-year that
returned zero or suspiciously few records.

---

## 6. Stage 2 — Abstract enrichment & matching (`enrich.py`, `match.py`)

Abstracts are attached to the enumerated records; the enumerated set is never grown or shrunk
here, only annotated.

**Source cascade (venue-native first), per the registry `abstract_sources` order:**

1. **Venue-native** — OpenReview (NeurIPS/ICLR), PMLR (ICML), ACL Anthology (ACL family),
   CVF Open Access (CVPR/ICCV). Best coverage for the newest proceedings, where OpenAlex/S2 lag.
2. **OpenAlex** — polite pool via `mailto=<email>` param, no key required. Match on DOI first.
3. **Semantic Scholar** — fallback; needs an API key at volume.

**Matching (`match.py`)** — order and thresholds:

1. **DOI equality** (normalized, lowercased) — accept.
2. **Fuzzy title** when no DOI or DOI miss: normalize (lowercase, strip LaTeX/markup, fold
   unicode, strip punctuation, collapse whitespace), then token-set / Levenshtein ratio.
   - ratio ≥ 0.95 → auto-accept
   - 0.85 ≤ ratio < 0.95 → **manual-review band**, flagged in the report, not silently dropped
   - < 0.85 → unmatched; retried against the next source in the cascade
3. Persist a per-record `abstract_source` and `match_confidence` for auditability.

Exact normalized-title equality alone under-matches (LaTeX, unicode, subtitles); the fuzzy band
plus the manual-review interval is what keeps the ~5–15% expected miss rate from becoming dropped
papers.

---

## 7. Stage 3 — Local Boolean filter (`filter_local.py`)

- **Reuse the existing query, don't reinvent it.** agentic-slr already compiles the Boolean
  keyword string into deterministic highlight terms + regex via the `keyword_highlighter` agent
  (`context/metadata.json`). This stage imports that compiled regex so the conference filter and
  the rest of the review share one source of truth for the query.
- Apply the regex over `title + abstract + keywords` of each enumerated record.
- Output `included.json` (matched) while retaining the full `enumerated.json` (frame). Nothing is
  deleted — exclusion is a label, so counts are recoverable.
- Each record carries which OR-block(s) it matched, for later PRISMA justification.

---

## 8. Stage 4 — Deduplication (`dedup_arxiv.py` + existing pipeline)

Two distinct dedup concerns:

1. **Within the conference set — arXiv/CoRR duplicates.** The same work can appear as a CoRR
   preprint and a proceedings paper, sometimes retitled. Because we enumerate proceedings keys
   only (not CoRR), intra-set arXiv collisions are limited, but cross-year resubmissions and
   retitles still occur. Collapse on fuzzy-title + author-set overlap; keep the proceedings
   version, record the merge.
2. **Across databases — reuse the existing stage.** The export conforms to the uniform schema and
   lands as `data/01_raw_paper_list/dblp_conf.json`, so the project's existing inter-database
   deduplication (`02_deduplication`, DOI-first then normalized-title with year guard) handles
   overlap between the conference set and the IEEE/ACM/Scopus/WoS exports. No parallel dedup logic
   is built inside the fetcher for the cross-database case.

---

## 9. Reporting — per-venue counts (`report.py`)

Produced every run, shown in the portal and written to `report.json`:

| Venue | Years | Enumerated (frame) | Matched abstract | Included (post-filter) | % included |
|---|---|---|---|---|---|
| NeurIPS | 2020–2025 | … | … | … | … |
| ICML | … | … | … | … | … |
| … | | | | | |
| **Total** | | **N** | **M** | **K** | |

- **Enumerated** is the denominator (Stage 1). **Included** is post-Boolean-filter (Stage 3).
  This directly answers "how many initially, how many left after filtering, per venue."
- Also reported: abstract-match rate per venue, count in the manual-review band, and any
  enabled venue-year that returned zero records (the DBLP-lag flag).

---

## 10. Uniform-schema export (`schema.py`)

Maps each included record to the agentic-slr uniform schema so it drops into the pipeline:

```json
{
  "index": "DBLP-001",
  "database": "DBLP Conferences",
  "database_id": "dblp_conf",
  "title": "...", "authors": ["..."], "year": 2024,
  "abstract": "...", "keywords": ["..."],
  "doi": "...", "venue": "NeurIPS", "url": "...",
  "source_file": "runs/<run_id>/included.json",
  "raw": { "dblp_key": "...", "abstract_source": "...", "match_confidence": 0.97,
            "matched_blocks": ["..."], "run_id": "...", "snapshot_date": "..." }
}
```

Sequential `DBLP-###` indexing matches the existing `IEEE-001` convention.

---

## 11. PRISMA / reproducibility outputs

- `manifest.json` per run: DBLP access date, resolved proceedings keys per venue-year, source
  cascade used, API versions/params, and content hashes of raw responses.
- Counts wired for the PRISMA flow diagram: records identified (enumerated), records after
  dedup, records after local filter, plus a separate line for "additional records identified
  through other methods" — reserved for backward/forward citation chasing from a seed set via the
  Semantic Scholar citation-graph API (supplementary strategy, not part of the enumeration count).
- Re-running with the same registry + year range + a later dump date is the intended way to
  refresh; the manifest makes the delta explicit.

---

## 12. Server & portal

- `server.py` (stdlib `http.server`): serves `portal/index.html` at `/`; `POST /api/run`
  (config → runs the four stages, streams progress/logs); `GET /api/registry` + `POST /api/registry`
  (read/edit venues); `GET /api/runs/<id>/report`; `GET /api/runs/<id>/export` (download
  `dblp_conf.json` / BibTeX); `GET /health`.
- Portal: editable venue table (toggle enabled, edit key/track, add a venue), keyword-block and
  year-range inputs, a run button with live log, and the **per-venue counts table** (enumerated
  vs. included) as the primary result surface, with download buttons.

---

## 13. Traps → mechanisms (checklist)

| Trap | Handled by |
|---|---|
| Venue-string filtering in S2/OpenAlex | Enumeration is DBLP-key only; external APIs used for abstracts, never scoping (§1, §6) |
| Search-API truncation | Per-proceedings TOC, not `/search/publ/api` (§5) |
| arXiv/CoRR duplicates | `dedup_arxiv.py` + existing cross-DB dedup (§8) |
| Findings ≠ ACL | Separate registry entry with explicit `track` (§4) |
| Workshop/companion bleed-in | Registry flags, separate keys excluded by default (§4, §5) |
| Under-matching abstracts | Fuzzy band + manual-review interval, not exact-equality-or-drop (§6) |
| Recent-year abstract/index lag | Venue-native first + DBLP-lag flag in report (§5, §6, §9) |
| OpenReview coverage variance | Never used for enumeration; abstract source only, per registry (§4) |
| Reproducibility | Snapshot manifest: dump date + venue keys + raw responses (§11) |

---

## 14. Build phases

1. **Registry + enumeration.** `venues.json`, `enumerate.py`, `snapshot.py`, `cache.py`.
   Verify keys against a couple of venue-years; confirm `enumerated.json` counts match the
   published proceedings sizes.
2. **Enrichment + matching.** Venue-native adapters (start OpenReview + PMLR + ACL Anthology),
   OpenAlex, S2; `match.py` with the fuzzy band.
3. **Filter + schema + report.** Import compiled regex, `filter_local.py`, `schema.py`,
   `report.py` with per-venue counts.
4. **arXiv dedup + export** into uniform schema; validate ingestion into `data/01_raw_paper_list/`.
5. **Server + portal**; editable venue table and counts UI.

---

## 15. Verification plan

- **Enumeration completeness:** for one venue-year with a known accepted-paper count
  (e.g. an ICML year from PMLR's own index), assert `enumerated.json` count == published count.
- **No venue-string leakage:** unit test asserting no code path filters on an external `venue`
  field.
- **Fuzzy-match band:** seeded titles with LaTeX/unicode/subtitle variants land in the expected
  accept / review / reject bands.
- **Snapshot integrity:** re-running from cached raw responses reproduces identical
  `included.json` and counts (byte-stable given same registry + range).
- **Pipeline handoff:** `dblp_conf.json` validates against the uniform schema and is picked up by
  the existing dedup stage.
- **Portability:** copy `conf-paper-fetcher/` outside the repo and run end-to-end.
