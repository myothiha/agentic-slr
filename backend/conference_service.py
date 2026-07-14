"""Conference Search — registry CRUD + DBLP enumeration (Phase 1).

Venues live in context/metadata.json under the editable `conferences` array
(seeded from storage.DEFAULT_CONFERENCES). Fetching a venue enumerates its
accepted papers from DBLP and saves them, one JSON per venue, under
data/00c_conference_papers/. Abstract enrichment is Phase 2; abstracts are left
empty here.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from agents.keyword_highlighter import build_highlight_rules

from . import abstract_sources, dblp_client, paths, storage

Logger = Callable[[str], None]


def _log(logger: Optional[Logger], msg: str) -> None:
    if logger:
        logger(msg)


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


def _full_name(conf: dict) -> str:
    """Long venue name: explicit field, else the known full name, else display."""
    return (conf.get("full_name")
            or abstract_sources.OPENALEX_QUERY.get(conf["id"])
            or conf["display"])


def _per_year_counts(papers: list[dict]) -> dict[str, int]:
    counts: dict[int, int] = {}
    for p in papers:
        y = p.get("year")
        if y:
            counts[y] = counts.get(y, 0) + 1
    return {str(y): counts[y] for y in sorted(counts)}


def _summary(conf: dict) -> dict[str, Any]:
    papers = storage.load_conference_papers(conf["id"])
    return {
        "id": conf["id"],
        "display": conf["display"],
        "full_name": _full_name(conf),
        "dblp_key": conf["dblp_key"],
        "track": conf.get("track", "main"),
        "year_start": conf.get("year_start", 2020),
        "year_end": conf.get("year_end", 2025),
        "enabled": conf.get("enabled", True),
        "paper_count": len(papers),
        "per_year": _per_year_counts(papers),
        "with_abstract": sum(1 for p in papers if p.get("abstract")),
        "index_range": _index_range(papers, conf["id"].upper()),
        "last_fetched": conf.get("last_fetched"),
    }


# --------------------------------------------------------------------------- #
# Registry CRUD
# --------------------------------------------------------------------------- #
def list_conferences() -> list[dict[str, Any]]:
    metadata = storage.load_metadata()
    return [_summary(c) for c in metadata.get("conferences", [])]


def get_conference_defaults(metadata: Optional[dict] = None) -> dict[str, int]:
    md = metadata if metadata is not None else storage.load_metadata()
    d = md.get("conference_defaults") or {}
    return {"year_start": d.get("year_start", 2020), "year_end": d.get("year_end", 2025)}


def set_conference_defaults(year_start: int, year_end: int,
                            apply_to_all: bool = False) -> dict[str, Any]:
    metadata = storage.load_metadata()
    metadata["conference_defaults"] = {"year_start": year_start, "year_end": year_end}
    if apply_to_all:
        for c in metadata.get("conferences", []):
            c["year_start"] = year_start
            c["year_end"] = year_end
    storage.save_metadata(metadata)
    return {
        "defaults": metadata["conference_defaults"],
        "applied_to_all": apply_to_all,
        "conferences": [_summary(c) for c in metadata.get("conferences", [])],
    }


def add_conference(payload: dict) -> dict[str, Any]:
    metadata = storage.load_metadata()
    venue_id = _slugify(payload.get("id") or payload["display"])
    if _find(metadata, venue_id):
        raise ValueError("A conference with this id already exists.")
    defaults = get_conference_defaults(metadata)
    conf = {
        "id": venue_id,
        "display": payload["display"].strip(),
        "full_name": (payload.get("full_name") or "").strip() or payload["display"].strip(),
        "dblp_key": payload["dblp_key"].strip().strip("/"),
        "track": payload.get("track") or "main",
        "include_workshops": bool(payload.get("include_workshops", False)),
        "include_companion": bool(payload.get("include_companion", False)),
        "year_start": payload.get("year_start") or defaults["year_start"],
        "year_end": payload.get("year_end") or defaults["year_end"],
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
    for key in ("display", "full_name", "dblp_key", "track", "include_workshops",
                "include_companion", "year_start", "year_end",
                "abstract_sources", "enabled"):
        if key in payload and payload[key] is not None:
            value = payload[key]
            if key in ("display", "full_name", "dblp_key", "track") and isinstance(value, str):
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


def clear_conference_abstracts(venue_id: str) -> dict[str, Any]:
    """Reset the enriched abstract fields (keeps the papers). Re-enrich to refill."""
    papers = storage.load_conference_papers(venue_id)
    n = 0
    for p in papers:
        if p.get("abstract") or p.get("abstract_source"):
            p["abstract"] = ""
            p["abstract_source"] = None
            p["match_method"] = None
            p["match_confidence"] = None
            if isinstance(p.get("raw"), dict):
                p["raw"].pop("enrich_candidate", None)
            n += 1
    if n:
        storage.save_conference_papers(venue_id, papers)
    return {"venue_id": venue_id, "cleared": n, "total": len(papers)}


# --------------------------------------------------------------------------- #
# Fetch (enumerate)
# --------------------------------------------------------------------------- #
_TRACK_LABELS = {
    "main": "Main",
    "datasets_benchmarks": "Datasets & Benchmarks",
    "findings": "Findings",
}


def _to_schema(rec: dict, conf: dict) -> dict[str, Any]:
    track = rec.get("track", "main")
    return {
        "index": "",                 # assigned by _reindex once the set is assembled
        "database": "DBLP Conferences",
        "database_id": "dblp_conf",
        "venue_id": conf["id"],
        "venue": conf["display"],
        "track": track,                          # 'main' | 'datasets_benchmarks' | 'findings'
        "track_label": _TRACK_LABELS.get(track, track),
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


def _effective_doi(p: dict) -> str:
    """The paper's DOI, deriving it from an ACL Anthology URL when DBLP omits it.

    ACL DOIs are 10.18653/v1/<anthology-id>, and the anthology id is right there
    in the URL (aclanthology.org/2026.acl-long.564) — so we don't need to wait for
    DBLP to record the DOI or scrape the page.
    """
    doi = p.get("doi", "")
    if doi:
        return doi
    url = p.get("url", "") or ""
    if "aclanthology.org" in url:
        aid = url.split("aclanthology.org/")[-1].split("?")[0].strip("/")
        if aid:
            return f"10.18653/v1/{aid}"
    return ""


def _s2_id(p: dict) -> Optional[str]:
    """Semantic Scholar batch id: DOI (derived for ACL) if any, else DBLP key."""
    doi = abstract_sources.normalize_doi(_effective_doi(p))
    if doi:
        return f"DOI:{doi}"
    k = (p.get("raw") or {}).get("dblp_key")
    return f"DBLP:{k}" if k else None


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


# --------------------------------------------------------------------------- #
# Enrichment (Phase 2) — attach abstracts via OpenAlex bulk title/DOI matching
# --------------------------------------------------------------------------- #
def enrich_conference(venue_id: str, *, refresh: bool = False,
                      logger: Optional[Logger] = None,
                      year: Optional[int] = None,
                      openreview_cookie: Optional[str] = None,
                      openreview_ua: Optional[str] = None) -> dict[str, Any]:
    """Attach abstracts to a venue's fetched papers, saving incrementally.

    Bulk-downloads OpenAlex works per year and matches DBLP papers by DOI ->
    exact title -> fuzzy title. Only papers still missing an abstract are
    processed (unless ``refresh``). Membership is never changed.
    """
    metadata = storage.load_metadata()
    conf = _find(metadata, venue_id)
    if conf is None:
        raise KeyError("Conference not found.")

    papers = storage.load_conference_papers(venue_id)
    if not papers:
        return {"summary": _summary(conf), "coverage": {}, "total": 0,
                "enriched": 0, "review": 0, "unmatched": 0}

    sources = list(conf.get("abstract_sources") or ["openalex"])
    if "homepage" not in sources:
        sources = sources + ["homepage"]  # universal last-resort: scrape the paper's own page
    has_openreview = "openreview" in sources and venue_id in abstract_sources.OPENREVIEW_GROUP
    has_openalex = "openalex" in sources
    has_s2 = "s2" in sources
    SAVE_EVERY = 200

    def needs(p: dict) -> bool:
        if year is not None and p.get("year") != year:
            return False
        return refresh or not p.get("abstract")

    years = sorted({p.get("year") for p in papers if needs(p) and p.get("year")})
    enriched = review = unmatched = 0
    coverage: dict[int, dict[str, int]] = {}

    # OpenAlex source id (resolved once, cached on the registry entry).
    oa_source = conf.get("openalex_source_id")
    oa_tried = False

    if refresh:
        oa_source = None  # force re-resolution (e.g. to correct a stale cached id)

    def resolve_oa() -> Optional[str]:
        nonlocal oa_source, oa_tried
        if oa_source or oa_tried:
            return oa_source
        oa_tried = True
        query = abstract_sources.OPENALEX_QUERY.get(venue_id, conf["display"])
        oa_source = abstract_sources.openalex_source_id(query, refresh=refresh, logger=logger)
        if oa_source:
            conf["openalex_source_id"] = oa_source
            storage.save_metadata(metadata)
        return oa_source

    for yr in years:
        # Pre-fetch per-year source data.
        or_map: dict[str, str] = {}
        if has_openreview:
            or_map = abstract_sources.openreview_bulk(
                abstract_sources.OPENREVIEW_GROUP[venue_id], yr, refresh=refresh, logger=logger,
                cookie=openreview_cookie, user_agent=openreview_ua)
        oa_doi: dict[str, str] = {}
        oa_index = None
        if has_openalex:
            # DOI-first: exact, source-independent lookup (DOI derived for ACL URLs).
            year_dois = [d for p in papers if p.get("year") == yr and needs(p)
                         for d in (_effective_doi(p),) if d]
            if year_dois:
                oa_doi = abstract_sources.openalex_by_dois(year_dois, refresh=refresh, logger=logger)
            # Source+title index as fallback for papers without a DOI (or a DOI miss).
            if resolve_oa():
                try:
                    works = abstract_sources.openalex_works(oa_source, yr, refresh=refresh, logger=logger)
                    oa_index = abstract_sources.build_index(works)
                except RuntimeError as e:
                    _log(logger, f"  {venue_id} {yr}: OpenAlex fetch failed ({e})")

        s2_map: dict[str, str] = {}
        if has_s2:
            s2_ids = [sid for p in papers if p.get("year") == yr and needs(p)
                      for sid in (_s2_id(p),) if sid]
            if s2_ids:
                s2_map = abstract_sources.s2_batch_abstracts(s2_ids, refresh=refresh, logger=logger)

        # Per-id OpenReview lookups only when bulk returned something (proving the
        # venue is served by an API per-id can also reach) and bounded by a cap —
        # so a failed bulk falls straight to OpenAlex instead of crawling for an hour.
        PERID_CAP = 400
        perid_used = 0
        perid_ok = has_openreview and bool(or_map)
        if has_openreview and not or_map:
            _log(logger, f"  {venue_id} {yr}: OpenReview bulk empty; "
                         f"skipping per-id, relying on OpenAlex")

        y_enriched = y_review = y_unmatched = processed = 0
        for p in papers:
            if p.get("year") != yr or not needs(p):
                continue
            resolved = False
            for src in sources:
                if src == "openreview" and has_openreview:
                    nid = abstract_sources.openreview_id_from_url(p.get("url", ""))
                    ab = or_map.get(nid) if nid else ""
                    if not ab and nid and perid_ok and perid_used < PERID_CAP:
                        perid_used += 1
                        ab = abstract_sources.openreview_abstract(
                            nid, refresh=refresh, logger=logger,
                            cookie=openreview_cookie, user_agent=openreview_ua)
                    if ab:
                        p["abstract"] = ab
                        p["abstract_source"] = "openreview"
                        p["match_method"] = "openreview_id"
                        p["match_confidence"] = 1.0
                        enriched += 1; y_enriched += 1; resolved = True
                        break
                elif src == "openalex":
                    # DOI-first (exact, source-independent), then source+title index.
                    doi_n = abstract_sources.normalize_doi(_effective_doi(p))
                    if doi_n and doi_n in oa_doi:
                        p["abstract"] = oa_doi[doi_n]
                        p["abstract_source"] = "openalex"
                        p["match_method"] = "doi"
                        p["match_confidence"] = 1.0
                        enriched += 1; y_enriched += 1; resolved = True
                        break
                    m = abstract_sources.match_paper(p, *oa_index) if oa_index is not None else None
                    if m and not m["needs_review"]:
                        p["abstract"] = m["abstract"]
                        p["abstract_source"] = "openalex"
                        p["match_method"] = m["method"]
                        p["match_confidence"] = m["confidence"]
                        enriched += 1; y_enriched += 1; resolved = True
                        break
                    if m and m["needs_review"]:
                        p["abstract_source"] = "openalex"
                        p["match_method"] = m["method"]
                        p["match_confidence"] = m["confidence"]
                        p.setdefault("raw", {})["enrich_candidate"] = m.get("candidate_title", "")
                        review += 1; y_review += 1; resolved = True
                        break
                elif src == "s2" and s2_map:
                    sid = _s2_id(p)
                    ab = s2_map.get(sid) if sid else None
                    if ab:
                        p["abstract"] = ab
                        p["abstract_source"] = "s2"
                        p["match_method"] = "s2_" + (sid.split(":", 1)[0].lower() if sid else "id")
                        p["match_confidence"] = 1.0
                        enriched += 1; y_enriched += 1; resolved = True
                        break
                elif src == "homepage":
                    ab = abstract_sources.homepage_abstract(
                        p.get("url", ""), doi=p.get("doi", ""), refresh=refresh, logger=logger)
                    if ab:
                        p["abstract"] = ab
                        p["abstract_source"] = "homepage"
                        p["match_method"] = "homepage"
                        p["match_confidence"] = 1.0
                        enriched += 1; y_enriched += 1; resolved = True
                        break
                # 's2' and unimplemented sources are skipped
            if not resolved:
                unmatched += 1; y_unmatched += 1
            processed += 1
            if processed % SAVE_EVERY == 0:
                storage.save_conference_papers(venue_id, papers)

        coverage[yr] = {"enriched": y_enriched, "review": y_review, "unmatched": y_unmatched}
        storage.save_conference_papers(venue_id, papers)
        _log(logger, f"  {venue_id} {yr}: +{y_enriched} abstracts, "
                     f"{y_review} review, {y_unmatched} unmatched")

    with_abstract = sum(1 for p in papers if p.get("abstract"))
    return {
        "summary": _summary(conf),
        "sources": sources,
        "openalex_source_id": oa_source,
        "fuzzy_backend": abstract_sources._FUZZ_BACKEND,
        "coverage": coverage,
        "total": len(papers),
        "with_abstract": with_abstract,
        "enriched": enriched,
        "review": review,
        "unmatched": unmatched,
    }


# --------------------------------------------------------------------------- #
# Keyword filtering (Phase 4) — Boolean keyword string over the conference corpus
# --------------------------------------------------------------------------- #
_FILTER_STATE = paths.CONFERENCE_FILTER_DIR / "filter_state.json"
_FILTER_RELEVANT = paths.CONFERENCE_FILTER_DIR / "relevant.json"


def _combined_regex(patterns: list[str]):
    if not patterns:
        return None
    try:
        return re.compile("(" + "|".join(patterns) + ")", re.IGNORECASE)
    except re.error:
        return None


def _paper_text(p: dict) -> str:
    return " ".join([
        p.get("title", "") or "",
        p.get("abstract", "") or "",
        " ".join(p.get("keywords", []) or []),
    ])


def _save_filter(state: dict, relevant: list[dict]) -> None:
    paths.ensure_dirs()
    _FILTER_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    _FILTER_RELEVANT.write_text(json.dumps(relevant, ensure_ascii=False), encoding="utf-8")


def run_conference_filter(keyword_string: str, *, use_llm: bool = False) -> dict[str, Any]:
    """Compile the keyword string and find matching papers across all venues.

    Matching is over title + abstract + keywords. Titles alone already yield
    useful matches even before abstracts are enriched. Returns the relevant
    papers plus per-venue enumerated/relevant counts.
    """
    rules = build_highlight_rules(keyword_string or "", use_llm=use_llm)
    patterns = rules.get("patterns", []) or []
    rx = _combined_regex(patterns)

    metadata = storage.load_metadata()
    per_venue: dict[str, dict[str, Any]] = {}
    relevant: list[dict] = []
    for conf in metadata.get("conferences", []):
        cp = storage.load_conference_papers(conf["id"])
        if not cp:
            continue
        rel = 0
        for p in cp:
            if rx is not None and rx.search(_paper_text(p)):
                relevant.append(p)
                rel += 1
        per_venue[conf["id"]] = {
            "display": conf["display"], "enumerated": len(cp), "relevant": rel,
        }

    state = {
        "keyword_string": keyword_string,
        "terms": rules.get("terms", []),
        "patterns": patterns,
        "per_venue": per_venue,
        "total_relevant": len(relevant),
        "total": sum(v["enumerated"] for v in per_venue.values()),
        "computed_at": _now(),
    }
    _save_filter(state, relevant)
    return {**state, "relevant": relevant}


def get_conference_filter() -> dict[str, Any]:
    """Return the last computed filter (state + relevant papers), or an empty shell."""
    if not _FILTER_STATE.exists():
        return {"keyword_string": "", "terms": [], "patterns": [], "per_venue": {},
                "total_relevant": 0, "total": 0, "computed_at": None, "relevant": []}
    state = json.loads(_FILTER_STATE.read_text(encoding="utf-8"))
    relevant = json.loads(_FILTER_RELEVANT.read_text(encoding="utf-8")) if _FILTER_RELEVANT.exists() else []
    return {**state, "relevant": relevant}
