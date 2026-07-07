"""Phase 5 — user-defined keyword extraction + manual categorization.

Supports MULTIPLE independent *dimensions* (e.g. "E-commerce task",
"LLM technique"). Papers are stored ONCE in a shared list; each paper carries a
per-dimension tag field so the same 270 papers can be multi-filtered across
dimensions.

State persists to data/04_keyword_tagging/tagging_state.json:

    {
      "dimensions": [
        {"field": "ecommerce_task", "name": "...", "description": "...",
         "preferred": [tag, ...], "tag_descriptions": {tag: desc},
         "groups": [ {"id","name","members":[tag,...]} ], "updated_at": "..."}
      ],
      "papers": {
        "<index>": {
          "index","title","year","database","abstract",
          "tags":     {"ecommerce_task": [...], "llm_technique": [...]},
          "evidence": {"ecommerce_task": {tag: sentence}, ...},
          "processed": {"ecommerce_task": "<iso>", ...}
        }
      }
    }

Extraction only processes screening 'Include' papers, writes into the paper's
tag field for that dimension, and SKIPS papers already processed for that
dimension (unless force=True). Groups map member tags to a canonical category
*name* per dimension; ungrouped tags act as standalone categories.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from agents.keyword_extraction import extract_keywords, normalize_tag
from agents.keyword_suggester import describe_tags
from agents.keyword_suggester import suggest as suggest_definition
from agents.llm import get_chat_model, provider_name

from . import paths, screening_service

_lock = threading.Lock()

STATE_FILE = paths.TAGGING_DIR / "tagging_state.json"

MAX_TAGS = 50  # safety ceiling only; the agent is told there is no fixed limit

_BASE_FIELDS = ("index", "title", "year", "database", "abstract")


# --------------------------------------------------------------------------- #
# Persistence (+ migration)
# --------------------------------------------------------------------------- #
def _ensure_dir() -> None:
    paths.TAGGING_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _blank_state() -> dict[str, Any]:
    return {"dimensions": [], "papers": {}}


def _migrate_legacy_single(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade the very old {definition, papers, groups} shape to dimensions."""
    if "dimensions" in data:
        return data
    definition = data.get("definition") or {}
    name = (definition.get("name") or "").strip()
    papers = data.get("papers") or {}
    groups = data.get("groups") or []
    if not name and not papers and not groups:
        return _blank_state()
    field = _slug(name or "dimension", existing=set())
    return {
        "dimensions": [{
            "field": field,
            "name": name or "Keyword",
            "description": definition.get("description", ""),
            "updated_at": definition.get("updated_at"),
            "papers": papers,
            "groups": groups,
        }],
    }


def _migrate_to_unified(data: dict[str, Any]) -> dict[str, Any]:
    """Move per-dimension `papers` into a single shared `papers` map with
    per-dimension tag fields."""
    data.setdefault("papers", {})
    for dim in data.get("dimensions", []):
        dim_papers = dim.pop("papers", None)
        if not dim_papers:
            continue
        field = dim["field"]
        for idx, rec in dim_papers.items():
            p = data["papers"].setdefault(idx, {
                "index": rec.get("index", idx),
                "title": rec.get("title", ""),
                "year": rec.get("year"),
                "database": rec.get("database", ""),
                "abstract": rec.get("abstract", ""),
                "tags": {},
                "evidence": {},
                "processed": {},
            })
            p.setdefault("tags", {})[field] = rec.get("tags", [])
            p.setdefault("evidence", {})[field] = rec.get("evidence", {})
            p.setdefault("processed", {})[field] = rec.get("processed_at") or _now()
    return data


def _load() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return _blank_state()
    text = STATE_FILE.read_text(encoding="utf-8").strip()
    if not text:
        return _blank_state()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _blank_state()
    data = _migrate_legacy_single(data)
    data = _migrate_to_unified(data)
    data.setdefault("dimensions", [])
    data.setdefault("papers", {})
    for d in data["dimensions"]:
        d.setdefault("preferred", [])
        d.setdefault("tag_descriptions", {})
        d.setdefault("groups", [])
    for p in data["papers"].values():
        p.setdefault("tags", {})
        p.setdefault("evidence", {})
        p.setdefault("processed", {})
    return data


def _save(state: dict[str, Any]) -> None:
    _ensure_dir()
    with _lock:
        with STATE_FILE.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)


def snapshot() -> dict[str, Any]:
    """Read-only full state (papers + dimensions), for the analysis layer."""
    return _load()


