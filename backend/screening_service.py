"""Orchestration + persistence for Phase 3 abstract/title screening.

Screening operates on the deduplicated kept set (data/02_deduplication/). Each
kept paper gets a screening record; decisions persist to
data/03_abstract_title_screening/screening_state.json.

Modification trail
------------------
  pending        — no decision yet
  llm_labeled    — the AI suggested a label, user has not acted
  user_confirmed — user accepted a label equal to the AI suggestion
  user_modified  — user set a label different from the AI suggestion
                   (or set one when there was no AI suggestion)
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from agents.abstract_title_screening import LABELS, screen_paper

from . import dedup_service, page_filter_service, parsers, paths, storage

_lock = threading.Lock()

STATE_FILE = paths.SCREENING_DIR / "screening_state.json"
DECISIONS_FILE = paths.SCREENING_DIR / "screening_decisions.json"

_PAPER_FIELDS = (
    "index", "database", "database_id", "title", "authors", "year",
    "abstract", "keywords", "doi", "venue", "url",
)


def _ensure_dir() -> None:
    paths.SCREENING_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _page_fields(paper: dict[str, Any]) -> dict[str, Any]:
    """Derive page metadata from the source paper's raw record."""
    pages = parsers.extract_pages(paper.get("raw"))
    return {
        "page_count": pages["count"],
        "page_start": pages["start"],
        "page_end": pages["end"],
    }


def _blank_record(paper: dict[str, Any]) -> dict[str, Any]:
    rec = {k: paper.get(k) for k in _PAPER_FIELDS}
    rec.update(_page_fields(paper))
    rec.update({
        "llm_label": None,
        "llm_reasoning": "",
        "label": None,
        "user_comment": "",
        "status": "pending",
        "screened_at": None,
    })
    return rec


def _load_raw_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"records": {}}
    text = STATE_FILE.read_text(encoding="utf-8").strip()
    if not text:
        return {"records": {}}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"records": {}}
    if isinstance(data, dict) and isinstance(data.get("records"), dict):
        return data
    return {"records": {}}


def _save_state(state: dict[str, Any]) -> None:
    _ensure_dir()
    with _lock:
        with STATE_FILE.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        # A flat decisions export for convenience / downstream stages.
        decisions = [
            {
                "index": r["index"], "label": r["label"], "status": r["status"],
                "llm_label": r["llm_label"], "user_comment": r["user_comment"],
            }
            for r in state["records"].values()
        ]
        with DECISIONS_FILE.open("w", encoding="utf-8") as f:
            json.dump(decisions, f, indent=2, ensure_ascii=False)


def sync() -> dict[str, Any]:
    """Reconcile screening records with the current deduplicated kept set.

    New kept papers get fresh records; decisions for papers that remain are
    preserved; records for papers no longer in the kept set are dropped.
    """
    # Source = papers that pass the page filter (all dedup-kept when inactive).
    kept = page_filter_service.kept_papers()
    state = _load_raw_state()
    old = state["records"]
    new_records: dict[str, Any] = {}
    for paper in kept:
        idx = paper.get("index")
        if not idx:
            continue
        if idx in old:
            rec = old[idx]
            # Refresh the paper fields in case ingestion data changed.
            for k in _PAPER_FIELDS:
                rec[k] = paper.get(k)
            rec.update(_page_fields(paper))  # backfill/refresh page metadata
            new_records[idx] = rec
        else:
            new_records[idx] = _blank_record(paper)
    state["records"] = new_records
    state["synced_at"] = _now()
    _save_state(state)
    return state


def _ordered_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    return list(state["records"].values())


def get_screening() -> dict[str, Any]:
    """Return the screening payload (auto-synced with the deduplicated set)."""
    dedup = dedup_service.get_report()
    has_source = dedup.get("has_run", False) and dedup.get("kept_count", 0) > 0
    if not has_source:
        return {"has_source": False, "papers": [], "counts": _counts([])}
    state = sync()
    papers = _ordered_records(state)
    return {"has_source": True, "papers": papers, "counts": _counts(papers)}


