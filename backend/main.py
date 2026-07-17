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
  DELETE /api/papers/{db_id}        -> clear a database's papers (downstream is left intact)
  GET  /api/papers/{db_id}/raw-files            -> list retained original uploads
  GET  /api/papers/{db_id}/raw-files/{filename} -> download an original upload
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
from fastapi.responses import FileResponse, Response

from pydantic import BaseModel

from agents.keyword_highlighter import update_metadata_highlighting

from . import (
    analysis_service,
    backup_service,
    conference_import_service,
    dedup_service,
    full_text_service,
    ingestion,
    page_filter_service,
    parsers,
    screening_service,
    storage,
    tagging_service,
)
from .models import (
    ConferenceImportRequest,
    ContextUpdate,
    DatabaseCreate,
    DatabaseUpdate,
    ScreeningLabel,
)

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


@app.patch("/api/databases/{db_id}")
def update_database(db_id: str, payload: DatabaseUpdate):
    metadata = storage.load_metadata()
    db = next((d for d in metadata["databases"] if d["id"] == db_id), None)
    if db is None:
        raise HTTPException(status_code=404, detail="Database not found.")
    if payload.name is not None:
        db["name"] = payload.name.strip()
    if payload.prefix is not None:
        db["prefix"] = payload.prefix.strip().upper()
    if payload.priority is not None:
        db["priority"] = payload.priority
    if payload.proxy_suffix is not None:
        # Empty/whitespace clears the proxy (helper returns None).
        db["proxy_suffix"] = full_text_service.clean_proxy_suffix(payload.proxy_suffix)
    storage.save_metadata(metadata)
    return db


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
    papers = storage.load_papers(db_id)
    # Backfill the early_access flag for papers ingested before it existed.
    for p in papers:
        if "early_access" not in p:
            p["early_access"] = parsers.derive_early_access(p.get("raw"))
    return papers


@app.delete("/api/papers/{db_id}")
def clear_papers(db_id: str):
    """Empty a database's raw paper list. The database entry itself stays.

    Only *this* database's papers are removed downstream: after emptying, we
    re-reconcile deduplication over the remaining databases (deterministic, so
    every other database keeps its result and manual restores), and page filter,
    screening, full-text and tagging then reconcile against the new kept set —
    preserving each surviving paper's decision by index. No other database's work
    is discarded. (No-op reconcile if deduplication hasn't been run yet.)
    """
    storage.delete_papers(db_id)
    dedup_service.reconcile()
    return {"cleared": db_id}


@app.get("/api/papers/{db_id}/raw-files")
def list_raw_files(db_id: str):
    """List the original uploaded files retained for a database (latest batch)."""
    return storage.list_raw_uploads(db_id)


@app.get("/api/papers/{db_id}/raw-files/{filename}")
def download_raw_file(db_id: str, filename: str):
    """Download an original uploaded file as stored on the server."""
    fp = storage.raw_upload_path(db_id, filename)
    if fp is None:
        raise HTTPException(status_code=404, detail="Raw file not found.")
    return FileResponse(
        path=str(fp),
        filename=fp.name,
        media_type="application/octet-stream",
    )


