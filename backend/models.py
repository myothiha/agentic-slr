"""Pydantic schemas shared across the backend."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Database(BaseModel):
    id: str
    name: str
    prefix: str
    priority: int = 100
    # Optional institutional proxy host suffix (EZproxy hostname-remapping style),
    # e.g. "mediaproxy.imtbs-tsp.eu". When set, download URLs for this database are
    # rewritten host.example.org -> host-example-org.<proxy_suffix>.
    proxy_suffix: Optional[str] = None


class HighlightRules(BaseModel):
    terms: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    compiled_at: Optional[str] = None
    source: Optional[str] = None  # "agent" | "deterministic"


class Metadata(BaseModel):
    title: str = ""
    research_questions: str = ""
    keyword_string: str = ""
    inclusion_criteria: list[str] = Field(default_factory=list)
    exclusion_criteria: list[str] = Field(default_factory=list)
    databases: list[Database] = Field(default_factory=list)
    highlight_rules: HighlightRules = Field(default_factory=HighlightRules)


class ContextUpdate(BaseModel):
    """Payload accepted by the Context Configuration form."""
    title: Optional[str] = None
    research_questions: Optional[str] = None
    keyword_string: Optional[str] = None
    inclusion_criteria: Optional[list[str]] = None
    exclusion_criteria: Optional[list[str]] = None


class DatabaseCreate(BaseModel):
    name: str
    prefix: Optional[str] = None
    priority: Optional[int] = None


class DatabaseUpdate(BaseModel):
    """Partial update for an existing database's config."""
    name: Optional[str] = None
    prefix: Optional[str] = None
    priority: Optional[int] = None
    # Empty string clears the proxy; None leaves it unchanged.
    proxy_suffix: Optional[str] = None


class ConferenceImportRequest(BaseModel):
    """Import filtered papers from a running conference-toolkit instance."""
    url: str
    keyword_string: str = ""
    venue_ids: list[str] = Field(default_factory=list)
    use_llm: bool = False


class Paper(BaseModel):
    index: str
    database: str
    database_id: str
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    abstract: str = ""
    keywords: list[str] = Field(default_factory=list)
    doi: str = ""
    venue: str = ""
    url: str = ""
    source_file: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class ScreeningLabel(BaseModel):
    """Payload for setting a screening decision or comment."""
    label: Optional[str] = None
    comment: Optional[str] = None


class DatabaseSummary(BaseModel):
    id: str
    name: str
    prefix: str
    priority: int
    paper_count: int = 0
    index_range: Optional[str] = None
    source_files: list[str] = Field(default_factory=list)
