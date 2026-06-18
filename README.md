# agentic-slr

Agentic workflow to semi-automate the Systematic Literature Review (SLR) process.

A web app (FastAPI backend + React/Vite frontend) that walks a review through its
pipeline. **Phase 1** (this milestone) covers context configuration, database
management, and data ingestion.

## Project layout

```
agentic-slr/
├── context/                 # metadata.json: title, RQs, criteria, keyword rules, databases
├── agents/                  # LangChain-powered agents
│   ├── keyword_highlighter.py   # Boolean keyword string -> highlight terms + regex
│   ├── deduplication.py         # Phase 2 (stub)
│   ├── abstract_title_screening.py  # Phase 3 (stub)
│   └── llm.py                   # shared LangChain model factory (DeepSeek default)
├── backend/                 # FastAPI app
│   ├── main.py                  # API routes
│   ├── parsers.py               # RIS / CSV / BibTeX -> uniform records
│   ├── ingestion.py             # combine files, sequential indexing, save
│   ├── storage.py               # metadata + paper-file I/O
│   ├── models.py / paths.py
├── data/
│   ├── 01_raw_paper_list/   # one JSON per database (e.g. ieee.json)
│   └── 02_deduplication/    # deduplicated.json, report.json, dedup_state.json
├── frontend/                # Vite + React + Tailwind
├── requirements.txt
└── .env / .env.example
```

## Setup

### 1. Backend (Python, uses the existing `.venv`)

```bash
./.venv/bin/pip install -r requirements.txt
```

Set your API key in `.env` (DeepSeek is the default provider):

```env
DEEPSEEK_API_KEY=sk-...
LLM_PROVIDER=deepseek
```

> The highlighting agent works **without** an API key too — it falls back to a
> deterministic keyword parser. The key only enables LLM-assisted term extraction
> for complex Boolean strings.

Run the API (from the project root, so `agents` imports resolve):

```bash
./.venv/bin/uvicorn backend.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### 2. Frontend (Node 18+)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api` to the backend on
port 8000, so start the backend first.

## What Phase 1 does

- **Context Configuration** — title, research questions, Boolean keyword string,
  inclusion/exclusion criteria. Saving triggers the Highlighting Agent, which
  compiles the keyword string into deterministic highlight terms + regex stored
  in `context/metadata.json`.
- **Database Management** — view/add/remove data sources. Defaults: IEEE Xplore,
  ACM Digital Library, Scopus, Web of Science. Each database has a prefix used
  for indexing.
- **Data Ingestion** — upload one or more RIS/CSV/BibTeX exports per database.
  Files are parsed into a uniform schema, combined, and each paper gets a
  sequential index (e.g. `IEEE-001`). Results are saved to
  `data/01_raw_paper_list/<database_id>.json`.
- **Dashboard** — pipeline progress, total papers, and per-database counts and
  index ranges.

### Uniform paper schema

```json
{
  "index": "IEEE-001",
  "database": "IEEE Xplore",
  "database_id": "ieee",
  "title": "...",
  "authors": ["..."],
  "year": 2021,
  "abstract": "...",
  "keywords": ["..."],
  "doi": "...",
  "venue": "...",
  "url": "...",
  "source_file": "export.ris",
  "raw": { }
}
```

## Phase 2 — Deduplication

- **Deduplication** page — runs intra- and inter-database deduplication in
  priority order (IEEE → ACM → Scopus → Web of Science by default). Matching is
  deterministic: DOI equality first, then normalized-title equality with a
  compatible-year guard.
- **Traceability matrix** — shows, per database, how many papers were duplicates
  and which source database each matched (the diagonal = intra-database duplicates).
- **Review list** — every removed duplicate with its matched original and match
  type, each with a **Restore** button. Restores are tracked and update the kept
  dataset live.
- Outputs are written to `data/02_deduplication/` (`deduplicated.json`,
  `report.json`, `dedup_state.json`) — the raw lists in `01_raw_paper_list/` are
  never modified.

## Roadmap

- **Phase 3** — Abstract/Title screening interface with the LangChain screening agent.
