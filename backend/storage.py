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


def _conf(id_, display, dblp_key, sources, y0=2020, y1=2025, track="main"):
    return {
        "id": id_, "display": display, "dblp_key": dblp_key, "track": track,
        "include_workshops": False, "include_companion": False,
        "year_start": y0, "year_end": y1,
        "abstract_sources": sources, "enabled": True,
    }


# Editable conference registry (venue -> DBLP key). dblp_key values are the
# expected keys but are re-verified per venue-year at fetch time.
DEFAULT_CONFERENCES = [
    _conf("neurips", "NeurIPS", "conf/nips", ["openreview", "openalex", "s2"]),
    _conf("icml", "ICML", "conf/icml", ["pmlr", "openalex", "s2"]),
    _conf("iclr", "ICLR", "conf/iclr", ["openreview", "openalex", "s2"]),
    _conf("acl", "ACL", "conf/acl", ["acl_anthology", "openalex", "s2"]),
    _conf("emnlp", "EMNLP", "conf/emnlp", ["acl_anthology", "openalex", "s2"]),
    _conf("naacl", "NAACL", "conf/naacl", ["acl_anthology", "openalex", "s2"]),
    _conf("cvpr", "CVPR", "conf/cvpr", ["cvf", "openalex", "s2"]),
    _conf("iccv", "ICCV", "conf/iccv", ["cvf", "openalex", "s2"], y0=2019),
    _conf("eccv", "ECCV", "conf/eccv", ["openalex", "s2"], y1=2024),
    _conf("aaai", "AAAI", "conf/aaai", ["openalex", "s2"]),
    _conf("ijcai", "IJCAI", "conf/ijcai", ["openalex", "s2"]),
    _conf("kdd", "KDD", "conf/kdd", ["openalex", "s2"]),
    _conf("www", "WWW (The Web Conf)", "conf/www", ["openalex", "s2"]),
    _conf("sigir", "SIGIR", "conf/sigir", ["openalex", "s2"]),
]

DEFAULT_METADATA: dict[str, Any] = {
    "title": "",
    "research_questions": "",
    "keyword_string": "",
    "inclusion_criteria": [],
    "exclusion_criteria": [],
    "databases": DEFAULT_DATABASES,
    "conferences": DEFAULT_CONFERENCES,
    "conference_defaults": {"year_start": 2020, "year_end": 2025},
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
# Conference paper files (one JSON per venue, in data/00c_conference_papers)
# --------------------------------------------------------------------------- #
def conference_paper_file(venue_id: str):
    return paths.CONFERENCE_DIR / f"{venue_id}.json"


def load_conference_papers(venue_id: str) -> list[dict[str, Any]]:
    fp = conference_paper_file(venue_id)
    if not fp.exists():
        return []
    with fp.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_conference_papers(venue_id: str, papers: list[dict[str, Any]]) -> None:
    paths.ensure_dirs()
    with _lock:
        with conference_paper_file(venue_id).open("w", encoding="utf-8") as f:
            json.dump(papers, f, indent=2, ensure_ascii=False)


def delete_conference_papers(venue_id: str) -> None:
    fp = conference_paper_file(venue_id)
    if fp.exists():
        fp.unlink()


def save_conference_snapshot(run_id: str, manifest: dict[str, Any]) -> None:
    paths.ensure_dirs()
    with _lock:
        fp = paths.CONFERENCE_SNAPSHOT_DIR / f"{run_id}.json"
        with fp.open("w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)


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
