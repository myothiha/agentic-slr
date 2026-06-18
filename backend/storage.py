"""Read/write helpers for metadata and per-database paper files."""
from __future__ import annotations

import json
import threading
from typing import Any

from . import paths

_lock = threading.Lock()

DEFAULT_DATABASES = [
    {"id": "ieee", "name": "IEEE Xplore", "prefix": "IEEE", "priority": 1},
    {"id": "acm", "name": "ACM Digital Library", "prefix": "ACM", "priority": 2},
    {"id": "scopus", "name": "Scopus", "prefix": "SCOPUS", "priority": 3},
    {"id": "wos", "name": "Web of Science", "prefix": "WOS", "priority": 4},
]

DEFAULT_METADATA: dict[str, Any] = {
    "title": "",
    "research_questions": "",
    "keyword_string": "",
    "inclusion_criteria": [],
    "exclusion_criteria": [],
    "databases": DEFAULT_DATABASES,
    "highlight_rules": {"terms": [], "patterns": [], "compiled_at": None, "source": None},
}


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #
def load_metadata() -> dict[str, Any]:
    paths.ensure_dirs()
    if not paths.METADATA_FILE.exists():
        save_metadata(DEFAULT_METADATA)
        return json.loads(json.dumps(DEFAULT_METADATA))
    with paths.METADATA_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    # Fill any missing top-level keys with defaults.
    for key, value in DEFAULT_METADATA.items():
        data.setdefault(key, json.loads(json.dumps(value)))
    data["research_questions"] = _coerce_research_questions(data.get("research_questions", ""))
    return data


def _coerce_research_questions(rqs: Any) -> str:
    """Research questions are a plain free-text field.

    Coerce any legacy shapes (list of strings, or structured RQ dicts) into a
    single text block so old metadata files keep working.
    """
    if isinstance(rqs, str):
        return rqs
    if isinstance(rqs, list):
        lines = []
        for rq in rqs:
            if isinstance(rq, str):
                lines.append(rq)
            elif isinstance(rq, dict):
                label = rq.get("id", "")
                question = rq.get("question", "")
                lines.append(f"{label}: {question}".strip(": ").strip())
        return "\n".join(l for l in lines if l)
    return ""


def save_metadata(data: dict[str, Any]) -> None:
    paths.ensure_dirs()
    with _lock:
        with paths.METADATA_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Paper files (one JSON per database, stored in data/01_raw_paper_list)
# --------------------------------------------------------------------------- #
def paper_file(database_id: str):
    return paths.RAW_PAPER_DIR / f"{database_id}.json"


def load_papers(database_id: str) -> list[dict[str, Any]]:
    fp = paper_file(database_id)
    if not fp.exists():
        return []
    with fp.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_papers(database_id: str, papers: list[dict[str, Any]]) -> None:
    paths.ensure_dirs()
    with _lock:
        with paper_file(database_id).open("w", encoding="utf-8") as f:
            json.dump(papers, f, indent=2, ensure_ascii=False)


def delete_papers(database_id: str) -> None:
    fp = paper_file(database_id)
    if fp.exists():
        fp.unlink()