def clear() -> None:
    """Delete all tagging state (used for a cascade reset)."""
    with _lock:
        if STATE_FILE.exists():
            STATE_FILE.unlink()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _slug(name: str, existing: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_") or "dimension"
    field = base
    n = 2
    while field in existing:
        field = f"{base}_{n}"
        n += 1
    return field


def _find(state: dict[str, Any], field: str) -> Optional[dict[str, Any]]:
    return next((d for d in state["dimensions"] if d["field"] == field), None)


def _require(state: dict[str, Any], field: str) -> dict[str, Any]:
    dim = _find(state, field)
    if dim is None:
        raise ValueError(f"Unknown dimension: {field}")
    return dim


def _dim_papers(state: dict[str, Any], field: str) -> list[dict[str, Any]]:
    """Papers that have been tagged for this dimension."""
    return [p for p in state["papers"].values() if field in p.get("tags", {})]


def _tag_counts(state: dict[str, Any], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in state["papers"].values():
        for tag in p.get("tags", {}).get(field, []):
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def _grouped_member_map(dim: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for g in dim["groups"]:
        for m in g.get("members", []):
            out[m] = g["id"]
    return out


def _clean_list(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values or []:
        norm = normalize_tag(v)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _dim_summary(state: dict[str, Any], dim: dict[str, Any], include_total: int) -> dict[str, Any]:
    return {
        "field": dim["field"],
        "name": dim["name"],
        "description": dim.get("description", ""),
        "preferred": dim.get("preferred", []),
        "updated_at": dim.get("updated_at"),
        "processed_total": len(_dim_papers(state, dim["field"])),
        "unique_tags": len(_tag_counts(state, dim["field"])),
        "group_count": len(dim["groups"]),
        "include_total": include_total,
    }


# --------------------------------------------------------------------------- #
# Dimension CRUD
# --------------------------------------------------------------------------- #
def list_dimensions() -> dict[str, Any]:
    state = _load()
    include_total = len(screening_service.included_papers())
    return {
        "llm_available": get_chat_model() is not None,
        "provider": provider_name(),
        "include_total": include_total,
        "include_source": screening_service.include_source(),
        "dimensions": [_dim_summary(state, d, include_total) for d in state["dimensions"]],
    }


def add_dimension(name: str, description: str = "", preferred: Any = None) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Dimension name is required.")
    state = _load()
    existing = {d["field"] for d in state["dimensions"]}
    dim = {
        "field": _slug(name, existing),
        "name": name,
        "description": (description or "").strip(),
        "preferred": _clean_list(preferred),
        "tag_descriptions": {},
        "groups": [],
        "updated_at": _now(),
    }
    state["dimensions"].append(dim)
    _save(state)
    return _dim_summary(state, dim, len(screening_service.included_papers()))


def update_dimension(
    field: str,
    name: Optional[str],
    description: Optional[str],
    preferred: Any = None,
    tag_descriptions: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    state = _load()
    dim = _require(state, field)
    if name is not None:
        new_name = name.strip()
        if not new_name:
            raise ValueError("Dimension name cannot be empty.")
        dim["name"] = new_name
    if description is not None:
        dim["description"] = description.strip()
    if preferred is not None:
        dim["preferred"] = _clean_list(preferred)
    if tag_descriptions is not None:
        for k, v in tag_descriptions.items():
            tag = normalize_tag(k)
            if tag:
                dim["tag_descriptions"][tag] = str(v or "").strip()
    dim["updated_at"] = _now()
    _save(state)
    return _dim_summary(state, dim, len(screening_service.included_papers()))


def delete_dimension(field: str) -> None:
    state = _load()
    before = len(state["dimensions"])
    state["dimensions"] = [d for d in state["dimensions"] if d["field"] != field]
    if len(state["dimensions"]) == before:
        raise ValueError("Dimension not found.")
    # Drop this dimension's tags from the shared papers; remove papers left empty.
    for idx in list(state["papers"].keys()):
        p = state["papers"][idx]
        p.get("tags", {}).pop(field, None)
        p.get("evidence", {}).pop(field, None)
        p.get("processed", {}).pop(field, None)
        if not p.get("tags"):
            del state["papers"][idx]
    _save(state)


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def _persist_progress(field: str, papers: dict[str, Any], tag_descriptions: dict[str, str]) -> None:
    """Save extraction progress WITHOUT clobbering concurrent edits (groups,
    other dimensions' tags). Re-reads the file and updates only this dimension's
    tag field on each paper, plus this dimension's tag_descriptions."""
    state = _load()
    for idx, src in papers.items():
        if field not in src.get("tags", {}):
            continue
        fp = state["papers"].setdefault(idx, {
            **{k: src.get(k) for k in _BASE_FIELDS},
            "tags": {}, "evidence": {}, "processed": {},
        })
        for k in _BASE_FIELDS:
            fp[k] = src.get(k)
        fp.setdefault("tags", {})[field] = src["tags"][field]
        fp.setdefault("evidence", {})[field] = src.get("evidence", {}).get(field, {})
        fp.setdefault("processed", {})[field] = src.get("processed", {}).get(field, _now())
    dim = _find(state, field)
    if dim is not None:
        merged = dict(dim.get("tag_descriptions", {}))
        merged.update(tag_descriptions or {})
        dim["tag_descriptions"] = merged
    _save(state)


def _describe_missing_tags(state: dict[str, Any], dim: dict[str, Any]) -> None:
    field = dim["field"]
    seen: set[str] = set()
    for p in state["papers"].values():
        seen.update(p.get("tags", {}).get(field, []))
    missing = [t for t in seen if not dim["tag_descriptions"].get(t)]
    if not missing:
        return
    dres = describe_tags(dim["name"], dim.get("description", ""), missing)
    for t, d in dres.get("descriptions", {}).items():
        if d:
            dim["tag_descriptions"][t] = d


def run_extraction(field: str, limit: Optional[int] = None, force: bool = False) -> dict[str, Any]:
    state = _load()
    dim = _require(state, field)
    description = dim.get("description", "")

    include = screening_service.included_papers()
    if not description.strip():
        return _summary(state, dim, include, 0, 0, 0, 0,
                        "Set a description for this dimension first.",
                        available=get_chat_model() is not None)

    model_name = provider_name()
    papers = state["papers"]
    processed = tagged = skipped = failed = 0
    unavailable = False
    errors: list[str] = []

    descs = dim.get("tag_descriptions", {})
    preferred_payload = [
        {"tag": t, "description": descs.get(t, "")} for t in dim.get("preferred", [])
    ]

    for paper in include:
        idx = paper.get("index")
        if not idx:
            continue
        already = field in papers.get(idx, {}).get("tags", {})
        if not force and already:
            skipped += 1
            continue
        if limit is not None and processed >= limit:
            break

        res = extract_keywords(paper, description, preferred=preferred_payload, max_tags=MAX_TAGS)
        if not res.get("available"):
            unavailable = True
            failed += 1
            err = res.get("error") or "unknown error"
            if err not in errors:
                errors.append(err)
            if "not configured" in err.lower():
                break
            if processed == 0 and failed >= 5:
                break
            continue

        items = res.get("items", [])
        tags = [it["tag"] for it in items]
        evidence = {it["tag"]: it["evidence"] for it in items if it.get("evidence")}
        p = papers.setdefault(idx, {
            "index": idx, "title": paper.get("title", ""), "year": paper.get("year"),
            "database": paper.get("database", ""), "abstract": paper.get("abstract", ""),
            "tags": {}, "evidence": {}, "processed": {},
        })
        # Refresh base fields (in case source metadata changed).
        p["index"] = idx
        p["title"] = paper.get("title", "")
        p["year"] = paper.get("year")
        p["database"] = paper.get("database", "")
        p["abstract"] = paper.get("abstract", "")
        p.setdefault("tags", {})[field] = tags
        p.setdefault("evidence", {})[field] = evidence
        p.setdefault("processed", {})[field] = _now()
        processed += 1
        if tags:
            tagged += 1
        if processed % 20 == 0:
            _describe_missing_tags(state, dim)
            _persist_progress(field, papers, dim["tag_descriptions"])

    if processed > 0:
        _describe_missing_tags(state, dim)

    _persist_progress(field, papers, dim["tag_descriptions"])
    note = None
    if errors:
        first = errors[0]
        note = (f"No papers were tagged — every attempt failed. First error: {first}"
                if processed == 0 else f"{failed} paper(s) failed. First error: {first}")
    return _summary(state, dim, include, processed, tagged, skipped, failed, note,
                    available=not unavailable or processed > 0, errors=errors[:3])


def _summary(state, dim, include, processed, tagged, skipped, failed, note, available, errors=None):
    return {
        "field": dim["field"],
        "processed": processed,
        "tagged": tagged,
        "skipped": skipped,
        "failed": failed,
        "include_total": len(include),
        "already_processed": len(_dim_papers(state, dim["field"])),
        "unique_tags": len(_tag_counts(state, dim["field"])),
        "llm_available": available,
        "note": note,
        "errors": errors or [],
    }


# --------------------------------------------------------------------------- #
# Read models
# --------------------------------------------------------------------------- #
def get_state(field: str) -> dict[str, Any]:
    state = _load()
    dim = _require(state, field)
    include = screening_service.included_papers()
    counts = _tag_counts(state, field)
    descs = dim.get("tag_descriptions", {})
    pool = [
        {"tag": t, "count": c, "description": descs.get(t, "")}
        for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {
        "field": dim["field"],
        "name": dim["name"],
        "description": dim.get("description", ""),
        "preferred": dim.get("preferred", []),
        "tag_descriptions": descs,
        "updated_at": dim.get("updated_at"),
        "llm_available": get_chat_model() is not None,
        "provider": provider_name(),
        "include_total": len(include),
        "include_source": screening_service.include_source(),
        "processed_total": len(_dim_papers(state, field)),
        "unique_tags": len(counts),
        "tag_pool": pool,
        "groups": dim["groups"],
    }


def get_papers(field: str) -> list[dict[str, Any]]:
    """Processed papers for one dimension, in the per-dimension shape the
    extraction UI expects (tags = list, evidence = map)."""
    state = _load()
    _require(state, field)
    out = []
    for p in state["papers"].values():
        if field not in p.get("tags", {}):
            continue
        out.append({
            "index": p.get("index"),
            "title": p.get("title", ""),
            "year": p.get("year"),
            "database": p.get("database", ""),
            "abstract": p.get("abstract", ""),
            "tags": p["tags"][field],
            "evidence": p.get("evidence", {}).get(field, {}),
        })
    return out


def suggest(field: str, target: str = "description", name: Optional[str] = None,
            description: Optional[str] = None) -> dict[str, Any]:
    state = _load()
    dim = _require(state, field)
    use_name = name if name is not None else dim["name"]
    use_desc = description if description is not None else dim.get("description", "")
    return suggest_definition(use_name, use_desc, screening_service.included_papers(), target)


# --------------------------------------------------------------------------- #
# Groups (per dimension)
# --------------------------------------------------------------------------- #
def _clean_members(members: Any) -> list[str]:
    return _clean_list(members)


def _detach_members(dim: dict[str, Any], members: list[str], keep_id: str | None) -> None:
    member_set = set(members)
    for g in dim["groups"]:
        if g["id"] == keep_id:
            continue
        g["members"] = [m for m in g.get("members", []) if m not in member_set]


def add_group(field: str, name: str, members: Any) -> dict[str, Any]:
    state = _load()
    dim = _require(state, field)
    group = {"id": "grp_" + uuid.uuid4().hex[:8], "name": (name or "").strip(),
             "members": _clean_members(members)}
    if not group["name"]:
        raise ValueError("Group name is required.")
    _detach_members(dim, group["members"], keep_id=group["id"])
    dim["groups"].append(group)
    _save(state)
    return group


def update_group(field: str, group_id: str, name: Optional[str], members: Any) -> dict[str, Any]:
    state = _load()
    dim = _require(state, field)
    group = next((g for g in dim["groups"] if g["id"] == group_id), None)
    if group is None:
        raise ValueError("Group not found.")
    if name is not None:
        new_name = name.strip()
        if not new_name:
            raise ValueError("Group name cannot be empty.")
        group["name"] = new_name
    if members is not None:
        group["members"] = _clean_members(members)
        _detach_members(dim, group["members"], keep_id=group_id)
    _save(state)
    return group


def delete_group(field: str, group_id: str) -> None:
    state = _load()
    dim = _require(state, field)
    before = len(dim["groups"])
    dim["groups"] = [g for g in dim["groups"] if g["id"] != group_id]
    if len(dim["groups"]) == before:
        raise ValueError("Group not found.")
    _save(state)


# --------------------------------------------------------------------------- #
# Category statistics (per dimension)
# --------------------------------------------------------------------------- #
def category_stats(field: str) -> dict[str, Any]:
    state = _load()
    dim = _require(state, field)
    papers = _dim_papers(state, field)
    tag_counts = _tag_counts(state, field)

    group_categories = []
    for g in dim["groups"]:
        members = g.get("members", [])
        member_set = set(members)
        paper_count = sum(1 for p in papers if member_set.intersection(p["tags"].get(field, [])))
        subs = [{"tag": m, "paper_count": tag_counts.get(m, 0)} for m in members]
        subs.sort(key=lambda s: (-s["paper_count"], s["tag"]))
        group_categories.append({
            "id": g["id"], "name": g["name"], "kind": "group",
            "paper_count": paper_count, "members": subs,
        })
    group_categories.sort(key=lambda c: (-c["paper_count"], c["name"]))

    grouped = set(_grouped_member_map(dim).keys())
    standalone = [
        {"tag": t, "name": t, "kind": "standalone", "paper_count": c}
        for t, c in tag_counts.items() if t not in grouped
    ]
    standalone.sort(key=lambda c: (-c["paper_count"], c["name"]))

    return {
        "field": dim["field"], "name": dim["name"],
        "processed_total": len(papers), "unique_tags": len(tag_counts),
        "groups": group_categories, "standalone": standalone,
        "category_total": len(group_categories) + len(standalone),
    }