def _counts(papers: list[dict[str, Any]]) -> dict[str, Any]:
    by_label = {lab: 0 for lab in LABELS}
    by_status = {"pending": 0, "llm_labeled": 0, "user_confirmed": 0, "user_modified": 0}
    decided = 0
    for p in papers:
        if p.get("label") in by_label:
            by_label[p["label"]] += 1
            decided += 1
        st = p.get("status", "pending")
        if st in by_status:
            by_status[st] += 1
    return {
        "total": len(papers),
        "decided": decided,
        "pending": len(papers) - decided,
        "by_label": by_label,
        "by_status": by_status,
    }


def _get_record(index: str) -> tuple[dict[str, Any], dict[str, Any]]:
    state = _load_raw_state()
    rec = state["records"].get(index)
    if rec is None:
        # Attempt a sync in case it is a new kept paper.
        state = sync()
        rec = state["records"].get(index)
    if rec is None:
        raise ValueError(f"Paper not found in screening set: {index}")
    return state, rec


def suggest(index: str) -> dict[str, Any]:
    """Run the LLM agent for one paper and store its suggestion."""
    state, rec = _get_record(index)
    metadata = storage.load_metadata()
    result = screen_paper(
        rec,
        metadata.get("inclusion_criteria", []),
        metadata.get("exclusion_criteria", []),
        metadata.get("research_questions", ""),
    )
    rec["llm_label"] = result.get("label")
    rec["llm_reasoning"] = result.get("reasoning", "")
    # Only advance the trail to llm_labeled if the user hasn't decided yet.
    if rec["status"] == "pending" and rec["llm_label"]:
        rec["status"] = "llm_labeled"
    _save_state(state)
    return {"record": rec, "available": result.get("available", False)}


def suggest_batch(limit: int = 25) -> dict[str, Any]:
    """Run the LLM agent over up to `limit` papers that have no AI label yet.

    Designed to be called repeatedly by the frontend so thousands of papers can
    be processed in chunks without a single long-running request. Stops early if
    the LLM is unavailable (missing key / network) to avoid hammering.
    """
    state = sync()
    metadata = storage.load_metadata()
    inclusion = metadata.get("inclusion_criteria", [])
    exclusion = metadata.get("exclusion_criteria", [])
    rqs = metadata.get("research_questions", "")

    pending = [r for r in state["records"].values() if not r.get("llm_label")]
    target = pending[:max(1, limit)]

    processed = labeled = failed = 0
    unavailable = False
    message = ""
    for rec in target:
        result = screen_paper(rec, inclusion, exclusion, rqs)
        if not result.get("available"):
            unavailable = True
            message = result.get("reasoning", "AI suggestion unavailable.")
            break
        rec["llm_label"] = result.get("label")
        rec["llm_reasoning"] = result.get("reasoning", "")
        if rec["status"] == "pending" and rec["llm_label"]:
            rec["status"] = "llm_labeled"
        processed += 1
        if result.get("label"):
            labeled += 1
        else:
            failed += 1

    _save_state(state)
    remaining = sum(1 for r in state["records"].values() if not r.get("llm_label"))
    total = len(state["records"])
    return {
        "processed": processed,
        "labeled": labeled,
        "failed": failed,
        "remaining": remaining,
        "total": total,
        "done": remaining == 0 or unavailable,
        "unavailable": unavailable,
        "message": message,
    }


def set_label(index: str, label: str, comment: Optional[str] = None) -> dict[str, Any]:
    if label not in LABELS:
        raise ValueError(f"label must be one of {LABELS}")
    state, rec = _get_record(index)
    rec["label"] = label
    if comment is not None:
        rec["user_comment"] = comment
    # Modification trail relative to the AI suggestion.
    if rec.get("llm_label") and label == rec["llm_label"]:
        rec["status"] = "user_confirmed"
    else:
        rec["status"] = "user_modified"
    rec["screened_at"] = _now()
    _save_state(state)
    return rec


def set_comment(index: str, comment: str) -> dict[str, Any]:
    state, rec = _get_record(index)
    rec["user_comment"] = comment
    _save_state(state)
    return rec


def reset(index: str) -> dict[str, Any]:
    """Clear a paper's decision back to pending (keeps any AI suggestion)."""
    state, rec = _get_record(index)
    rec["label"] = None
    rec["screened_at"] = None
    rec["status"] = "llm_labeled" if rec.get("llm_label") else "pending"
    _save_state(state)
    return rec
