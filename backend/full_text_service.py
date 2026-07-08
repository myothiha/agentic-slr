"""Phase 3a — full-text PDF retrieval + extraction for 'Include' papers.

Operates on the screening 'Include' set (resolved via ``screening_service`` so
this stage stays consistent with keyword tagging / analysis). For each included
paper we try to obtain a PDF (auto Open-Access download, manual upload, or a
folder scan) and extract its plain text with ``pypdf``.

State persists to data/03a_full_text_extraction/full_text_state.json:

    {
      "records": {
        "<index>": {
          "index", "title", "year", "database", "doi", "url",
          "status": "missing" | "downloading" | "extracted" | "error",
          "source": "oa" | "upload" | "scan" | null,   # how the PDF arrived
          "pdf_url": <resolved OA url or null>,          # for a manual link
          "char_count": <int>, "preview": <str>,
          "error": <reason or null>, "updated_at": "<iso>"
        }
      },
      "include_source": "user" | "ai" | "none",
      "synced_at": "<iso>"
    }

The extracted plain text is stored in individual files
(extracted_texts/<index>.txt) rather than inline, to keep the state JSON small.

Design notes
------------
* ``included_papers()`` delegates to ``screening_service`` — it does NOT
  re-derive the Include set, so the override guard (drop papers the user set to
  Exclude/Maybe) is honoured automatically.
* ``pypdf`` has no OCR: a scanned / image-only PDF yields no text, so extraction
  producing < ``MIN_TEXT_CHARS`` characters is recorded as ``error`` with reason
  ``"no_text_layer"`` rather than a false ``extracted``.
* ``sync_included_papers`` never deletes PDF/TXT files (the Include set shifts
  while screening is in progress); files are only removed by ``delete_paper``.
"""
from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from pypdf import PdfReader

from . import paths, screening_service

_lock = threading.Lock()

STATE_FILE = paths.FULL_TEXT_STATE_FILE
PDF_DIR = paths.FULL_TEXT_PDF_DIR
TXT_DIR = paths.FULL_TEXT_TXT_DIR

# Extraction shorter than this is treated as a failure (scanned / image-only PDF
# with no embedded text layer, since pypdf does no OCR).
MIN_TEXT_CHARS = 100
PREVIEW_CHARS = 500

# OpenAlex asks for a mailto to place callers in its faster "polite pool".
OPENALEX_MAILTO = os.environ.get("OPENALEX_MAILTO") or "myothiha576@gmail.com"
OPENALEX_TIMEOUT = 20.0
DOWNLOAD_TIMEOUT = 45.0
MAX_DOWNLOAD_WORKERS = 6

_RECORD_FIELDS = ("index", "title", "year", "database", "doi", "url")


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dirs() -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    TXT_DIR.mkdir(parents=True, exist_ok=True)


def _blank_state() -> dict[str, Any]:
    return {"records": {}, "include_source": "none", "synced_at": None}


def _read() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return _blank_state()
    text = STATE_FILE.read_text(encoding="utf-8").strip()
    if not text:
        return _blank_state()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _blank_state()
    data.setdefault("records", {})
    data.setdefault("include_source", "none")
    data.setdefault("synced_at", None)
    return data


def _write(state: dict[str, Any]) -> None:
    _ensure_dirs()
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def get_state() -> dict[str, Any]:
    """Read-only snapshot of the full-text state."""
    return _read()


def save_state(state: dict[str, Any]) -> None:
    with _lock:
        _write(state)


def clear() -> None:
    """Delete full-text state + extracted text (used for a cascade reset).

    Raw PDFs are left on disk; they are the user's source material.
    """
    with _lock:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        if TXT_DIR.exists():
            for f in TXT_DIR.glob("*.txt"):
                f.unlink()


# --------------------------------------------------------------------------- #
# Included set + reconciliation
# --------------------------------------------------------------------------- #
def included_papers() -> list[dict[str, Any]]:
    """The active Include set — delegated to the canonical screening resolver."""
    return screening_service.included_papers()


def _pdf_path(index: str):
    return PDF_DIR / f"{index}.pdf"


def _txt_path(index: str):
    return TXT_DIR / f"{index}.txt"


def _blank_record(paper: dict[str, Any]) -> dict[str, Any]:
    rec = {k: paper.get(k) for k in _RECORD_FIELDS}
    rec.update({
        "status": "missing",
        "source": None,
        "pdf_url": None,
        "char_count": 0,
        "preview": "",
        "error": None,
        "updated_at": _now(),
    })
    return rec


