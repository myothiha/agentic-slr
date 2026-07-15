"""Orchestration + persistence for Phase 2 deduplication.

Reads raw papers from data/01_raw_paper_list, runs the deduplication agent, and
writes results to data/02_deduplication/:

  * dedup_state.json   — full annotated list (the source of truth, supports restore)
  * deduplicated.json  — the final kept dataset (unique + restored papers)
  * report.json        — matrix + summary + run metadata

Restoring a duplicate flips its status to "restored" and rewrites the kept
dataset + report, preserving full traceability.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from agents.deduplication import run_deduplication

from . import paths, storage

_lock = threading.Lock()

STATE_FILE = paths.DEDUP_DIR / "dedup_state.json"
DEDUP_FILE = paths.DEDUP_DIR / "deduplicated.json"
REPORT_FILE = paths.DEDUP_DIR / "report.json"


def _ensure_dir() -> None:
    paths.DEDUP_DIR.mkdir(parents=True, exist_ok=True)


def clear() -> None:
    """Delete all deduplication state files (used for a cascade reset)."""
    with _lock:
        for fp in (STATE_FILE, DEDUP_FILE, REPORT_FILE):
            if fp.exists():
                fp.unlink()


def _kept(annotated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in annotated if p.get("dedup_status") in ("unique", "restored")]


def _write_all(state: dict[str, Any]) -> None:
    _ensure_dir()
    with _lock:
        with STATE_FILE.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        with DEDUP_FILE.open("w", encoding="utf-8") as f:
            json.dump(_kept(state["annotated"]), f, indent=2, ensure_ascii=False)
        report = {
            "run_at": state["run_at"],
            "priority_order": state["priority_order"],
            "matrix": state["matrix"],
            "summary": state["summary"],
            "restored_count": sum(
                1 for p in state["annotated"] if p.get("dedup_status") == "restored"
            ),
        }
        with REPORT_FILE.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)


def run(priority_order: Optional[list[str]] = None) -> dict[str, Any]:
    """Run (or re-run) deduplication over the current raw paper lists."""
    metadata = storage.load_metadata()
    databases = metadata["databases"]
    papers_by_db = {db["id"]: storage.load_papers(db["id"]) for db in databases}

    result = run_deduplication(databases, papers_by_db, priority_order)
    state = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "priority_order": result["priority_order"],
        "annotated": result["annotated"],
        "matrix": result["matrix"],
        "summary": result["summary"],
    }
    _write_all(state)
    return get_report()


def reconcile() -> Optional[dict[str, Any]]:
    """Re-run deduplication over the *current* databases after the inputs change.

    Used when a database's papers are added or emptied: because deduplication is
    deterministic (DOI/normalised-title based), re-running yields the same result
    for every unchanged database, while papers from an emptied database simply
    drop out and any paper that was only a duplicate *of* a removed paper becomes
    kept again. The chosen priority order and manual "restore" overrides are
    preserved. Downstream stages (page filter, screening, full-text, tagging)
    reconcile themselves against the new kept set, keeping their per-paper
    decisions by index. No-op if deduplication has never been run.
    """
    state = load_state()
    if state is None:
        return None
    priority = state.get("priority_order")
    restored = {
        p["index"] for p in state["annotated"] if p.get("dedup_status") == "restored"
    }
    run(priority_order=priority)
    if restored:
        new = load_state()
        touched = False
        for p in new["annotated"]:
            # Re-apply a manual restore only where the paper is still a detected
            # duplicate (if its original was removed it is already kept).
            if p.get("index") in restored and p.get("duplicate_of") is not None:
                p["dedup_status"] = "restored"
                touched = True
        if touched:
            _write_all(new)
    return get_report()


def load_state() -> Optional[dict[str, Any]]:
    if not STATE_FILE.exists():
        return None
    text = STATE_FILE.read_text(encoding="utf-8").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and "annotated" in data else None


def get_report() -> dict[str, Any]:
    """Return the full review payload: matrix, summary, and the duplicate list."""
    state = load_state()
    if state is None:
        return {"has_run": False}
    annotated = state["annotated"]
    duplicates = [p for p in annotated if p.get("dedup_status") == "duplicate"]
    restored = [p for p in annotated if p.get("dedup_status") == "restored"]

    # Provide the full matched-original records (keyed by index) so the UI can
    # show the removed paper and its match side by side.
    by_index = {p.get("index"): p for p in annotated}
    originals: dict[str, Any] = {}
    for d in duplicates + restored:
        oi = (d.get("duplicate_of") or {}).get("index")
        if oi and oi in by_index:
            originals[oi] = by_index[oi]

    return {
        "has_run": True,
        "run_at": state["run_at"],
        "priority_order": state["priority_order"],
        "matrix": state["matrix"],
        "summary": state["summary"],
        "kept_count": len(_kept(annotated)),
        "duplicates": duplicates,
        "restored": restored,
        "originals": originals,
    }


def set_status(index: str, status: str) -> dict[str, Any]:
    """Restore ('restored') or re-remove ('duplicate') a paper by its index."""
    if status not in ("restored", "duplicate"):
        raise ValueError("status must be 'restored' or 'duplicate'")
    state = load_state()
    if state is None:
        raise ValueError("Deduplication has not been run yet.")
    found = False
    for p in state["annotated"]:
        if p.get("index") == index:
            # Only papers that were detected as duplicates can be toggled.
            if p.get("duplicate_of") is None:
                raise ValueError("This paper is an original, not a duplicate.")
            p["dedup_status"] = status
            found = True
            break
    if not found:
        raise ValueError(f"Paper not found: {index}")
    _write_all(state)
    return get_report()


def kept_papers() -> list[dict[str, Any]]:
    state = load_state()
    return _kept(state["annotated"]) if state else []
