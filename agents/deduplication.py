"""Deduplication Agent (Phase 2).

Performs intra- and inter-database deduplication with a configurable priority
order (default IEEE -> ACM -> Scopus -> Web of Science) and produces a
traceability matrix that records how many duplicates each database contributed
and which source database each duplicate matched against.

Matching strategy (deterministic):
  * DOI match  — strongest signal; normalized DOIs that are equal are duplicates.
  * Title match — normalized title equality, additionally requiring compatible
    publication years (equal, or one missing) to reduce false positives.

The first paper encountered for a given key (in priority + index order) is kept
as the "original"; later matches are flagged as duplicates of it. Because the
registry accumulates across the whole pass, duplicates *within* a single
database (intra-database) are caught too — their matched source is that same
database.

This module is pure logic (no file I/O); persistence lives in
backend/dedup_service.py.
"""
from __future__ import annotations

import re
from typing import Any, Optional

_DOI_PREFIXES = (
    "https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
    "http://dx.doi.org/", "doi:", "doi ",
)


def normalize_doi(doi: str) -> str:
    if not doi:
        return ""
    d = doi.strip().lower()
    for p in _DOI_PREFIXES:
        if d.startswith(p):
            d = d[len(p):]
    return d.strip()


def normalize_title(title: str) -> str:
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _years_compatible(a: Optional[int], b: Optional[int]) -> bool:
    if a and b:
        return a == b
    return True


def run_deduplication(
    databases: list[dict[str, Any]],
    papers_by_db: dict[str, list[dict[str, Any]]],
    priority_order: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Run deduplication across databases.

    Args:
        databases: list of db metadata dicts ({id, name, prefix, priority}).
        papers_by_db: mapping db_id -> list of uniform paper dicts.
        priority_order: optional explicit list of db_ids; defaults to ascending
            `priority` then name.

    Returns a dict with: priority_order, annotated (list of papers with
    dedup_status + duplicate_of), matrix, and summary.
    """
    db_by_id = {d["id"]: d for d in databases}
    if priority_order is None:
        priority_order = [
            d["id"] for d in sorted(databases, key=lambda d: (d.get("priority", 100), d["name"]))
        ]

    registry_doi: dict[str, dict[str, Any]] = {}
    registry_title: dict[str, list[dict[str, Any]]] = {}

    annotated: list[dict[str, Any]] = []
    # matrix[removed_db_id][source_db_id] = count
    matrix: dict[str, dict[str, int]] = {}
    per_db_totals: dict[str, int] = {}

    for db_id in priority_order:
        papers = papers_by_db.get(db_id, [])
        per_db_totals[db_id] = len(papers)
        for paper in papers:
            doi_key = normalize_doi(paper.get("doi", ""))
            title_key = normalize_title(paper.get("title", ""))
            match: Optional[tuple[dict[str, Any], str]] = None

            if doi_key and doi_key in registry_doi:
                match = (registry_doi[doi_key], "doi")
            elif title_key and title_key in registry_title:
                for cand in registry_title[title_key]:
                    if _years_compatible(paper.get("year"), cand.get("year")):
                        match = (cand, "title")
                        break

            entry = dict(paper)
            if match is not None:
                original, match_type = match
                entry["dedup_status"] = "duplicate"
                entry["duplicate_of"] = {
                    "index": original.get("index"),
                    "database": original.get("database"),
                    "database_id": original.get("database_id"),
                    "title": original.get("title"),
                    "match_type": match_type,
                }
                src = original.get("database_id")
                matrix.setdefault(db_id, {}).setdefault(src, 0)
                matrix[db_id][src] += 1
            else:
                entry["dedup_status"] = "unique"
                entry["duplicate_of"] = None
                if doi_key:
                    registry_doi[doi_key] = entry
                if title_key:
                    registry_title.setdefault(title_key, []).append(entry)

            annotated.append(entry)

    summary = _build_summary(annotated, priority_order, db_by_id, per_db_totals, matrix)
    return {
        "priority_order": priority_order,
        "annotated": annotated,
        "matrix": _matrix_view(priority_order, db_by_id, per_db_totals, matrix),
        "summary": summary,
    }


def _build_summary(annotated, priority_order, db_by_id, per_db_totals, matrix) -> dict[str, Any]:
    total = len(annotated)
    duplicates = sum(1 for p in annotated if p["dedup_status"] == "duplicate")
    return {
        "total_input": total,
        "total_duplicates": duplicates,
        "total_unique": total - duplicates,
        "databases": len(priority_order),
    }


def _matrix_view(priority_order, db_by_id, per_db_totals, matrix) -> dict[str, Any]:
    """Shape the matrix for display: one row per database (in priority order)."""
    names = {db_id: db_by_id.get(db_id, {}).get("name", db_id) for db_id in priority_order}
    rows = []
    for db_id in priority_order:
        against = matrix.get(db_id, {})
        dup_total = sum(against.values())
        total = per_db_totals.get(db_id, 0)
        rows.append({
            "database_id": db_id,
            "database": names[db_id],
            "total": total,
            "duplicates": dup_total,
            "unique": total - dup_total,
            "against": {src: against.get(src, 0) for src in priority_order},
        })
    return {
        "priority_order": priority_order,
        "names": names,
        "rows": rows,
    }
