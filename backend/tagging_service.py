"""Phase 5 — user-defined keyword extraction + manual categorization.

Supports MULTIPLE independent *dimensions* (e.g. "E-commerce task",
"LLM technique"). Each dimension is fully self-contained: its own description,
stable field key (slug, e.g. ``ecommerce_task``), per-paper tags + evidence,
unique tag pool, and manual groups. Extraction and grouping run per dimension
and never affect another dimension.

State persists to data/04_keyword_tagging/tagging_state.json:

    {
      "dimensions": [
        {
          "field": "ecommerce_task",          # stable id / per-paper tag field
          "name": "E-commerce task",
          "description": "...",
          "updated_at": "...",
          "papers": {
            "<index>": {"index","title","year","database","abstract",
                        "tags":[...], "evidence": {tag: sentence},
                        "processed_at","model"}
          },
          "groups": [ {"id","name","members":[tag,...]} ]
        }
      ]
    }

Extraction only processes screening 'Include' papers, SKIPS papers already
processed in that dimension (unless force=True), and merges tags into that
dimension's pool. Groups map member tags to a canonical category *name* — the
original per-paper tags are never altered. A tag belongs to at most one group
within its dimension; ungrouped tags act as standalone categories.
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


# --------------------------------------------------------------------------- #
# Persistence (+ migration from the old single-definition shape)
# --------------------------------------------------------------------------- #
def _ensure_dir() -> None:
    paths.TAGGING_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _blank_state() -> dict[str, Any]:
    return {"dimensions": []}


def _migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade the legacy {definition, papers, groups} shape to dimensions."""
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
        "dimensions": [
            {
                "field": field,
                "name": name or "Keyword",
                "description": definition.get("description", ""),
                "updated_at": definition.get("updated_at"),
                "papers": papers,
                "groups": groups,
            }
        ]
    }


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
    data = _migrate(data)
    data.setdefault("dimensions", [])
    for d in data["dimensions"]:
        d.setdefault("preferred", [])
        d.setdefault("tag_descriptions", {})
        d.setdefault("papers", {})
        d.setdefault("groups", [])
    return data


def _save(state: dict[str, Any]) -> None:
    _ensure_dir()
    with _lock:
        with STATE_FILE.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)


def clear() -> None:
    """Delete all tagging state (used for a cascade reset)."""
    with _lock:
        if STATE_FILE.exists():
            STATE_FILE.unlink()


# --------------------------------------------------------------------------- #
# Dimension helpers
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


def _tag_counts(dim: dict[str, Any]) -> dict[str, int]:
    """tag -> number of processed papers in this dimension carrying that tag."""
    counts: dict[str, int] = {}
    for rec in dim["papers"].values():
        for tag in rec.get("tags", []):
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


def _dim_summary(dim: dict[str, Any], include_total: int) -> dict[str, Any]:
    return {
        "field": dim["field"],
        "name": dim["name"],
        "description": dim.get("description", ""),
        "preferred": dim.get("preferred", []),
        "updated_at": dim.get("updated_at"),
        "processed_total": len(dim["papers"]),
        "unique_tags": len(_tag_counts(dim)),
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
        "dimensions": [_dim_summary(d, include_total) for d in state["dimensions"]],
    }


def add_dimension(
    name: str, description: str = "", preferred: Any = None
) -> dict[str, Any]:
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
        "updated_at": _now(),
        "papers": {},
        "groups": [],
    }
    state["dimensions"].append(dim)
    _save(state)
    return _dim_summary(dim, len(screening_service.included_papers()))


