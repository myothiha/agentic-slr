"""Phase 6 — Keyword Analysis.

Configurable multi-level charts over the tagged papers, plus saved named views.

A view has up to three levels (Phase 1 uses two: panels -> breakdown):
  * TOP level  — one diagram per selected value (small multiples).
  * BREAKDOWN  — the distribution (bars/slices) inside each diagram.
  * SERIES     — (Phase 2) an extra dimension splitting each bar.

Eligible dimension for any level: a tag dimension field, or Publication Year
(field == "year"). For tag dimensions the *value* of a paper is, by default, the
CATEGORY (group) its tags map to; tags that belong to no category act as their
own standalone value. Raw-tag mode uses the tags directly.

Counting is many-to-many: a paper contributes to every value it carries, so bar
sums can exceed the distinct paper count.

State (saved views) persists to data/05_keyword_analysis/analysis_views.json.
"""
from __future__ import annotations

import json
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

from . import paths, tagging_service

_lock = threading.Lock()

VIEWS_FILE = paths.ANALYSIS_DIR / "analysis_views.json"
YEAR_FIELD = "year"


# --------------------------------------------------------------------------- #
# Value mapping
# --------------------------------------------------------------------------- #
def _tag_to_category(dim: dict[str, Any]) -> dict[str, str]:
    """member tag -> category (group) name for one dimension."""
    out: dict[str, str] = {}
    for g in dim.get("groups", []):
        for m in g.get("members", []):
            out[m] = g["name"]
    return out


def _paper_values(state: dict[str, Any], field: str, unit: str, paper: dict[str, Any],
                  cat_maps: dict[str, dict[str, str]]) -> list[str]:
    """The set of values this paper has for (field, unit)."""
    if field == YEAR_FIELD:
        y = paper.get("year")
        return [str(y)] if y else []
    tags = paper.get("tags", {}).get(field, []) or []
    if unit == "tag":
        return list(dict.fromkeys(tags))
    # category unit: map to group name, or keep the tag when ungrouped (standalone)
    cmap = cat_maps.get(field, {})
    vals = [cmap.get(t, t) for t in tags]
    return list(dict.fromkeys(vals))


def _cat_maps(state: dict[str, Any], fields: set[str]) -> dict[str, dict[str, str]]:
    maps: dict[str, dict[str, str]] = {}
    for dim in state["dimensions"]:
        if dim["field"] in fields:
            maps[dim["field"]] = _tag_to_category(dim)
    return maps


# --------------------------------------------------------------------------- #
# Dimensions metadata (for the selectors)
# --------------------------------------------------------------------------- #
def dimensions() -> dict[str, Any]:
    state = tagging_service.snapshot()
    papers = list(state["papers"].values())
    out = []
    for dim in state["dimensions"]:
        field = dim["field"]
        counts: Counter = Counter()
        for p in papers:
            for t in p.get("tags", {}).get(field, []):
                counts[t] += 1
        cmap = _tag_to_category(dim)
        cat_counts: Counter = Counter()
        for p in papers:
            for v in _paper_values(state, field, "category", p, {field: cmap}):
                cat_counts[v] += 1
        out.append({
            "field": field,
            "name": dim["name"],
            "type": "tag",
            "categories": [{"name": n, "count": c} for n, c in cat_counts.most_common()],
            "tags": [{"tag": t, "count": c} for t, c in counts.most_common()],
        })
    years = sorted({str(p["year"]) for p in papers if p.get("year")})
    out.append({"field": YEAR_FIELD, "name": "Publication Year", "type": "year",
                "values": years})
    return {"dimensions": out}


