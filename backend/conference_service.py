"""Conference Search — registry CRUD + DBLP enumeration (Phase 1).

Venues live in context/metadata.json under the editable `conferences` array
(seeded from storage.DEFAULT_CONFERENCES). Fetching a venue enumerates its
accepted papers from DBLP and saves them, one JSON per venue, under
data/00c_conference_papers/. Abstract enrichment is Phase 2; abstracts are left
empty here.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import dblp_client, storage

Logger = Callable[[str], None]


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "venue"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find(metadata: dict, venue_id: str) -> Optional[dict]:
    return next((c for c in metadata.get("conferences", []) if c["id"] == venue_id), None)


def _index_range(papers: list[dict], prefix: str) -> Optional[str]:
    nums = []
    for p in papers:
        m = re.search(r"(\d+)$", p.get("index", ""))
        if m:
            nums.append(int(m.group(1)))
    if not nums:
        return None
    lo, hi = min(nums), max(nums)
    return f"{prefix}-{lo:03d}" if lo == hi else f"{prefix}-{lo:03d}–{prefix}-{hi:03d}"


def _summary(conf: dict) -> dict[str, Any]:
    papers = storage.load_conference_papers(conf["id"])
    return {
        "id": conf["id"],
        "display": conf["display"],
        "dblp_key": conf["dblp_key"],
        "track": conf.get("track", "main"),
        "year_start": conf.get("year_start", 2020),
        "year_end": conf.get("year_end", 2025),
        "enabled": conf.get("enabled", True),
        "paper_count": len(papers),
        "index_range": _index_range(papers, conf["id"].upper()),
        "last_fetched": conf.get("last_fetched"),
    }


# --------------------------------------------------------------------------- #
# Registry CRUD
# --------------------------------------------------------------------------- #
def list_conferences() -> list[dict[str, Any]]:
    metadata = storage.load_metadata()
    return [_summary(c) for c in metadata.get("conferences", [])]


def add_conference(payload: dict) -> dict[str, Any]:
    metadata = storage.load_metadata()
    venue_id = _slugify(payload.get("id") or payload["display"])
    if _find(metadata, venue_id):
        raise ValueError("A conference with this id already exists.")
    conf = {
        "id": venue_id,
        "display": payload["display"].strip(),
        "dblp_key": payload["dblp_key"].strip().strip("/"),
        "track": payload.get("track") or "main",
        "include_workshops": bool(payload.get("include_workshops", False)),
        "include_companion": bool(payload.get("include_companion", False)),
        "year_start": payload.get("year_start") or 2020,
        "year_end": payload.get("year_end") or 2025,
        "abstract_sources": payload.get("abstract_sources") or ["openalex", "s2"],
        "enabled": bool(payload.get("enabled", True)),
    }
    metadata.setdefault("conferences", []).append(conf)
    storage.save_metadata(metadata)
    return _summary(conf)


def update_conference(venue_id: str, payload: dict) -> dict[str, Any]:
    metadata = storage.load_metadata()
    conf = _find(metadata, venue_id)
    if conf is None:
        raise KeyError("Conference not found.")
    for key in ("display", "dblp_key", "track", "include_workshops",
                "include_companion", "year_start", "year_end",
                "abstract_sources", "enabled"):
        if key in payload and payload[key] is not None:
            value = payload[key]
            if key in ("display", "dblp_key", "track") and isinstance(value, str):
                value = value.strip()
            if key == "dblp_key":
                value = value.strip("/")
            conf[key] = value
    storage.save_metadata(metadata)
    return _summary(conf)


def delete_conference(venue_id: str) -> dict[str, Any]:
    metadata = storage.load_metadata()
    before = len(metadata.get("conferences", []))
    metadata["conferences"] = [c for c in metadata.get("conferences", []) if c["id"] != venue_id]
    if len(metadata["conferences"]) == before:
        raise KeyError("Conference not found.")
    storage.save_metadata(metadata)
    storage.delete_conference_papers(venue_id)
    return {"deleted": venue_id}


# --------------------------------------------------------------------------- #
# Papers
# --------------------------------------------------------------------------- #
def conference_papers(venue_id: str) -> list[dict[str, Any]]:
    return storage.load_conference_papers(venue_id)


def clear_conference_papers(venue_id: str) -> dict[str, Any]:
    metadata = storage.load_metadata()
    conf = _find(metadata, venue_id)
    storage.delete_conference_papers(venue_id)
    if conf is not None:
        conf.pop("last_fetched", None)
        storage.save_metadata(metadata)
    return {"cleared": venue_id}


# --------------------------------------------------------------------------- #
# Fetch (enumerate)
# --------------------------------------------------------------------------- #
def _to_schema(rec: dict, conf: dict) -> dict[str, Any]:
    return {
        "index": "",                 # assigned by _reindex once the set is assembled
        "database": "DBLP Conferences",
        "database_id": "dblp_conf",
        "venue_id": conf["id"],
        "venue": conf["display"],
        "title": rec["title"],
        "authors": rec["authors"],
        "year": rec["year"],
        "abstract": "",              # filled in Phase 2 (enrichment)
        "keywords": [],
        "doi": rec["doi"],
        "url": rec["ee"] or rec["dblp_url"],
        "source_file": f"dblp:{rec.get('toc_key', conf['dblp_key'])}",
        "abstract_source": None,     # Phase 2
        "match_confidence": None,    # Phase 2
        "raw": {
            "dblp_key": rec["dblp_key"],
            "dblp_url": rec["dblp_url"],
            "venue_raw": rec["venue_raw"],
            "type": rec["type"],
            "toc_key": rec.get("toc_key", ""),
        },
    }


def _reindex(papers: list[dict], prefix: str) -> list[dict]:
    for i, p in enumerate(papers, 1):
        p["index"] = f"{prefix}-{i:03d}"
    return papers


def fetch_conference(venue_id: str, *, refresh: bool = False,
                     logger: Optional[Logger] = None,
                     year: Optional[int] = None) -> dict[str, Any]:
    """Enumerate a venue's accepted papers and save them, incrementally.

    Each year (TOC) is saved as soon as it completes, so a failure partway
    through keeps what already succeeded. Pass ``year`` to fetch a single year
    and merge it into the venue's existing papers (replacing that year); omit it
    to (re)fetch the whole configured range.
    """
    metadata = storage.load_metadata()
    conf = _find(metadata, venue_id)
    if conf is None:
        raise KeyError("Conference not found.")
    prefix = venue_id.upper()

    if year is not None:
        y0 = y1 = year
        # Keep everything except the year being refreshed.
        acc = [p for p in storage.load_conference_papers(venue_id) if p.get("year") != year]
    else:
        y0 = conf.get("year_start", 2020)
        y1 = conf.get("year_end", 2025)
        acc = []

    def on_toc(_toc: dict, recs: list) -> None:
        acc.extend(_to_schema(rec, conf) for rec in recs)
        _reindex(acc, prefix)
        storage.save_conference_papers(venue_id, acc)  # persist progress per year

    result = dblp_client.enumerate_venue(
        conf["dblp_key"], y0, y1,
        track=conf.get("track", "main"),
        include_workshops=conf.get("include_workshops", False),
        include_companion=conf.get("include_companion", False),
        refresh=refresh, logger=logger, on_toc=on_toc,
    )

    _reindex(acc, prefix)
    storage.save_conference_papers(venue_id, acc)  # final save (covers the no-TOC case)

    fetched_at = _now()
    run_id = f"{venue_id}-{fetched_at.replace(':', '').replace('-', '')[:15]}"
    manifest = {
        "run_id": run_id,
        "venue_id": venue_id,
        "display": conf["display"],
        "dblp_key": conf["dblp_key"],
        "year_start": y0,
        "year_end": y1,
        "track": conf.get("track", "main"),
        "fetched_at": fetched_at,
        "resolved_tocs": result["tocs"],
        "per_year_counts": result["per_year"],
        "failed_tocs": result["failed_tocs"],
        "total": len(acc),
        "source": "dblp",
    }
    storage.save_conference_snapshot(run_id, manifest)

    conf["last_fetched"] = fetched_at
    storage.save_metadata(metadata)

    return {
        "summary": _summary(conf),
        "per_year": result["per_year"],
        "resolved_tocs": result["tocs"],
        "failed_tocs": result["failed_tocs"],
        "total": len(acc),
        "run_id": run_id,
    }
