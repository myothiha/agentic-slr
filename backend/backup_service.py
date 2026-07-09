"""Backup & restore for the whole project folder.

Creates timestamped zip archives of the entire project (excluding heavy/derived
directories) under `backups/`, lists them, restores from one (taking a safety
backup first), and deletes them.

NOTE: `.env` (API keys) is excluded from backups for safety; `.env.example` is
kept so a restore documents which variables are needed.
"""
from __future__ import annotations

import os
import shutil
import zipfile
from datetime import datetime, timezone
from typing import Any

from . import paths

BACKUP_DIR = paths.PROJECT_ROOT / "backups"

# Directories never included in a backup (derived, heavy, or the backups dir).
# `raw_pdfs` holds downloaded/uploaded full-text PDFs — large binaries that are
# re-downloadable or re-uploadable, so they're excluded to keep backups lean.
# The extracted text (extracted_texts/) and full_text_state.json are kept.
EXCLUDE_DIRS = {
    ".venv", "node_modules", ".git", "backups", "__pycache__",
    ".pytest_cache", "dist", ".vite", ".idea", ".DS_Store", "raw_pdfs",
}

# Files excluded for security: .env holds API keys. `.env.example` is kept so a
# restore still documents which variables are needed (re-enter the secret after).
EXCLUDE_FILES = {".env"}


def _ensure_dir() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _iter_files():
    """Yield (absolute_path, arcname) for every file to include in a backup."""
    root = paths.PROJECT_ROOT
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded directories in place so os.walk skips them.
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if fn in EXCLUDE_FILES:
                continue  # never back up secrets
            abs_path = os.path.join(dirpath, fn)
            arcname = os.path.relpath(abs_path, root)
            yield abs_path, arcname


def create_backup(label: str | None = None) -> dict[str, Any]:
    _ensure_dir()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{_safe(label)}" if label else ""
    name = f"backup-{ts}{suffix}.zip"
    dest = BACKUP_DIR / name
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for abs_path, arcname in _iter_files():
            try:
                zf.write(abs_path, arcname)
            except (OSError, ValueError):
                continue  # skip files that vanish or can't be read
    return _info(dest)


def list_backups() -> list[dict[str, Any]]:
    _ensure_dir()
    items = [
        _info(p) for p in BACKUP_DIR.glob("*.zip") if p.is_file()
    ]
    return sorted(items, key=lambda i: i["created_at"], reverse=True)


def restore_backup(name: str) -> dict[str, Any]:
    path = _safe_backup_path(name)
    if not path.exists():
        raise ValueError(f"Backup not found: {name}")
    # Safety net: snapshot current state before overwriting.
    safety = create_backup(label="before-restore")
    with zipfile.ZipFile(path, "r") as zf:
        zf.extractall(paths.PROJECT_ROOT)
    return {"restored": name, "safety_backup": safety["name"]}


def delete_backup(name: str) -> dict[str, Any]:
    path = _safe_backup_path(name)
    if not path.exists():
        raise ValueError(f"Backup not found: {name}")
    path.unlink()
    return {"deleted": name}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _info(path) -> dict[str, Any]:
    st = path.stat()
    return {
        "name": path.name,
        "size": st.st_size,
        "created_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
    }


def _safe(label: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in label)[:40]


def _safe_backup_path(name: str):
    # Prevent path traversal; only allow .zip files inside BACKUP_DIR.
    base = os.path.basename(name)
    if not base.endswith(".zip"):
        raise ValueError("Invalid backup name.")
    return BACKUP_DIR / base
