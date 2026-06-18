"""FastAPI application for the Agentic SLR workflow — Phase 1.

Endpoints
---------
  GET  /api/health
  GET  /api/context                 -> full metadata
  PUT  /api/context                 -> update context fields, run highlighter
  POST /api/context/recompute-highlights
  GET  /api/databases               -> databases + paper counts / index ranges
  POST /api/databases               -> add a custom database
  DELETE /api/databases/{db_id}     -> remove a database (and its papers)
  POST /api/ingest/{db_id}          -> upload + ingest files
  GET  /api/papers/{db_id}          -> list papers for a database
  DELETE /api/papers/{db_id}        -> clear a database's papers
  GET  /api/dashboard               -> high-level pipeline overview
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Ensure the project root is importable so `agents` resolves when run from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel

from agents.keyword_highlighter import update_metadata_highlighting

from . import backup_service, dedup_service, ingestion, screening_service, storage
from .models import ContextUpdate, DatabaseCreate, ScreeningLabel

app = FastAPI(title="Agentic SLR API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "db"


def _prefix_from(name: str) -> str:
    letters = re.sub(r"[^A-Za-z0-9]", "", name).upper()
    return (letters[:4] or "DB")


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health():
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# Context configuration
# --------------------------------------------------------------------------- #
@app.get("/api/context")
def get_context():
    return storage.load_metadata()


@app.put("/api/context")
def update_context(payload: ContextUpdate):
    metadata = storage.load_metadata()
    data = payload.model_dump(exclude_unset=True)
    keyword_changed = "keyword_string" in data and data["keyword_string"] != metadata.get(
        "keyword_string"
    )
    for key, value in data.items():
        metadata[key] = value
    # Trigger the Highlighting Agent whenever the keyword string changes.
    if keyword_changed:
        update_metadata_highlighting(metadata, use_llm=True)
    storage.save_metadata(metadata)
    return metadata


@app.post("/api/context/recompute-highlights")
def recompute_highlights(use_llm: bool = True):
    metadata = storage.load_metadata()
    update_metadata_highlighting(metadata, use_llm=use_llm)
    storage.save_metadata(metadata)
    return metadata["highlight_rules"]


# --------------------------------------------------------------------------- #
# Database management
# --------------------------------------------------------------------------- #
@app.get("/api/databases")
def list_databases():
    return ingestion.database_summaries()


@app.post("/api/databases")
def add_database(payload: DatabaseCreate):
    metadata = storage.load_metadata()
    db_id = _slugify(payload.name)
    if any(d["id"] == db_id for d in metadata["databases"]):
        raise HTTPException(status_code=409, detail="A database with this name already exists.")
    priority = payload.priority
    if priority is None:
        priority = max((d.get("priority", 0) for d in metadata["databases"]), default=0) + 1
    new_db = {
        "id": db_id,
        "name": payload.name.strip(),
        "prefix": (payload.prefix or _prefix_from(payload.name)).upper(),
        "priority": priority,
    }
    metadata["databases"].append(new_db)
    storage.save_metadata(metadata)
    return new_db


@app.delete("/api/databases/{db_id}")
def delete_database(db_id: str):
    metadata = storage.load_metadata()
    before = len(metadata["databases"])
    metadata["databases"] = [d for d in metadata["databases"] if d["id"] != db_id]
    if len(metadata["databases"]) == before:
        raise HTTPException(status_code=404, detail="Database not found.")
    storage.save_metadata(metadata)
    storage.delete_papers(db_id)
    return {"deleted": db_id}


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #
@app.post("/api/ingest/{db_id}")
async def ingest(db_id: str, files: list[UploadFile] = File(...)):
    metadata = storage.load_metadata()
    if not any(d["id"] == db_id for d in metadata["databases"]):
        raise HTTPException(status_code=404, detail="Database not found.")
    payload: list[tuple[str, bytes]] = []
    for f in files:
        content = await f.read()
        payload.append((f.filename or "upload", content))
    try:
        return ingestion.ingest_files(db_id, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/papers/{db_id}")
def get_papers(db_id: str):
    return storage.load_papers(db_id)


@app.delete("/api/papers/{db_id}")
def clear_papers(db_id: str):
    storage.delete_papers(db_id)
    return {"cleared": db_id}


# --------------------------------------------------------------------------- #
# Deduplication (Phase 2)
# --------------------------------------------------------------------------- #
class DedupRunRequest(BaseModel):
    priority_order: list[str] | None = None


@app.post("/api/deduplicate")
def run_deduplication_endpoint(payload: DedupRunRequest | None = None):
    order = payload.priority_order if payload else None
    return dedup_service.run(order)


@app.get("/api/deduplication")
def get_deduplication():
    return dedup_service.get_report()


@app.post("/api/deduplication/restore/{index}")
def restore_duplicate(index: str):
    try:
        return dedup_service.set_status(index, "restored")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/deduplication/remove/{index}")
def remove_duplicate(index: str):
    try:
        return dedup_service.set_status(index, "duplicate")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/deduplication/papers")
def get_kept_papers():
    return dedup_service.kept_papers()


# --------------------------------------------------------------------------- #
# Screening (Phase 3)
# --------------------------------------------------------------------------- #
@app.get("/api/screening")
def get_screening():
    return screening_service.get_screening()


@app.post("/api/screening/suggest/{index}")
def screening_suggest(index: str):
    try:
        return screening_service.suggest(index)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/screening/suggest-batch")
def screening_suggest_batch(limit: int = 25):
    return screening_service.suggest_batch(limit)


@app.post("/api/screening/label/{index}")
def screening_label(index: str, payload: ScreeningLabel):
    try:
        return screening_service.set_label(index, payload.label, payload.comment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/screening/comment/{index}")
def screening_comment(index: str, payload: ScreeningLabel):
    try:
        return screening_service.set_comment(index, payload.comment or "")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/screening/reset/{index}")
def screening_reset(index: str):
    try:
        return screening_service.reset(index)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --------------------------------------------------------------------------- #
# Backup & Restore
# --------------------------------------------------------------------------- #
@app.get("/api/backups")
def list_backups():
    return backup_service.list_backups()


@app.post("/api/backups")
def create_backup(label: str | None = None):
    return backup_service.create_backup(label)


@app.post("/api/backups/restore/{name}")
def restore_backup(name: str):
    try:
        return backup_service.restore_backup(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/backups/{name}")
def delete_backup(name: str):
    try:
        return backup_service.delete_backup(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@app.get("/api/dashboard")
def dashboard():
    metadata = storage.load_metadata()
    summaries = ingestion.database_summaries()
    total = sum(s["paper_count"] for s in summaries)
    rules = metadata.get("highlight_rules", {})

    dedup = dedup_service.get_report()
    dedup_has_run = dedup.get("has_run", False)
    dedup_kept = dedup.get("kept_count", 0) if dedup_has_run else 0
    # Currently-removed = duplicates still flagged (restores reduce this count).
    dedup_removed = len(dedup.get("duplicates", [])) if dedup_has_run else 0

    screening = screening_service.get_screening()
    screen_counts = screening.get("counts", {})
    screen_total = screen_counts.get("total", 0)
    screen_decided = screen_counts.get("decided", 0)

    return {
        "title": metadata.get("title", ""),
        "research_questions": metadata.get("research_questions", ""),
        "context_configured": bool(metadata.get("keyword_string")),
        "highlight_terms": len(rules.get("terms", [])),
        "highlight_source": rules.get("source"),
        "total_papers": total,
        "databases": summaries,
        "dedup": {
            "has_run": dedup_has_run,
            "kept": dedup_kept,
            "removed": dedup_removed,
        },
        "screening": {
            "total": screen_total,
            "decided": screen_decided,
            "by_label": screen_counts.get("by_label", {}),
        },
        "stages": [
            {"key": "01_raw_paper_list", "label": "Data Ingestion", "count": total,
             "done": total > 0},
            {"key": "02_deduplication", "label": "Deduplication", "count": dedup_kept,
             "done": dedup_has_run},
            {"key": "03_abstract_title_screening", "label": "Screening",
             "count": screen_decided, "done": screen_total > 0 and screen_decided >= screen_total},
        ],
    }
