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
from urllib.parse import urlsplit, urlunsplit

import httpx
from pypdf import PdfReader

from . import paths, screening_service, storage

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

# A browser-like User-Agent helps with publisher hosts / institutional proxies
# that reject the default python-httpx agent.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_HTTP_HEADERS = {"User-Agent": BROWSER_UA}

_RECORD_FIELDS = ("index", "title", "authors", "year", "database", "database_id", "doi", "url")


# --------------------------------------------------------------------------- #
# Institutional proxy (EZproxy hostname-remapping style)
# --------------------------------------------------------------------------- #
def clean_proxy_suffix(suffix: Optional[str]) -> Optional[str]:
    """Normalise a configured proxy suffix, or None if effectively empty.

    Accepts values like "mediaproxy.imtbs-tsp.eu", ".mediaproxy.imtbs-tsp.eu",
    or "https://mediaproxy.imtbs-tsp.eu/" and returns the bare host suffix.
    """
    if not suffix:
        return None
    s = suffix.strip()
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.strip().strip("/").strip(".")
    return s or None


def proxy_rewrite(url: Optional[str], suffix: Optional[str]) -> Optional[str]:
    """Rewrite a URL's host through an EZproxy-style suffix.

    e.g. https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=9670669  with
    suffix "mediaproxy.imtbs-tsp.eu" ->
         https://ieeexplore-ieee-org.mediaproxy.imtbs-tsp.eu/stamp/stamp.jsp?arnumber=9670669
    Returns the URL unchanged when no suffix or no host is present.
    """
    suffix = clean_proxy_suffix(suffix)
    if not url or not suffix:
        return url
    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        return url
    dashed = host.replace(".", "-")
    # Accept either a bare suffix ("mediaproxy.imtbs-tsp.eu") or a full proxied
    # host that already contains the rewritten hostname
    # ("ieeexplore-ieee-org.mediaproxy.imtbs-tsp.eu") — don't double the prefix.
    if suffix == dashed or suffix.startswith(dashed + "."):
        new_host = suffix
    else:
        new_host = dashed + "." + suffix
    if parts.port:
        new_host = f"{new_host}:{parts.port}"
    return urlunsplit((parts.scheme or "https", new_host, parts.path,
                       parts.query, parts.fragment))


def _proxy_map() -> dict[str, Optional[str]]:
    """Map database_id -> configured proxy suffix (only non-empty ones)."""
    out: dict[str, Optional[str]] = {}
    for db in storage.load_metadata().get("databases", []):
        suffix = clean_proxy_suffix(db.get("proxy_suffix"))
        if suffix:
            out[db["id"]] = suffix
    return out


def _download_url_for(rec: dict[str, Any], proxy_map: dict[str, Optional[str]]) -> Optional[str]:
    """Best manual-download URL for a paper: the stored publisher url routed
    through the database's proxy when configured, else the raw url, else a DOI link.
    """
    suffix = proxy_map.get(rec.get("database_id"))
    raw_url = rec.get("url")
    if raw_url:
        return proxy_rewrite(raw_url, suffix) if suffix else raw_url
    doi = _clean_doi(rec.get("doi"))
    return f"https://doi.org/{doi}" if doi else None


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
    """Reconcile, then return the ordered records + counts + include source.

    Each paper gets a transient ``download_url`` (the stored publisher url routed
    through the database's institutional proxy when configured) for the UI's
    manual download link. It is computed from live config, not persisted.
    """
    state = sync_included_papers()
    records = state["records"]
    proxy_map = _proxy_map()
    ordered = []
    for k in sorted(records.keys()):
        rec = dict(records[k])
        rec["download_url"] = _download_url_for(rec, proxy_map)
        ordered.append(rec)
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


def _fetch_pdf_bytes(url: str, client: httpx.Client) -> tuple[Optional[bytes], str]:
    """GET a URL and return (pdf_bytes, "") if it's a real PDF, else (None, reason)."""
    try:
        r = client.get(url, timeout=DOWNLOAD_TIMEOUT,
                        headers={"Accept": "application/pdf,*/*"})
        r.raise_for_status()
    except httpx.HTTPError as e:
        return None, f"download_failed: {type(e).__name__}"
    # Landing pages / proxy login pages return HTML, not a PDF.
    if not r.content[:5].startswith(b"%PDF"):
        return None, "not_a_pdf"
    return r.content, ""


def auto_download_oa(index: str, client: Optional[httpx.Client] = None) -> dict[str, Any]:
    """Fetch an Open-Access PDF for one paper (via OpenAlex), then extract text.

    Open Access ONLY — this never routes through an institutional proxy. Proxied
    (e.g. IEEE) papers are reached solely through the manual Download link, so
    automated parallel requests can't breach a publisher's concurrent-session
    limit or trip the proxy's bot protection.
    """
    state = _read()
    rec = state["records"].get(index)
    if rec is None:
        return {}
    doi = _clean_doi(rec.get("doi"))
    if not doi:
        return _update_record(index, status="error", error="no_doi") or {}

    own_client = client is None
    client = client or httpx.Client(timeout=OPENALEX_TIMEOUT, follow_redirects=True,
                                    headers=_HTTP_HEADERS)
    try:
        try:
            oa_url = _resolve_oa_url(doi, client)
        except httpx.HTTPError as e:
            return _update_record(index, status="error",
                                  error=f"openalex_failed: {type(e).__name__}") or {}
        if not oa_url:
            return _update_record(index, status="error", error="no_oa_pdf") or {}

        content, reason = _fetch_pdf_bytes(oa_url, client)
        if not content:
            return _update_record(index, status="error", pdf_url=oa_url,
                                  error=reason) or {}

        _ensure_dirs()
        _pdf_path(index).write_bytes(content)
        _update_record(index, status="downloading", source="oa", pdf_url=oa_url,
                       error=None)
        return extract_text_from_pdf(index)
    finally:
        if own_client:
            client.close()


def auto_download_oa_batch(database_id: Optional[str] = None) -> dict[str, Any]:
    """Attempt an Open-Access download for every 'missing' paper that has a DOI.

    When ``database_id`` is given, only that database's papers are processed
    (lets the user work one source at a time).

    Open Access only — proxied databases are intentionally excluded so parallel
    requests never open concurrent proxy/publisher sessions. Those papers are
    fetched manually via the Download link.

    Uses a synchronous httpx client per worker inside a thread pool (matching the
    codebase's threading pattern) — no async/thread mixing.
    """
    sync_included_papers()
    state = _read()
    targets = [
        idx for idx, rec in state["records"].items()
        if rec.get("status") == "missing" and _clean_doi(rec.get("doi"))
        and (database_id is None or rec.get("database_id") == database_id)
    ]

    def _work(idx: str) -> str:
        with httpx.Client(timeout=OPENALEX_TIMEOUT, follow_redirects=True,
                          headers=_HTTP_HEADERS) as c:
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
def scan_local_pdfs(database_id: Optional[str] = None) -> dict[str, Any]:
    """Extract text from any raw_pdfs/<index>.pdf that isn't extracted yet.

    When ``database_id`` is given, only that database's papers are scanned.
    Enables dropping PDFs straight into the filesystem.
    """
    sync_included_papers()
    _ensure_dirs()
    state = _read()
    scanned = 0
    extracted = 0
    for idx, rec in state["records"].items():
        if database_id is not None and rec.get("database_id") != database_id:
            continue
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
