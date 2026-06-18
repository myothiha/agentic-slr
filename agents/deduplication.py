"""Deduplication Agent (Phase 2 — not yet implemented).

Will perform intra- and inter-database deduplication with priority ordering
(IEEE -> ACM -> Scopus -> Web of Science) and produce a traceability matrix.
Saves results to data/02_deduplication/.
"""
from __future__ import annotations


def deduplicate(*args, **kwargs):
    raise NotImplementedError("Deduplication is implemented in Phase 2.")
