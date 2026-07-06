"""Read/write helpers for metadata and per-database paper files."""
from __future__ import annotations

import json
import re
import shutil
import threading
from datetime import datetime, timezone
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
    # The stored original uploads belong to this paper list, so drop them too.
    delete_raw_uploads(database_id)


# --------------------------------------------------------------------------- #
# Original uploaded files (kept for traceability / re-download)
#
# Only the most recent upload batch per database is retained: each new ingest
# replaces whatever was stored before. Files live in
# data/00_raw_uploads/<database_id>/.
# --------------------------------------------------------------------------- #
def _safe_name(filename: str) -> str:
    """Strip any path components and disallow traversal in stored filenames."""
    name = (filename or "upload").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "upload"
    return name


def raw_upload_dir(database_id: str):
    return paths.RAW_UPLOAD_DIR / database_id


def save_raw_uploads(database_id: str, files: list[tuple[str, bytes]]) -> None:
    """Persist the original upload batch, replacing any previously stored files."""
    if not files:
        return
    dest = raw_upload_dir(database_id)
    with _lock:
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        used: set[str] = set()
        for filename, content in files:
            name = _safe_name(filename)
            # Avoid collisions when a batch has duplicate names.
            stem, dot, ext = name.partition(".")
            n, candidate = 1, name
            while candidate in used:
                candidate = f"{stem}_{n}{dot}{ext}"
                n += 1
            used.add(candidate)
            (dest / candidate).write_bytes(content)


def list_raw_uploads(database_id: str) -> list[dict[str, Any]]:
    dest = raw_upload_dir(database_id)
    if not dest.exists():
        return []
    out: list[dict[str, Any]] = []
    for fp in sorted(dest.iterdir()):
        if fp.is_file():
            st = fp.stat()
            out.append({
                "filename": fp.name,
                "size": st.st_size,
                "uploaded_at": datetime.fromtimestamp(
                    st.st_mtime, tz=timezone.utc
                ).isoformat(),
            })
    return out


def raw_upload_path(database_id: str, filename: str):
    """Resolve a stored raw file, guarding against path traversal."""
    dest = raw_upload_dir(database_id).resolve()
    fp = (dest / _safe_name(filename)).resolve()
    if dest not in fp.parents or not fp.is_file():
        return None
    return fp


def delete_raw_uploads(database_id: str) -> None:
    dest = raw_upload_dir(database_id)
    if dest.exists():
        shutil.rmtree(dest)
