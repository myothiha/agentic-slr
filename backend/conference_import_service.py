"""Import filtered conference papers from a running conference-toolkit instance.

agentic-slr acts as a *client* of the standalone conference-toolkit (which owns
DBLP enumeration + abstract enrichment). This module:

  1. lists the venues the toolkit has registered (so the user can pick some),
  2. asks the toolkit to run its Boolean keyword filter over already-fetched
     papers, subsets the matches to the selected venues, and
  3. lands them into a dedicated "DBLP Conferences" database in the normal
     paper store, so they flow through dedup -> screening -> ... like any other
     database's papers.

The toolkit call is server-to-server (this backend -> toolkit backend), so the
browser's CORS rules don't apply. Nothing is fetched from DBLP here — that is
the toolkit's job; we only read what it has already fetched/enriched.
"""
from __future__ import annotations

from typing import Any

import httpx

from . import ingestion, storage

# The dedicated database the imported papers land in. Auto-created on first use.
CONF_DB = {"id": "dblp_conf", "name": "DBLP Conferences", "prefix": "CONF", "priority": 50}

REQUEST_TIMEOUT = 60.0


# --------------------------------------------------------------------------- #
# URL handling
# --------------------------------------------------------------------------- #
def _base_url(url: str) -> str:
    """Normalize a user-supplied toolkit URL to its scheme://host[:port] root."""
    u = (url or "").strip().rstrip("/")
    if not u:
        raise ValueError("Conference-toolkit URL is required.")
    if not u.startswith(("http://", "https://")):
        u = "http://" + u
    if u.endswith("/api"):  # tolerate the user pasting the API root
        u = u[: -len("/api")]
    return u


# --------------------------------------------------------------------------- #
# Remote calls
# --------------------------------------------------------------------------- #
def list_remote_venues(url: str) -> list[dict[str, Any]]:
    """GET the toolkit's registered venues (id, display, rank, paper_count, …)."""
    base = _base_url(url)
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.get(f"{base}/api/conferences")
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        raise RuntimeError(f"Could not reach conference-toolkit at {base}: {e}") from e


def import_papers(
    url: str,
    keyword_string: str,
    venue_ids: list[str] | None,
    *,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Run the toolkit's keyword filter, subset to selected venues, and ingest.

    Returns an ingest summary augmented with match counts per venue.
    """
    base = _base_url(url)
    if not (keyword_string or "").strip():
        raise ValueError("A Boolean keyword string is required.")

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.post(
                f"{base}/api/conference-filter",
                json={"keyword_string": keyword_string, "use_llm": use_llm},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise RuntimeError(f"Filter request to conference-toolkit failed: {e}") from e

    relevant = data.get("relevant") or []
    selected = {v for v in (venue_ids or []) if v}
    if selected:
        relevant = [p for p in relevant if p.get("venue_id") in selected]

    _ensure_conf_database()
    records = [_to_record(p) for p in relevant]
    summary = ingestion.ingest_records(CONF_DB["id"], records, source_label="conference-toolkit")

    per_venue: dict[str, dict[str, Any]] = {}
    for p in relevant:
        vid = p.get("venue_id") or "?"
        entry = per_venue.setdefault(vid, {"display": p.get("venue") or vid, "matched": 0})
        entry["matched"] += 1

    return {
        **summary,
        "matched": len(relevant),
        "per_venue": per_venue,
        "keyword_string": keyword_string,
        "toolkit_total_relevant": data.get("total_relevant"),
    }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _ensure_conf_database() -> None:
    """Create the 'DBLP Conferences' database entry if it doesn't exist yet."""
    metadata = storage.load_metadata()
    dbs = metadata.setdefault("databases", [])
    if not any(d.get("id") == CONF_DB["id"] for d in dbs):
        dbs.append({**CONF_DB, "proxy_suffix": None})
        storage.save_metadata(metadata)


def _to_record(p: dict[str, Any]) -> dict[str, Any]:
    """Map a conference-toolkit paper to an agentic-slr canonical record."""
    venue = p.get("venue") or ""
    track = p.get("track_label") or p.get("track")
    if track and str(track).lower() != "main":
        venue = f"{venue} · {track}".strip(" ·")

    raw = dict(p.get("raw") or {})
    raw.update({
        "venue_id": p.get("venue_id"),
        "abstract_source": p.get("abstract_source"),
        "match_confidence": p.get("match_confidence"),
        "toolkit_index": p.get("index"),
    })
    return {
        "title": p.get("title", ""),
        "authors": p.get("authors", []),
        "year": p.get("year"),
        "abstract": p.get("abstract", ""),
        "keywords": p.get("keywords", []),
        "doi": p.get("doi", ""),
        "venue": venue,
        "url": p.get("url", ""),
        "source_file": f"conference-toolkit:{p.get('venue_id', '')}",
        "raw": raw,
    }
