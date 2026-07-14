# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Critical execution rule

Always use the interpreter and pip from the local virtual environment (`.venv`), never the system ones:

- `./.venv/bin/python script.py` (not `python script.py`)
- `./.venv/bin/pip install x` (not `pip install x`)

`project-description.md` and the various `*-plan.md` files hold the author's evolving requirements — consult them when adding features or when you need product context.

## Commands

Backend (run from the project root so `agents` imports resolve):

```bash
./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn backend.main:app --reload --port 8000   # API + docs at :8000/docs
```

Frontend (Node ≥20, from `frontend/`):

```bash
npm install
npm run dev        # Vite dev server on :5173, proxies /api -> :8000 (start backend first)
npm run build
```

Chart export utility: `./.venv/bin/python scripts/export_keyword_charts.py`.

There is no test suite or linter configured.

## Architecture

A web app that semi-automates the Systematic Literature Review (SLR) pipeline: FastAPI backend + React/Vite/Tailwind frontend. Work flows through numbered pipeline stages, each stage reading the previous stage's output and writing its own — earlier outputs are treated as immutable.

**Pipeline order** (mirrors the frontend nav in `frontend/src/App.jsx` and the `data/NN_*` directories in `backend/paths.py`): Context Configuration → Database Management / Data Ingestion → Deduplication → Page Filter → Abstract/Title Screening → Full-Text Extraction → Keyword Extraction/Tagging → Keyword Grouping → Keyword Analysis. Backup & Restore is orthogonal.

**Backend is service-oriented.** `backend/main.py` is a thin FastAPI router (~900 lines of endpoints) that delegates all logic to per-stage service modules: `ingestion.py`, `dedup_service.py`, `page_filter_service.py`, `screening_service.py`, `full_text_service.py`, `tagging_service.py`, `analysis_service.py`, `backup_service.py`. When adding an endpoint, put the logic in the matching service and keep `main.py` a dispatch layer.

**Three cross-cutting foundation modules:**
- `backend/paths.py` — the single source of truth for every filesystem path. All paths derive from `PROJECT_ROOT` (so the app is CWD-independent), and `ensure_dirs()` creates them. Never hardcode a data path elsewhere; add it here.
- `backend/storage.py` — metadata + paper-file I/O. `context/metadata.json` is the central config document (title, research questions, Boolean keyword string, inclusion/exclusion criteria, compiled highlight regex, database list, tagging dimensions).
- `backend/models.py` — Pydantic schemas shared across services (e.g. `Metadata`, `Database`, `HighlightRules`). Note the non-obvious `Database.proxy_suffix`: when set, download URLs are host-rewritten (EZproxy hostname-remapping style, `host.example.org` → `host-example-org.<proxy_suffix>`) for institutional access.

**LLM usage degrades gracefully.** `agents/llm.py` (`get_chat_model()`) is a LangChain factory keyed on the `LLM_PROVIDER` env var (default `deepseek`; also openai/anthropic/google). If the API key is missing/placeholder or the package isn't installed, it returns `None` and every caller falls back to deterministic logic. So each agent (`keyword_highlighter`, `abstract_title_screening`, `keyword_extraction`, `keyword_suggester`, `deduplication`) must work without a key. Deduplication and highlighting in particular are fully deterministic (DOI/normalized-title equality; Boolean-string parsing) — the LLM is only an assist.

**Uniform paper schema.** Ingestion normalizes RIS/CSV/BibTeX/XLSX exports (`parsers.py`) into one record shape with a per-database sequential `index` (e.g. `IEEE-001`). Downstream stages key papers by this `index`. Each stage persists state as JSON under its `data/NN_*` directory (e.g. `dedup_state.json`, `screening_decisions.json`), keeping raw lists in `01_raw_paper_list/` untouched so stages are replayable.

**Frontend** is a React Router SPA. `src/pages/*` are one page per pipeline stage, `src/api.js` wraps the backend, and `src/paperSearch.js` holds shared search logic used across screening/analysis pages.

## Configuration

Copy `.env.example` to `.env`. Relevant vars: `LLM_PROVIDER`, `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` / `DEEPSEEK_BASE_URL` (or the OpenAI/Anthropic/Google equivalents).