def sync_included_papers() -> dict[str, Any]:
    """Reconcile state records with the current Include set.

    Adds blank records for newly-included papers and drops records for papers no
    longer included. Never deletes PDF/TXT files — the Include set legitimately
    changes while screening is in progress and a paper may return.
    """
    papers = included_papers()
    source = screening_service.include_source()
    by_index = {p["index"]: p for p in papers}

    with _lock:
        state = _read()
        old = state.get("records", {})
        new_records: dict[str, Any] = {}
        for idx, paper in by_index.items():
            rec = old.get(idx)
            if rec is None:
                rec = _blank_record(paper)
            else:
                # Refresh display/link fields in case the source metadata changed.
                for k in _RECORD_FIELDS:
                    rec[k] = paper.get(k, rec.get(k))
            new_records[idx] = rec
        state["records"] = new_records
        state["include_source"] = source
        state["synced_at"] = _now()
        _write(state)
    return state


def _counts(records: dict[str, Any]) -> dict[str, int]:
    counts = {"total": len(records), "extracted": 0, "missing": 0,
              "downloading": 0, "error": 0}
    for rec in records.values():
        st = rec.get("status", "missing")
        if st in counts:
            counts[st] += 1
    return counts


def get_dashboard() -> dict[str, Any]:
    """Reconcile, then return the ordered records + counts + include source."""
    state = sync_included_papers()
    records = state["records"]
    ordered = [records[k] for k in sorted(records.keys())]
    return {
        "papers": ordered,
        "counts": _counts(records),
        "include_source": state.get("include_source", "none"),
    }


def _update_record(index: str, **changes: Any) -> Optional[dict[str, Any]]:
    """Load-mutate-save a single record atomically. Returns the record."""
    with _lock:
        state = _read()
        rec = state["records"].get(index)
        if rec is None:
            return None
        rec.update(changes)
        rec["updated_at"] = _now()
        _write(state)
        return rec


# --------------------------------------------------------------------------- #
# Text extraction
# --------------------------------------------------------------------------- #
def extract_text_from_pdf(index: str) -> dict[str, Any]:
    """Extract text from raw_pdfs/<index>.pdf into extracted_texts/<index>.txt.

    Marks the record ``extracted`` on success, or ``error`` with reason
    ``no_text_layer`` when the PDF yields (almost) no text.
    """
    pdf_path = _pdf_path(index)
    if not pdf_path.exists():
        return _update_record(index, status="error", error="pdf_missing") or {}

    try:
        reader = PdfReader(str(pdf_path))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
    except Exception as e:  # corrupt / encrypted PDF
        return _update_record(index, status="error",
                              error=f"parse_failed: {type(e).__name__}") or {}

    if len(text) < MIN_TEXT_CHARS:
        return _update_record(index, status="error", error="no_text_layer",
                              char_count=len(text)) or {}

    _ensure_dirs()
    _txt_path(index).write_text(text, encoding="utf-8")
    return _update_record(
        index,
        status="extracted",
        error=None,
        char_count=len(text),
        preview=text[:PREVIEW_CHARS],
    ) or {}


def get_extracted_text(index: str) -> Optional[str]:
    """Full plain text for a paper, or None if not extracted yet."""
    fp = _txt_path(index)
    if not fp.exists():
        return None
    return fp.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Open-Access download (OpenAlex)
# --------------------------------------------------------------------------- #
def _clean_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
    return doi or None


def _resolve_oa_url(doi: str, client: httpx.Client) -> Optional[str]:
    """Ask OpenAlex for an Open-Access PDF/landing URL for a DOI."""
    url = f"https://api.openalex.org/works/https://doi.org/{doi}"
    resp = client.get(url, params={"mailto": OPENALEX_MAILTO})
    if resp.status_code != 200:
        return None
    data = resp.json()
    for loc_key in ("best_oa_location", "primary_location"):
        loc = data.get(loc_key) or {}
        if loc.get("pdf_url"):
            return loc["pdf_url"]
    oa = data.get("open_access") or {}
    return oa.get("oa_url")


