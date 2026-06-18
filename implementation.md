# Systematic Literature Review (SLR) Agentic Workflow

This document is the implementation plan and "as-built" record for the
semi-automated agentic workflow for a systematic literature review process.

**Status legend:** ✅ Implemented · 🟡 Partially implemented · ⏳ Planned (not yet built)

## Architecture Decisions
- **Web Framework**: FastAPI (Python backend) + React frontend. ✅
- **Frontend stack**: **Vite + React (JavaScript) + Tailwind CSS**, with
  `react-router-dom` for routing. JavaScript (not TypeScript) was chosen for
  simplicity. ✅
- **Agent Framework**: **LangChain v1** for all agent implementations, giving a
  unified interface across providers (DeepSeek active by default; OpenAI,
  Anthropic, Google supported). Pinned in `requirements.txt`:
  `langchain==1.3.9`, `langchain-core==1.4.7`, `langchain-openai==1.3.2`,
  `langchain-anthropic==1.4.6`, `langchain-google-genai==4.2.5`. ✅
- **Backend layout**: code lives in a `backend/` package (`main.py`, `parsers.py`,
  `ingestion.py`, `dedup_service.py`, `storage.py`, `models.py`, `paths.py`);
  agents live in `agents/` at the project root. ✅
- **Data Format (Papers)**: one JSON file per database (e.g. `ieee.json`). ✅
- **Data Format (Metadata)**: JSON at `context/metadata.json`, storing the raw
  keyword string alongside the compiled regex patterns produced by the
  Highlighting Agent. ✅
- **Python Environment**: the existing `.venv`. All backend commands use
  `./.venv/bin/python` and `./.venv/bin/pip`. ✅
- **Node**: Node.js 18+ required by Vite 5; Node 24 LTS (npm 11) recommended.
  `frontend/package.json` declares `engines` `node >=20`, `npm >=10`. ✅

## 1. Project Setup and Environment ✅
- **Folder structure** (built):
  - `context/` — `metadata.json` (title, research questions, keyword string,
    inclusion/exclusion criteria, databases, and compiled highlight rules).
  - `agents/` — `keyword_highlighter.py`, `deduplication.py`,
    `abstract_title_screening.py` (Phase 3 stub), plus `llm.py` (shared
    LangChain model factory with graceful fallback when no key is set).
  - `backend/` — FastAPI app and services.
  - `frontend/` — Vite/React/Tailwind app.
  - `data/01_raw_paper_list/`, `data/02_deduplication/` — per-stage outputs.
- **Environment variables**: `.env` and `.env.example` hold provider API keys
  plus `LLM_PROVIDER` and DeepSeek base-url/model. DeepSeek is the active key. ✅
- **Global UI**:
  - **Dashboard / Overview** ✅ — pipeline progress (Ingestion → Deduplication →
    Screening), total papers, highlight-term count, and per-database status cards.
  - **Navigation sidebar** ✅ — Dashboard, Context Configuration, Database
    Management, Data Ingestion, Deduplication.

## 2. Phase 1: Context & Data Ingestion ✅
- **Highlighting Agent** (`agents/keyword_highlighter.py`) ✅ — invoked when the
  Context Configuration is saved with a changed keyword string. Extracts terms
  from complex Boolean queries (quoted phrases, wildcards like `secur*`,
  operators, field tags) and compiles **deterministic regex** locally. LangChain
  (DeepSeek) is used to assist term extraction when a key is configured, with a
  fully deterministic fallback so highlighting always works offline. Compiled
  rules (`terms`, `patterns`, `source`, `compiled_at`) are written to
  `metadata.json`.
- **Data Parsers** (`backend/parsers.py`) ✅ — normalize **RIS, CSV, and BibTeX**
  exports into a uniform schema (BibTeX added beyond the original RIS/CSV plan).
  CSV uses header aliasing to handle Scopus/WoS/IEEE column variations.
- **Combining files** ✅ — multiple uploads for one database are appended into
  that database's single JSON file.
- **Indexing** ✅ — each paper gets a sequential, traceable index per database
  (`IEEE-001`, `ACM-042`, …); appends continue the existing sequence.
- **Storage** ✅ — uniform JSON saved to `data/01_raw_paper_list/<db_id>.json`.

  Uniform paper schema:
  `index, database, database_id, title, authors[], year, abstract, keywords[],
  doi, venue, url, source_file, raw{}`.

- **Web UI pages**:
  - **Context Configuration Page** ✅ — form for Title, **Research Questions
    (single free-text field)**, Boolean keyword string, and inclusion/exclusion
    criteria (one per line). Saving persists to `metadata.json` and triggers the
    Highlighting Agent; a live panel previews the compiled highlight terms.
    > Note: a structured RQ editor (question + rationale + taxonomy) was built and
    > then reverted to a plain free-text field per the author's preference. The
    > backend coerces any legacy structured/list RQ data into text on load.
  - **Database Management Page** ✅ — table of configured sources (defaults:
    IEEE Xplore, ACM Digital Library, Scopus, Web of Science) with priority,
    prefix, paper count, and index range. Users can add custom databases (auto
    slug + prefix) and remove them. Each row has a **"Check Raw paper list"**
    button.
  - **Per-database Raw Paper List** ✅ (`/databases/:id`) — the raw ingested
    papers for one database in a **paginated, searchable** table (columns: index,
    full untruncated title, authors, year, DOI). A single search box matches
    **any field** (title, index, DOI, author, year, venue, keyword, abstract,
    source) with multi-term AND matching. Rows expand to show abstract, keywords,
    venue, and URL. Pagination has a per-page selector (10/20/50/100, **default
    20**).
  - **Data Ingestion (Upload) Page** ✅ — drag-and-drop dropzone, target-database
    selector, multi-file upload, per-file parse results, and a live table of
    ingested databases with counts and index ranges.
  - **LLM Agent Configuration Page** ⏳ — *planned, not yet built.* Will map which
    provider/model each agent uses (e.g. Highlighting vs Screening), saved to
    `metadata.json` so the backend routes LangChain calls accordingly. The shared
    factory `agents/llm.py` already supports per-provider selection via
    `LLM_PROVIDER`; the per-agent UI/mapping is the remaining work.