def update_dimension(
    field: str,
    name: Optional[str],
    description: Optional[str],
    preferred: Any = None,
    tag_descriptions: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Update a dimension's display name/description/preferred keywords.

    ``tag_descriptions`` is MERGED into the existing map (so descriptions for
    generated tags are preserved). The ``field`` key is kept stable so per-paper
    tag fields never move.
    """
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
    return _dim_summary(dim, len(screening_service.included_papers()))


def delete_dimension(field: str) -> None:
    state = _load()
    before = len(state["dimensions"])
    state["dimensions"] = [d for d in state["dimensions"] if d["field"] != field]
    if len(state["dimensions"]) == before:
        raise ValueError("Dimension not found.")
    _save(state)


# --------------------------------------------------------------------------- #
# Extraction (per dimension)
# --------------------------------------------------------------------------- #
def _describe_missing_tags(dim: dict[str, Any], description: str) -> None:
    """Generate short descriptions for any tags in this dimension that lack one
    (new tags the extractor invented, and preferred tags first seen this run)."""
    seen_tags: set[str] = set()
    for rec in dim["papers"].values():
        seen_tags.update(rec.get("tags", []))
    missing = [t for t in seen_tags if not dim["tag_descriptions"].get(t)]
    if not missing:
        return
    dres = describe_tags(dim["name"], description, missing)
    for t, d in dres.get("descriptions", {}).items():
        if d:
            dim["tag_descriptions"][t] = d


def run_extraction(
    field: str, limit: Optional[int] = None, force: bool = False
) -> dict[str, Any]:
    state = _load()
    dim = _require(state, field)
    description = dim.get("description", "")

    include = screening_service.included_papers()
    if not description.strip():
        return _summary(dim, include, 0, 0, 0, 0,
                        "Set a description for this dimension first.",
                        available=get_chat_model() is not None)

    model_name = provider_name()
    processed = tagged = skipped = failed = 0
    unavailable = False
    errors: list[str] = []

    # Preferred tags carry their short descriptions to guide the extractor.
    descs = dim.get("tag_descriptions", {})
    preferred_payload = [
        {"tag": t, "description": descs.get(t, "")} for t in dim.get("preferred", [])
    ]

    for paper in include:
        idx = paper.get("index")
        if not idx:
            continue
        if not force and idx in dim["papers"]:
            skipped += 1
            continue
        if limit is not None and processed >= limit:
            break

        res = extract_keywords(
            paper, description, preferred=preferred_payload, max_tags=MAX_TAGS
        )
        if not res.get("available"):
            unavailable = True
            failed += 1
            err = res.get("error") or "unknown error"
            if err not in errors:
                errors.append(err)
            # A config problem won't fix itself; stop immediately.
            if "not configured" in err.lower():
                break
            # Fail fast: if nothing has succeeded after several attempts, the LLM
            # call is broken (bad key, model, rate limit, …) — don't churn for
            # 30 minutes; stop and report the error.
            if processed == 0 and failed >= 5:
                break
            continue

        items = res.get("items", [])
        tags = [it["tag"] for it in items]
        evidence = {it["tag"]: it["evidence"] for it in items if it.get("evidence")}
        dim["papers"][idx] = {
            "index": idx,
            "title": paper.get("title", ""),
            "year": paper.get("year"),
            "database": paper.get("database", ""),
            "abstract": paper.get("abstract", ""),
            "tags": tags,
            "evidence": evidence,
            "processed_at": _now(),
            "model": model_name,
        }
        processed += 1
        if tags:
            tagged += 1
        # Describe new tags + persist incrementally, so progress AND descriptions
        # survive interruptions (not just at the very end of a long run).
        if processed % 20 == 0:
            _describe_missing_tags(dim, description)
            _save(state)

    # Final pass for any remaining undescribed tags.
    if processed > 0:
        _describe_missing_tags(dim, description)

    _save(state)
    note = None
    if errors:
        first = errors[0]
        if processed == 0:
            note = f"No papers were tagged — every attempt failed. First error: {first}"
        else:
            note = f"{failed} paper(s) failed. First error: {first}"
    return _summary(dim, include, processed, tagged, skipped, failed, note,
                    available=not unavailable or processed > 0, errors=errors[:3])


def _summary(dim, include, processed, tagged, skipped, failed, note, available, errors=None):
    return {
        "field": dim["field"],
        "processed": processed,
        "tagged": tagged,
        "skipped": skipped,
        "failed": failed,
        "include_total": len(include),
        "already_processed": len(dim["papers"]),
        "unique_tags": len(_tag_counts(dim)),
        "llm_available": available,
        "note": note,
        "errors": errors or [],
    }


# --------------------------------------------------------------------------- #
# Read models (per dimension)
# --------------------------------------------------------------------------- #
def get_state(field: str) -> dict[str, Any]:
    state = _load()
    dim = _require(state, field)
    include = screening_service.included_papers()
    counts = _tag_counts(dim)
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
        "processed_total": len(dim["papers"]),
        "unique_tags": len(counts),
        "tag_pool": pool,
        "groups": dim["groups"],
    }


def get_papers(field: str) -> list[dict[str, Any]]:
    state = _load()
    dim = _require(state, field)
    return list(dim["papers"].values())


def suggest(
    field: str,
    target: str = "description",
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> dict[str, Any]:
    """Suggest a description or preferred keywords for a dimension.

    ``name``/``description`` override the stored values so the UI can reflect
    unsaved edits. Learns from the current Include set (user or AI-labelled).
    """
    state = _load()
    dim = _require(state, field)
    use_name = name if name is not None else dim["name"]
    use_desc = description if description is not None else dim.get("description", "")
    papers = screening_service.included_papers()
    return suggest_definition(use_name, use_desc, papers, target)


# --------------------------------------------------------------------------- #
# Groups (per dimension)
# --------------------------------------------------------------------------- #
def _clean_members(members: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in members or []:
        norm = normalize_tag(m)
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _detach_members(dim: dict[str, Any], members: list[str], keep_id: str | None) -> None:
    member_set = set(members)
    for g in dim["groups"]:
        if g["id"] == keep_id:
            continue
        g["members"] = [m for m in g.get("members", []) if m not in member_set]


def add_group(field: str, name: str, members: Any) -> dict[str, Any]:
    state = _load()
    dim = _require(state, field)
    group = {
        "id": "grp_" + uuid.uuid4().hex[:8],
        "name": (name or "").strip(),
        "members": _clean_members(members),
    }
    if not group["name"]:
        raise ValueError("Group name is required.")
    _detach_members(dim, group["members"], keep_id=group["id"])
    dim["groups"].append(group)
    _save(state)
    return group


def update_group(
    field: str, group_id: str, name: Optional[str], members: Any
) -> dict[str, Any]:
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
    """Paper counts per category for one dimension.

    A paper counts toward a category if it carries ANY tag in that category
    (many-to-many). Group categories also report per-member sub-counts. Tags in
    no group are returned as standalone categories.
    """
    state = _load()
    dim = _require(state, field)
    papers = list(dim["papers"].values())
    tag_counts = _tag_counts(dim)

    group_categories = []
    for g in dim["groups"]:
        members = g.get("members", [])
        member_set = set(members)
        paper_count = sum(
            1 for p in papers if member_set.intersection(p.get("tags", []))
        )
        subs = [{"tag": m, "paper_count": tag_counts.get(m, 0)} for m in members]
        subs.sort(key=lambda s: (-s["paper_count"], s["tag"]))
        group_categories.append({
            "id": g["id"],
            "name": g["name"],
            "kind": "group",
            "paper_count": paper_count,
            "members": subs,
        })
    group_categories.sort(key=lambda c: (-c["paper_count"], c["name"]))

    grouped = set(_grouped_member_map(dim).keys())
    standalone = [
        {"tag": t, "name": t, "kind": "standalone", "paper_count": c}
        for t, c in tag_counts.items()
        if t not in grouped
    ]
    standalone.sort(key=lambda c: (-c["paper_count"], c["name"]))

    return {
        "field": dim["field"],
        "name": dim["name"],
        "processed_total": len(papers),
        "unique_tags": len(tag_counts),
        "groups": group_categories,
        "standalone": standalone,
        "category_total": len(group_categories) + len(standalone),
    }