def auto_download_oa(index: str, client: Optional[httpx.Client] = None) -> dict[str, Any]:
    """Resolve + download an OA PDF for one paper, then extract its text.

    Stores the resolved OA url on the record (even on failure) so the UI can
    still offer a manual download link.
    """
    state = _read()
    rec = state["records"].get(index)
    if rec is None:
        return {}
    doi = _clean_doi(rec.get("doi"))
    if not doi:
        return _update_record(index, status="error", error="no_doi") or {}

    own_client = client is None
    client = client or httpx.Client(timeout=OPENALEX_TIMEOUT, follow_redirects=True)
    try:
        try:
            pdf_url = _resolve_oa_url(doi, client)
        except httpx.HTTPError as e:
            return _update_record(index, status="error",
                                  error=f"openalex_failed: {type(e).__name__}") or {}
        if not pdf_url:
            return _update_record(index, status="error", error="no_oa_pdf") or {}

        try:
            r = client.get(pdf_url, timeout=DOWNLOAD_TIMEOUT)
            r.raise_for_status()
            content = r.content
        except httpx.HTTPError as e:
            return _update_record(index, status="error", pdf_url=pdf_url,
                                  error=f"download_failed: {type(e).__name__}") or {}

        # Many oa_url values are landing pages, not the PDF itself.
        if not content[:5].startswith(b"%PDF"):
            return _update_record(index, status="error", pdf_url=pdf_url,
                                  error="not_a_pdf") or {}

        _ensure_dirs()
        _pdf_path(index).write_bytes(content)
        _update_record(index, status="downloading", source="oa", pdf_url=pdf_url,
                       error=None)
        return extract_text_from_pdf(index)
    finally:
        if own_client:
            client.close()


def auto_download_oa_batch() -> dict[str, Any]:
    """Attempt OA download for every 'missing' paper that has a DOI.

    Uses a synchronous httpx client per worker inside a thread pool (matching the
    codebase's threading pattern) — no async/thread mixing.
    """
    sync_included_papers()
    state = _read()
    targets = [
        idx for idx, rec in state["records"].items()
        if rec.get("status") == "missing" and _clean_doi(rec.get("doi"))
    ]

    def _work(idx: str) -> str:
        with httpx.Client(timeout=OPENALEX_TIMEOUT, follow_redirects=True) as c:
            rec = auto_download_oa(idx, client=c)
        return rec.get("status", "error")

    results: list[str] = []
    if targets:
        with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as pool:
            results = list(pool.map(_work, targets))

    return {
        "attempted": len(targets),
        "extracted": results.count("extracted"),
        "failed": sum(1 for r in results if r == "error"),
        "counts": _counts(_read()["records"]),
    }


# --------------------------------------------------------------------------- #
# Manual PDF sources: folder scan + upload
# --------------------------------------------------------------------------- #
def scan_local_pdfs() -> dict[str, Any]:
    """Extract text from any raw_pdfs/<index>.pdf that isn't extracted yet.

    Enables dropping PDFs straight into the filesystem.
    """
    sync_included_papers()
    _ensure_dirs()
    state = _read()
    scanned = 0
    extracted = 0
    for idx, rec in state["records"].items():
        if rec.get("status") == "extracted":
            continue
        if _pdf_path(idx).exists():
            scanned += 1
            _update_record(idx, source=rec.get("source") or "scan")
            result = extract_text_from_pdf(idx)
            if result.get("status") == "extracted":
                extracted += 1
    return {
        "scanned": scanned,
        "extracted": extracted,
        "counts": _counts(_read()["records"]),
    }


def save_uploaded_pdf(index: str, file_bytes: bytes) -> dict[str, Any]:
    """Persist an uploaded PDF for a paper and extract its text."""
    sync_included_papers()
    state = _read()
    if index not in state["records"]:
        raise ValueError(f"{index} is not in the current Include set.")
    if not file_bytes[:5].startswith(b"%PDF"):
        return _update_record(index, status="error", error="not_a_pdf") or {}
    _ensure_dirs()
    _pdf_path(index).write_bytes(file_bytes)
    _update_record(index, source="upload", error=None)
    return extract_text_from_pdf(index)


def delete_paper(index: str) -> dict[str, Any]:
    """Remove the PDF + extracted text and reset the record to 'missing'."""
    with _lock:
        for fp in (_pdf_path(index), _txt_path(index)):
            if fp.exists():
                fp.unlink()
        state = _read()
        rec = state["records"].get(index)
        if rec is None:
            return {}
        rec.update({
            "status": "missing", "source": None, "pdf_url": None,
            "char_count": 0, "preview": "", "error": None, "updated_at": _now(),
        })
        _write(state)
        return rec