- **Phase 1 API**: `GET/PUT /api/context`, `POST /api/context/recompute-highlights`,
  `GET/POST /api/databases`, `DELETE /api/databases/{id}`,
  `POST /api/ingest/{id}`, `GET/DELETE /api/papers/{id}`, `GET /api/dashboard`.

## 3. Phase 2: Deduplication System ✅
- **Deduplication Agent** (`agents/deduplication.py`) ✅ — deterministic matching:
  - **DOI match** (normalized) first; then **normalized-title match** guarded by
    a compatible-year check (equal years, or one missing) to limit false positives.
  - **Intra- and inter-database** dedup in a single pass over databases in
    **priority order** (default IEEE → ACM → Scopus → Web of Science). The first
    occurrence is kept as the original; later matches are flagged as duplicates of
    it (intra-database duplicates fall on the matrix diagonal).
- **Service & persistence** (`backend/dedup_service.py`) ✅ — writes to
  `data/02_deduplication/`: `deduplicated.json` (final kept set), `report.json`
  (matrix + summary), and `dedup_state.json` (full annotated list, the source of
  truth that supports restore). The raw `01_raw_paper_list/` files are never
  modified.
- **Traceability matrix** ✅ — per database: total, duplicates, unique, and a
  breakdown of which source database each duplicate matched against.
- **Restore / re-remove** ✅ — duplicates can be restored (or re-removed); the
  kept dataset and report are rewritten live, preserving traceability.
- **Web UI pages**:
  - **Deduplication Review Page** ✅:
    - **Metrics view** — summary stats (input, kept, removed, restored) and the
      traceability matrix.
    - **Removed duplicates list** — the removed paper's title and the matched
      original's title shown **side by side, untruncated**. Clicking a row expands
      a dropdown comparing the two papers **side by side** (index, database, year,
      authors, DOI, abstract, keywords). Each row has a **Restore** button; match
      type (doi/title) is shown as a badge. **Paginated** with a per-page selector
      (default 20).
  - **Deduplicated List Page** ✅ (`/deduplication/papers`) — the final kept
    papers in the same paginated/searchable `PaperTable`, reached via a **"View
    deduplicated list"** button on the Deduplication page.
- **Dashboard wiring** ✅ — the Deduplication stage shows kept/removed counts and
  marks itself done once a run exists.
- **Phase 2 API**: `POST /api/deduplicate`, `GET /api/deduplication`,
  `POST /api/deduplication/restore/{index}`,
  `POST /api/deduplication/remove/{index}`, `GET /api/deduplication/papers`.

### Shared UI: `components/PaperTable.jsx`
A reusable, paginated, searchable table with expandable detail rows powers both
the raw per-database list and the deduplicated list (search across all fields;
per-page selector defaulting to 20).

## 4. Phase 3: Screening Interface & LLM Agent ⏳ (Planned)
- **Agent** (`agents/abstract_title_screening.py`, currently a stub) — compare
  title, abstract, and keywords against the criteria; produce reasoning and a
  suggested label (Include/Exclude/Maybe) via LangChain output parsers. Save
  progress and final decisions to `data/03_abstract_title_screening/`.
- **Abstract & Title Screening Page**:
  - **Side-by-side split view** — left panel shows `index`, `Title`, `Abstract`,
    `Year`, and `Keywords`; right panel shows inclusion/exclusion criteria.
  - **Keyword highlighting** — dynamically highlights matching text using the
    deterministic regex compiled by the Highlighting Agent.
  - **Action area** — read-only LLM reasoning, a user-comment text area, and
    `[Include] [Exclude] [Maybe]` buttons.
  - **Navigation** — "Next Paper" and "Previous Paper".
- **Screened Papers Review Page**:
  - **List view** — Title, Author, Year, Abstract, Label, LLM Reasoning, User
    Comment.
  - **Filtering panel** — multi-select filters to slice the dataset by:
    - **Modification trail**: LLM Labeled, User Confirmed, User Modified.
    - **Screen labels**: Include, Exclude, Maybe.
  - **Color coding** — row tinted by label (green Include, red Exclude, yellow
    Maybe).
  - **Inline editing** — quick action buttons to change the label seamlessly.

## Verification Plan
- **Done so far**:
  - RIS/CSV/BibTeX parsing verified against sample exports (authors, year,
    keywords, DOI extraction). ✅
  - Highlighting Agent verified to extract terms and compile working regex
    (deterministic path), including wildcards. ✅
  - Ingestion verified: combine + continued sequential indexing + summaries. ✅
  - Deduplication verified with controlled cross-database cases: DOI match,
    title+year match, intra-database duplicate (diagonal), and a correctly *kept*
    title match with mismatched years; matrix, restore flow, and dashboard all
    correct. ✅
  - Frontend production build passes; pagination slice logic checked. ✅
  - LangChain v1 packages verified to install and build a chain. ✅
- **Process note**: verification must run against an **isolated temporary data
  directory**, never the live `data/` folder.
- **Remaining (Phase 3)**: dry-run the screening interface with the LangChain
  DeepSeek agent to verify label suggestions, filtering, and inline editing.
