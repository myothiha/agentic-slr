"""Ingest uploaded files into the uniform per-database paper store.

Responsibilities:
  * parse each uploaded file into canonical records (via parsers)
  * combine multiple files for the same database
  * assign sequential, traceable indexes (e.g. IEEE-001) per database
  * persist to data/01_raw_paper_list/<database_id>.json
"""
from __future__ import annotations

from typing import Any

from . import parsers, storage


def _next_seq(existing: list[dict[str, Any]]) -> int:
    """Highest existing sequence number for a database, so we append safely."""
    max_seq = 0
    for p in existing:
        idx = p.get("index", "")
        if "-" in idx:
            tail = idx.rsplit("-", 1)[-1]
            if tail.isdigit():
                max_seq = max(max_seq, int(tail))
    return max_seq


def ingest_files(
    database_id: str,
    files: list[tuple[str, bytes]],
) -> dict[str, Any]:
    """Parse and append uploaded files to a database's paper list.

    `files` is a list of (filename, content_bytes).
    Returns a summary dict.
    """
    metadata = storage.load_metadata()
    db = next((d for d in metadata["databases"] if d["id"] == database_id), None)
    if db is None:
        raise ValueError(f"Unknown database id: {database_id}")

    existing = storage.load_papers(database_id)
    seq = _next_seq(existing)
    prefix = db["prefix"]

    added: list[dict[str, Any]] = []
    per_file: list[dict[str, Any]] = []

    for filename, content in files:
        records = parsers.parse_file(filename, content)
        for rec in records:
            seq += 1
            paper = {
                "index": f"{prefix}-{seq:03d}",
                "database": db["name"],
                "database_id": database_id,
                "title": rec.get("title", ""),
                "authors": rec.get("authors", []),
                "year": rec.get("year"),
                "abstract": rec.get("abstract", ""),
                "keywords": rec.get("keywords", []),
                "doi": rec.get("doi", ""),
                "venue": rec.get("venue", ""),
                "url": rec.get("url", ""),
                "source_file": filename,
                "raw": rec.get("raw", {}),
            }
            added.append(paper)
        per_file.append({"filename": filename, "parsed": len(records)})

    combined = existing + added
    storage.save_papers(database_id, combined)

    return {
        "database_id": database_id,
        "database": db["name"],
        "files": per_file,
        "added": len(added),
        "total": len(combined),
        "index_range": _index_range(combined, prefix),
    }


def _index_range(papers: list[dict[str, Any]], prefix: str) -> str | None:
    seqs = []
    for p in papers:
        idx = p.get("index", "")
        tail = idx.rsplit("-", 1)[-1] if "-" in idx else ""
        if tail.isdigit():
            seqs.append(int(tail))
    if not seqs:
        return None
    lo, hi = min(seqs), max(seqs)
    return f"{prefix}-{lo:03d} … {prefix}-{hi:03d}"


def reindex(database_id: str) -> int:
    """Re-number all papers in a database sequentially from 1.

    Useful after deletions to keep indexes contiguous.
    """
    metadata = storage.load_metadata()
    db = next((d for d in metadata["databases"] if d["id"] == database_id), None)
    if db is None:
        raise ValueError(f"Unknown database id: {database_id}")
    papers = storage.load_papers(database_id)
    for i, p in enumerate(papers, start=1):
        p["index"] = f"{db['prefix']}-{i:03d}"
    storage.save_papers(database_id, papers)
    return len(papers)


def database_summaries() -> list[dict[str, Any]]:
    metadata = storage.load_metadata()
    summaries = []
    for db in sorted(metadata["databases"], key=lambda d: d.get("priority", 100)):
        papers = storage.load_papers(db["id"])
        source_files = sorted({p.get("source_file", "") for p in papers if p.get("source_file")})
        summaries.append({
            "id": db["id"],
            "name": db["name"],
            "prefix": db["prefix"],
            "priority": db.get("priority", 100),
            "paper_count": len(papers),
            "index_range": _index_range(papers, db["prefix"]),
            "source_files": source_files,
        })
    return summaries
