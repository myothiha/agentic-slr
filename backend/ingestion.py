"""Ingest uploaded files into the uniform per-database paper store.

Responsibilities:
  * parse each uploaded file into canonical records (via parsers)
  * combine multiple files for the same database
  * assign sequential, traceable indexes (e.g. IEEE-001) per database
  * persist to data/01_raw_paper_list/<database_id>.json
"""
from __future__ import annotations

from typing import Any, Optional

from agents.deduplication import normalize_doi, normalize_title

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


def _years_compatible(a: Optional[int], b: Optional[int]) -> bool:
    if a and b:
        return a == b
    return True


class _Seen:
    """Registry of already-present papers (by DOI and title+year) so we can skip
    incoming records that duplicate the existing list or each other.
    """

    def __init__(self, papers: list[dict[str, Any]]):
        self.doi: dict[str, bool] = {}
        self.title: dict[str, list[Optional[int]]] = {}
        for p in papers:
            self.add(p.get("doi", ""), p.get("title", ""), p.get("year"))

    def add(self, doi: str, title: str, year: Optional[int]) -> None:
        dk = normalize_doi(doi)
        tk = normalize_title(title)
        if dk:
            self.doi[dk] = True
        if tk:
            self.title.setdefault(tk, []).append(year)

    def contains(self, doi: str, title: str, year: Optional[int]) -> bool:
        dk = normalize_doi(doi)
        if dk and dk in self.doi:
            return True
        tk = normalize_title(title)
        if tk and tk in self.title:
            return any(_years_compatible(year, y) for y in self.title[tk])
        return False


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

    # Skip incoming records that already exist (by DOI, then title+year) — both
    # against the current list and against earlier records in this same upload.
    seen = _Seen(existing)

    added: list[dict[str, Any]] = []
    per_file: list[dict[str, Any]] = []

    for filename, content in files:
        records = parsers.parse_file(filename, content)
        f_added = 0
        f_skipped = 0
        for rec in records:
            title = rec.get("title", "")
            doi = rec.get("doi", "")
            year = rec.get("year")
            if seen.contains(doi, title, year):
                f_skipped += 1
                continue
            seq += 1
            paper = {
                "index": f"{prefix}-{seq:03d}",
                "database": db["name"],
                "database_id": database_id,
                "title": title,
                "authors": rec.get("authors", []),
                "year": year,
                "abstract": rec.get("abstract", ""),
                "keywords": rec.get("keywords", []),
                "doi": doi,
                "venue": rec.get("venue", ""),
                "url": rec.get("url", ""),
                "early_access": rec.get("early_access", False),
                "source_file": filename,
                "raw": rec.get("raw", {}),
            }
            added.append(paper)
            seen.add(doi, title, year)
            f_added += 1
        per_file.append({
            "filename": filename, "parsed": len(records),
            "added": f_added, "skipped": f_skipped,
        })

    combined = existing + added
    storage.save_papers(database_id, combined)
    # Retain the original upload batch (latest only) for traceability/re-download.
    storage.save_raw_uploads(database_id, files)

    return {
        "database_id": database_id,
        "database": db["name"],
        "files": per_file,
        "added": len(added),
        "skipped": sum(f["skipped"] for f in per_file),
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
            "proxy_suffix": db.get("proxy_suffix"),
            "paper_count": len(papers),
            "index_range": _index_range(papers, db["prefix"]),
            "source_files": source_files,
            "raw_files": storage.list_raw_uploads(db["id"]),
        })
    return summaries
