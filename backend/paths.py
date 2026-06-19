"""Centralised filesystem paths for the SLR backend.

All paths are derived from the project root so the app works regardless of
the current working directory.
"""
from __future__ import annotations

from pathlib import Path

# backend/paths.py -> backend/ -> project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONTEXT_DIR = PROJECT_ROOT / "context"
METADATA_FILE = CONTEXT_DIR / "metadata.json"

DATA_DIR = PROJECT_ROOT / "data"
RAW_PAPER_DIR = DATA_DIR / "01_raw_paper_list"
DEDUP_DIR = DATA_DIR / "02_deduplication"
PAGE_FILTER_DIR = DATA_DIR / "02b_page_filter"
SCREENING_DIR = DATA_DIR / "03_abstract_title_screening"


def ensure_dirs() -> None:
    """Create the directories the backend relies on if they are missing."""
    for d in (CONTEXT_DIR, DATA_DIR, RAW_PAPER_DIR):
        d.mkdir(parents=True, exist_ok=True)