# --------------------------------------------------------------------------- #
# Compute
# --------------------------------------------------------------------------- #
def compute(config: dict[str, Any]) -> dict[str, Any]:
    state = tagging_service.snapshot()
    papers = list(state["papers"].values())

    top = config.get("top") or {}
    brk = config.get("breakdown") or {}
    opts = config.get("options") or {}
    top_field = top.get("dimension")
    top_unit = top.get("unit", "category")
    top_values = top.get("values") or []
    brk_field = brk.get("dimension")
    brk_unit = brk.get("unit", "category")
    normalize = bool(opts.get("normalize"))
    min_count = int(opts.get("min_count") or 1)
    top_n = opts.get("top_n")

    if not top_field or not brk_field:
        return {"panels": [], "matching_papers": [], "matching_total": 0}

    cmaps = _cat_maps(state, {top_field, brk_field})

    # Precompute each paper's top and breakdown values once.
    def tvals(p):
        return _paper_values(state, top_field, top_unit, p, cmaps)

    def bvals(p):
        return _paper_values(state, brk_field, brk_unit, p, cmaps)

    brk_is_year = brk_field == YEAR_FIELD
    top_is_year = top_field == YEAR_FIELD

    def _order(counter):
        if brk_is_year:
            return sorted(counter.items(), key=lambda kv: int(kv[0]))
        return counter.most_common()

    panels = []
    matched_idx: dict[str, dict[str, Any]] = {}
    for v in top_values:
        subset = [p for p in papers if v in tvals(p)]
        bar_counter: Counter = Counter()
        bar_idx: dict[str, list[str]] = {}
        for p in subset:
            for b in bvals(p):
                bar_counter[b] += 1
                bar_idx.setdefault(b, []).append(p.get("index"))
            matched_idx[p.get("index")] = p
        bars = [{"label": b, "count": c, "indices": bar_idx[b]}
                for b, c in _order(bar_counter)]
        bars = [b for b in bars if b["count"] >= min_count]
        if top_n:
            bars = bars[:int(top_n)]
        if normalize and subset:
            for b in bars:
                b["percent"] = round(100 * b["count"] / len(subset), 1)
        panels.append({"value": v, "paper_count": len(subset), "bars": bars})

    matching = [{
        "index": p.get("index"), "title": p.get("title", ""), "year": p.get("year"),
        "database": p.get("database", ""),
        "top_values": tvals(p), "breakdown_values": bvals(p),
    } for p in matched_idx.values()]
    matching.sort(key=lambda r: (r["index"] or ""))

    overview = _overview(papers, tvals, bvals, min_count, top_is_year)

    return {
        "top": {"field": top_field, "unit": top_unit},
        "breakdown": {"field": brk_field, "unit": brk_unit},
        "overview": overview,
        "panels": panels,
        "matching_papers": matching,
        "matching_total": len(matching),
    }


_MAX_SERIES = 12


def _overview(papers, tvals, bvals, min_count, top_is_year=False):
    """Always-on chart: paper count per top-dimension value (sorted by year when
    the top dimension is Publication Year, else by count)."""
    all_top: Counter = Counter()
    for p in papers:
        for v in tvals(p):
            all_top[v] += 1
    if top_is_year:
        top_order = [v for v in sorted(all_top, key=lambda x: int(x)) if all_top[v] >= min_count]
    else:
        top_order = [v for v, c in all_top.most_common() if c >= min_count]

    series_counter: Counter = Counter()
    per_top: dict[str, Counter] = {}
    for tv in top_order:
        rc: Counter = Counter()
        for p in papers:
            if tv in tvals(p):
                for b in bvals(p):
                    rc[b] += 1
                    series_counter[b] += 1
        per_top[tv] = rc

    series = [s for s, c in series_counter.most_common() if c >= min_count]
    top_series = series[:_MAX_SERIES]
    use_other = len(series) > _MAX_SERIES
    rows = []
    for tv in top_order:
        row = {"top": tv}
        other = 0
        for s, c in per_top[tv].items():
            if s in top_series:
                row[s] = c
            elif c >= min_count:
                other += c
        if use_other and other:
            row["Other"] = other
        rows.append(row)

    return {
        "dim1_bars": [{"label": v, "count": all_top[v]} for v in top_order],
        "series": top_series + (["Other"] if use_other else []),
        "rows": rows,
    }


# --------------------------------------------------------------------------- #
# Saved views
# --------------------------------------------------------------------------- #
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_views() -> list[dict[str, Any]]:
    if not VIEWS_FILE.exists():
        return []
    try:
        data = json.loads(VIEWS_FILE.read_text(encoding="utf-8") or "[]")
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _save_views(views: list[dict[str, Any]]) -> None:
    paths.ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        VIEWS_FILE.write_text(json.dumps(views, indent=2, ensure_ascii=False), encoding="utf-8")


def list_views() -> list[dict[str, Any]]:
    return _load_views()


def create_view(name: str, config: dict[str, Any]) -> dict[str, Any]:
    if not (name or "").strip():
        raise ValueError("View name is required.")
    views = _load_views()
    view = {"id": "view_" + uuid.uuid4().hex[:8], "name": name.strip(),
            "config": config or {}, "updated_at": _now()}
    views.append(view)
    _save_views(views)
    return view


def update_view(view_id: str, name: Optional[str], config: Optional[dict[str, Any]]) -> dict[str, Any]:
    views = _load_views()
    view = next((v for v in views if v["id"] == view_id), None)
    if view is None:
        raise ValueError("View not found.")
    if name is not None:
        if not name.strip():
            raise ValueError("View name cannot be empty.")
        view["name"] = name.strip()
    if config is not None:
        view["config"] = config
    view["updated_at"] = _now()
    _save_views(views)
    return view


def delete_view(view_id: str) -> None:
    views = _load_views()
    new = [v for v in views if v["id"] != view_id]
    if len(new) == len(views):
        raise ValueError("View not found.")
    _save_views(new)


def clear() -> None:
    with _lock:
        if VIEWS_FILE.exists():
            VIEWS_FILE.unlink()