# --------------------------------------------------------------------------- #
# Conference Import — pull filtered papers from a conference-toolkit instance
# --------------------------------------------------------------------------- #
@app.get("/api/conference-import/venues")
def conference_import_venues(url: str):
    """List the venues a running conference-toolkit has registered."""
    try:
        return conference_import_service.list_remote_venues(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/conference-import")
def conference_import(payload: ConferenceImportRequest):
    """Filter (via the toolkit) + import matching papers into the pipeline."""
    try:
        return conference_import_service.import_papers(
            payload.url, payload.keyword_string, payload.venue_ids, use_llm=payload.use_llm
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


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
# Page filter (between deduplication and screening)
# --------------------------------------------------------------------------- #
class PageFilterConfig(BaseModel):
    min_pages: int | None = None
    max_pages: int | None = None
    exclude_unknown: bool = False


@app.get("/api/page-filter")
def get_page_filter():
    return page_filter_service.get()


@app.put("/api/page-filter")
def set_page_filter(cfg: PageFilterConfig):
    return page_filter_service.set_config(cfg.min_pages, cfg.max_pages, cfg.exclude_unknown)


@app.post("/api/page-filter/override/{index}")
def set_page_override(index: str, mode: str):
    try:
        return page_filter_service.set_override(index, mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
# Full-text extraction (Phase 3a)
# --------------------------------------------------------------------------- #
@app.get("/api/full-text")
def get_full_text():
    """Reconcile with the Include set and return the dashboard payload."""
    return full_text_service.get_dashboard()


@app.get("/api/full-text/papers/{index}/text")
def get_full_text_text(index: str):
    text = full_text_service.get_extracted_text(index)
    if text is None:
        raise HTTPException(status_code=404, detail="No extracted text for this paper.")
    return {"index": index, "text": text, "char_count": len(text)}


@app.get("/api/full-text/papers/{index}/pdf")
def download_full_text_pdf(index: str):
    """Download a single paper's stored PDF, named by its title."""
    result = full_text_service.pdf_download(index)
    if result is None:
        raise HTTPException(status_code=404, detail="No PDF stored for this paper.")
    path, filename = result
    return FileResponse(path=str(path), filename=filename, media_type="application/pdf")


@app.get("/api/full-text/download-all")
def download_full_text_pdfs(database_id: str | None = None):
    """Download all stored PDFs as a single zip, each named by its paper title.

    Pass ?database_id=<id> to include a single database only.
    """
    data, count = full_text_service.build_pdf_zip(database_id)
    if count == 0:
        raise HTTPException(status_code=404, detail="No PDFs available to download.")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="included_papers_pdfs.zip"'},
    )


class PdfZipRequest(BaseModel):
    indexes: list[str]


@app.post("/api/full-text/download-zip")
def download_full_text_pdfs_by_index(payload: PdfZipRequest):
    """Download the stored PDFs for a specific set of paper indexes as one zip.

    Used by the analysis drill-down list, which shows an arbitrary filtered
    subset of papers rather than a whole database.
    """
    data, count = full_text_service.build_pdf_zip(indexes=payload.indexes)
    if count == 0:
        raise HTTPException(status_code=404, detail="No PDFs available to download.")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="papers_pdfs.zip"'},
    )


@app.post("/api/full-text/auto-download")
def full_text_auto_download(database_id: str | None = None):
    """Batch Open-Access downloader for 'missing' papers with a DOI.

    Pass ?database_id=<id> to process a single database only.
    """
    return full_text_service.auto_download_oa_batch(database_id)


@app.post("/api/full-text/scan")
def full_text_scan(database_id: str | None = None):
    """Scan raw_pdfs/ for manually-dropped PDFs and extract them.

    Pass ?database_id=<id> to scan a single database only.
    """
    return full_text_service.scan_local_pdfs(database_id)


@app.post("/api/full-text/upload/{index}")
async def full_text_upload(index: str, file: UploadFile = File(...)):
    content = await file.read()
    try:
        return full_text_service.save_uploaded_pdf(index, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/full-text/papers/{index}/unavailable")
def full_text_mark_unavailable(index: str):
    """User marks a paper as having no obtainable free full-text PDF."""
    rec = full_text_service.mark_unavailable(index)
    if not rec:
        raise HTTPException(status_code=404, detail="Paper not found in full-text state.")
    return rec


@app.delete("/api/full-text/papers/{index}")
def full_text_delete(index: str):
    rec = full_text_service.delete_paper(index)
    if not rec:
        raise HTTPException(status_code=404, detail="Paper not found in full-text state.")
    return rec


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

    pf = page_filter_service.get()
    pf_counts = pf.get("counts", {})
    pf_included = pf_counts.get("included", 0) + pf_counts.get("unknown", 0)
    pf_active = pf.get("active", False)

    screening = screening_service.get_screening()
    screen_counts = screening.get("counts", {})
    screen_total = screen_counts.get("total", 0)
    screen_decided = screen_counts.get("decided", 0)

    ft_counts = full_text_service.get_dashboard().get("counts", {})
    ft_total = ft_counts.get("total", 0)
    ft_extracted = ft_counts.get("extracted", 0)

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
        "page_filter": {
            "active": pf_active,
            "included": pf_included,
            "excluded": pf_counts.get("excluded", 0),
        },
        "stages": [
            {"key": "01_raw_paper_list", "label": "Data Ingestion", "count": total,
             "done": total > 0},
            {"key": "02_deduplication", "label": "Deduplication", "count": dedup_kept,
             "done": dedup_has_run},
            {"key": "02b_page_filter", "label": "Page Filter", "count": pf_included,
             "done": pf_active},
            {"key": "02c_abstract_title_screening", "label": "Screening",
             "count": screen_decided, "done": screen_total > 0 and screen_decided >= screen_total},
            {"key": "03a_full_text_extraction", "label": "Full-Text Extraction",
             "count": ft_extracted, "done": ft_total > 0 and ft_extracted >= ft_total},
        ],
    }


# --------------------------------------------------------------------------- #
# Keyword tagging (Phase 5): multiple independent dimensions, each with its own
# extraction + categorization.
# --------------------------------------------------------------------------- #
class DimensionPayload(BaseModel):
    name: str = ""
    description: str = ""
    preferred: list[str] = []
    sources: list[str] | None = None


class DimensionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    preferred: list[str] | None = None
    tag_descriptions: dict[str, str] | None = None
    sources: list[str] | None = None


class ExtractionRequest(BaseModel):
    limit: int | None = None
    force: bool = False


class SuggestRequest(BaseModel):
    target: str = "description"  # "description" | "keywords"
    name: str | None = None
    description: str | None = None


class RemoveTagPayload(BaseModel):
    tag: str


class MergeTagPayload(BaseModel):
    source: str
    target: str


class GroupPayload(BaseModel):
    name: str
    members: list[str] = []


class GroupUpdate(BaseModel):
    name: str | None = None
    members: list[str] | None = None


def _tagging_error(e: ValueError) -> HTTPException:
    msg = str(e)
    code = 404 if ("Unknown dimension" in msg or "not found" in msg.lower()) else 400
    return HTTPException(status_code=code, detail=msg)


@app.get("/api/tagging/dimensions")
def list_tagging_dimensions():
    return tagging_service.list_dimensions()


@app.post("/api/tagging/dimensions")
def create_tagging_dimension(payload: DimensionPayload):
    try:
        return tagging_service.add_dimension(
            payload.name, payload.description, payload.preferred, payload.sources
        )
    except ValueError as e:
        raise _tagging_error(e)


@app.put("/api/tagging/dimensions/{field}")
def update_tagging_dimension(field: str, payload: DimensionUpdate):
    try:
        return tagging_service.update_dimension(
            field, payload.name, payload.description, payload.preferred,
            payload.tag_descriptions, payload.sources,
        )
    except ValueError as e:
        raise _tagging_error(e)


@app.delete("/api/tagging/dimensions/{field}")
def delete_tagging_dimension(field: str):
    try:
        tagging_service.delete_dimension(field)
        return {"deleted": field}
    except ValueError as e:
        raise _tagging_error(e)


@app.get("/api/tagging/dimensions/{field}")
def get_tagging_dimension(field: str):
    try:
        return tagging_service.get_state(field)
    except ValueError as e:
        raise _tagging_error(e)


@app.post("/api/tagging/dimensions/{field}/remove-tag")
def remove_tagging_tag(field: str, payload: RemoveTagPayload):
    """Remove one tag from this dimension everywhere (vocabulary, groups, and
    every paper's tags/evidence)."""
    try:
        return tagging_service.remove_tag(field, payload.tag)
    except ValueError as e:
        raise _tagging_error(e)


@app.post("/api/tagging/dimensions/{field}/merge-tag")
def merge_tagging_tag(field: str, payload: MergeTagPayload):
    """Fold one tag into another for this dimension, across all papers."""
    try:
        return tagging_service.merge_tag(field, payload.source, payload.target)
    except ValueError as e:
        raise _tagging_error(e)


@app.post("/api/tagging/dimensions/{field}/suggest")
def suggest_tagging_definition(field: str, payload: SuggestRequest | None = None):
    target = payload.target if payload else "description"
    name = payload.name if payload else None
    description = payload.description if payload else None
    try:
        return tagging_service.suggest(field, target, name, description)
    except ValueError as e:
        raise _tagging_error(e)


@app.post("/api/tagging/dimensions/{field}/extract")
def run_tagging_extraction(field: str, payload: ExtractionRequest | None = None):
    limit = payload.limit if payload else None
    force = payload.force if payload else False
    try:
        return tagging_service.run_extraction(field, limit=limit, force=force)
    except ValueError as e:
        raise _tagging_error(e)


@app.get("/api/tagging/dimensions/{field}/papers")
def get_tagging_papers(field: str):
    try:
        return tagging_service.get_papers(field)
    except ValueError as e:
        raise _tagging_error(e)


@app.post("/api/tagging/prune-non-fulltext")
def prune_tagging_non_fulltext():
    """Remove tagged papers that aren't in the current full-text set.

    Cleans up leftovers from runs made before extraction was gated to full-text
    papers, so the analysis list only contains papers with a downloadable PDF.
    """
    return tagging_service.prune_non_fulltext()


@app.get("/api/tagging/dimensions/{field}/categories")
def get_tagging_categories(field: str):
    try:
        return tagging_service.category_stats(field)
    except ValueError as e:
        raise _tagging_error(e)


@app.post("/api/tagging/dimensions/{field}/groups")
def create_tagging_group(field: str, payload: GroupPayload):
    try:
        return tagging_service.add_group(field, payload.name, payload.members)
    except ValueError as e:
        raise _tagging_error(e)


@app.put("/api/tagging/dimensions/{field}/groups/{group_id}")
def update_tagging_group(field: str, group_id: str, payload: GroupUpdate):
    try:
        return tagging_service.update_group(field, group_id, payload.name, payload.members)
    except ValueError as e:
        raise _tagging_error(e)


@app.delete("/api/tagging/dimensions/{field}/groups/{group_id}")
def delete_tagging_group(field: str, group_id: str):
    try:
        tagging_service.delete_group(field, group_id)
        return {"deleted": group_id}
    except ValueError as e:
        raise _tagging_error(e)


# --------------------------------------------------------------------------- #
# Keyword Analysis (Phase 6): configurable multi-level charts + saved views
# --------------------------------------------------------------------------- #
class AnalysisConfig(BaseModel):
    top: dict | None = None
    breakdown: dict | None = None
    series: dict | None = None
    options: dict | None = None


class AnalysisView(BaseModel):
    name: str
    config: dict = {}


class AnalysisViewUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None


@app.get("/api/analysis/dimensions")
def analysis_dimensions():
    return analysis_service.dimensions()


@app.post("/api/analysis/compute")
def analysis_compute(config: AnalysisConfig):
    return analysis_service.compute(config.model_dump())


class PapersForRequest(BaseModel):
    filters: list[dict] = []


@app.post("/api/analysis/papers")
def analysis_papers(payload: PapersForRequest):
    return analysis_service.papers_for(payload.filters)


@app.post("/api/analysis/papers/detail")
def analysis_papers_detail(payload: PapersForRequest):
    return analysis_service.papers_detail(payload.filters)


@app.get("/api/analysis/views")
def analysis_list_views():
    return analysis_service.list_views()


@app.post("/api/analysis/views")
def analysis_create_view(payload: AnalysisView):
    try:
        return analysis_service.create_view(payload.name, payload.config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/analysis/views/{view_id}")
def analysis_update_view(view_id: str, payload: AnalysisViewUpdate):
    try:
        return analysis_service.update_view(view_id, payload.name, payload.config)
    except ValueError as e:
        code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=code, detail=str(e))


@app.delete("/api/analysis/views/{view_id}")
def analysis_delete_view(view_id: str):
    try:
        analysis_service.delete_view(view_id)
        return {"deleted": view_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
