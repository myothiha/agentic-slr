"""Page-count filter — an optional stage between deduplication and screening.

The reviewer specifies a page-count range (e.g. "at least 8 pages"); papers
outside the range are excluded before they reach LLM screening. Page counts are
derived from each paper's raw record (see parsers.extract_pages). Papers whose
page count cannot be determined are "unknown" and are kept by default (so they
can be judged manually) unless `exclude_unknown` is set. Per-paper manual
overrides take precedence over the rule.

State persists to data/02b_page_filter/page_filter_state.json.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from . import dedup_service, parsers, paths

_lock = threading.Lock()

STATE_FILE = paths.PAGE_FILTER_DIR / "page_filter_state.json"

DEFAULT_CONFIG = {"min_pages": None, "max_pages": None, "exclude_unknown": False}

_DISPLAY_FIELDS = ("index", "database", "database_id", "title", "authors", "year", "doi")


def _ensure_dir() -> None:
    paths.PAGE_FILTER_DIR.mkdir(parents=True, exist_ok=True)


def clear() -> None:
    """Delete page-filter state (used for a cascade reset)."""
    with _lock:
        if STATE_FILE.exists():
            STATE_FILE.unlink()


def _load() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"config": dict(DEFAULT_CONFIG), "overrides": {}}
    text = STATE_FILE.read_text(encoding="utf-8").strip()
    if not text:
        return {"config": dict(DEFAULT_CONFIG), "overrides": {}}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"config": dict(DEFAULT_CONFIG), "overrides": {}}
    cfg = {**DEFAULT_CONFIG, **(data.get("config") or {})}
    return {"config": cfg, "overrides": data.get("overrides") or {}}


def _save(state: dict[str, Any]) -> None:
    _ensure_dir()
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    with _lock:
        with STATE_FILE.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)


def is_active(state: dict[str, Any] | None = None) -> bool:
    s = state or _load()
    c = s["config"]
    return (
        c.get("min_pages") is not None
        or c.get("max_pages") is not None
        or bool(c.get("exclude_unknown"))
        or bool(s.get("overrides"))
    )


def _classify(paper: dict[str, Any], cfg: dict[str, Any], overrides: dict[str, Any]):
    """Return (page_count, start, end, status, reason)."""
    pages = parsers.extract_pages(paper.get("raw"))
    count = pages["count"]
    ov = overrides.get(paper.get("index"))
    if ov == "include":
        return count, pages["start"], pages["end"], "included", "manual override"
    if ov == "exclude":
        return count, pages["start"], pages["end"], "excluded", "manual override"
    if count is None:
        if cfg.get("exclude_unknown"):
            return None, pages["start"], pages["end"], "excluded", "unknown page count"
        return None, pages["start"], pages["end"], "unknown", "unknown page count"
    lo, hi = cfg.get("min_pages"), cfg.get("max_pages")
    if lo is not None and count < lo:
        return count, pages["start"], pages["end"], "excluded", f"< {lo} pages"
    if hi is not None and count > hi:
        return count, pages["start"], pages["end"], "excluded", f"> {hi} pages"
    return count, pages["start"], pages["end"], "included", "in range"


def get() -> dict[str, Any]:
    """Full payload for the Page Filter page."""
    report = dedup_service.get_report()
    has_source = report.get("has_run", False) and report.get("kept_count", 0) > 0
    state = _load()
    cfg, overrides = state["config"], state["overrides"]

    if not has_source:
        return {"has_source": False, "config": cfg, "papers": [], "counts": _counts([])}

    papers = []
    for p in dedup_service.kept_papers():
        count, start, end, status, reason = _classify(p, cfg, overrides)
        row = {k: p.get(k) for k in _DISPLAY_FIELDS}
        row.update({
            "page_count": count,
            "page_start": start,
            "page_end": end,
            "status": status,
            "reason": reason,
            "override": overrides.get(p.get("index")),
        })
        papers.append(row)
    return {
        "has_source": True,
        "config": cfg,
        "active": is_active(state),
        "papers": papers,
        "counts": _counts(papers),
    }


def _counts(papers: list[dict[str, Any]]) -> dict[str, int]:
    c = {"total": len(papers), "included": 0, "excluded": 0, "unknown": 0}
    for p in papers:
        c[p["status"]] = c.get(p["status"], 0) + 1
    return c


def set_config(
    min_pages: Optional[int], max_pages: Optional[int], exclude_unknown: bool
) -> dict[str, Any]:
    state = _load()
    state["config"] = {
        "min_pages": min_pages,
        "max_pages": max_pages,
        "exclude_unknown": bool(exclude_unknown),
    }
    _save(state)
    return get()


def set_override(index: str, mode: str) -> dict[str, Any]:
    if mode not in ("include", "exclude", "auto"):
        raise ValueError("mode must be 'include', 'exclude', or 'auto'")
    state = _load()
    if mode == "auto":
        state["overrides"].pop(index, None)
    else:
        state["overrides"][index] = mode
    _save(state)
    return get()


def kept_papers() -> list[dict[str, Any]]:
    """Full dedup-kept paper dicts that pass the page filter (screening source).

    When the filter is inactive, this is simply all deduplicated kept papers.
    """
    state = _load()
    if not is_active(state):
        return dedup_service.kept_papers()
    cfg, overrides = state["config"], state["overrides"]
    out = []
    for p in dedup_service.kept_papers():
        _, _, _, status, _ = _classify(p, cfg, overrides)
        if status in ("included", "unknown"):
            out.append(p)
    return out
