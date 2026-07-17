"""User-defined Keyword Extraction Agent (Phase 5).

Given a free-text *description* of the kind of keyword the user cares about
(e.g. "the E-commerce task such as recommendation, product search, sale
assistant, shopping cart") and a paper's metadata, the agent extracts a small
set of concise keyword tags that match the description.

Implemented with LangChain (provider chosen via .env, DeepSeek by default). If
no LLM is configured the caller receives a clear "unavailable" result rather
than a crash — mirroring the abstract/title screening agent.

Public API
----------
    extract_keywords(paper, description, max_tags=5) -> dict
        returns {"items": [{"tag": str, "evidence": str}], "tags": list[str],
                 "available": bool, "error": str | None}
"""
from __future__ import annotations

import json
import re
from typing import Any

from .llm import get_chat_model

_PROMPT = (
    "You are tagging a research paper for a systematic literature review.\n\n"
    "The reviewer wants to extract keywords of ONE specific kind, described as:\n"
    "\"{description}\"\n\n"
    "Read the paper content below and extract ALL keyword tags that match this "
    "description. There is NO limit on the number of tags — do not restrict "
    "yourself to a few; include EVERY tag that is genuinely relevant to the "
    "paper. Rules:\n"
    "- Only return tags clearly supported by the paper; if none apply, return an "
    "empty list. Relevance is the only filter — never drop a relevant tag just to "
    "keep the list short.\n"
    "- Each tag must be a concise noun phrase (1-4 words), lowercase.\n"
    "- Use the most GENERAL canonical form of the concept (e.g. 'fine-tuning', "
    "not 'LoRA fine-tuning of BERT-base'); keep tags reusable across papers.\n"
    "- Do not invent tags unrelated to the described kind.\n"
    "{preferred_block}"
    "- For EACH tag, quote the exact sentence (or short span) from the "
    "{evidence_sources} that justifies it. Copy the evidence VERBATIM, "
    "character-for-character, so it can be located and highlighted in the text. "
    "Do not paraphrase the evidence.\n\n"
    "PAPER\n"
    "{paper_block}\n\n"
    "Respond with ONLY a JSON object of the form:\n"
    '{{"items": [{{"tag": "tag one", "evidence": "the verbatim supporting '
    'sentence"}}]}}'
)

# Selectable text sources for extraction. "title"/"abstract"/"keywords" together
# form the default "metadata" set; "fulltext" adds the extracted PDF body.
DEFAULT_SOURCES = ["title", "abstract", "keywords"]
_SOURCE_LABELS = {
    "title": "Title",
    "keywords": "Author keywords",
    "abstract": "Abstract",
    "fulltext": "Full text",
}
# Order the block/evidence list follows regardless of selection order.
_SOURCE_ORDER = ["title", "keywords", "abstract", "fulltext"]


def _clean_sources(sources: Any) -> list[str]:
    """Normalise a requested source list to known keys, preserving canonical
    order; fall back to the metadata default when nothing valid is given."""
    if not sources:
        return list(DEFAULT_SOURCES)
    req = {str(s).strip().lower() for s in sources}
    out = [s for s in _SOURCE_ORDER if s in req]
    return out or list(DEFAULT_SOURCES)


def _paper_block(paper: dict[str, Any], sources: list[str], full_text: str | None) -> str:
    """Build the PAPER section from the selected fields only. Year and Venue are
    always included as lightweight bibliographic context."""
    meta = _paper_meta(paper)
    lines: list[str] = []
    if "title" in sources:
        lines.append(f"Title: {meta['title']}")
    lines.append(f"Year: {meta['year']}")
    lines.append(f"Venue: {meta['venue']}")
    if "keywords" in sources:
        lines.append(f"Author keywords: {meta['keywords']}")
    if "abstract" in sources:
        lines.append(f"Abstract: {meta['abstract']}")
    if "fulltext" in sources:
        body = (full_text or "").strip() or "(no extracted full text available)"
        lines.append(f"Full text:\n{body}")
    return "\n".join(lines)


def _evidence_sources(sources: list[str]) -> str:
    """Human phrase naming the text fields the model may quote evidence from."""
    labels = [_SOURCE_LABELS[s] for s in sources if s in _SOURCE_LABELS]
    if not labels:
        return "provided text"
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + ", or " + labels[-1]


def normalize_tag(tag: str) -> str:
    """Canonical form used for de-duplication across papers and the tag pool."""
    t = re.sub(r"\s+", " ", str(tag or "").strip().lower())
    t = t.strip(" .,;:-")
    return t


def _paper_meta(paper: dict[str, Any]) -> dict[str, str]:
    return {
        "title": paper.get("title", "") or "(no title)",
        "year": str(paper.get("year") or "n/a"),
        "venue": paper.get("venue", "") or "(unknown)",
        "keywords": ", ".join(paper.get("keywords", []) or []) or "(none)",
        "abstract": paper.get("abstract", "") or "(no abstract provided)",
    }


def _normalize_preferred(preferred: Any) -> list[dict[str, str]]:
    """Accept preferred as [str] or [{tag, description}] -> [{tag, description}]."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for p in preferred or []:
        if isinstance(p, dict):
            tag = normalize_tag(p.get("tag", ""))
            desc = str(p.get("description", "") or "").strip()
        else:
            tag = normalize_tag(str(p))
            desc = ""
        if tag and tag not in seen:
            seen.add(tag)
            out.append({"tag": tag, "description": desc})
    return out


def _preferred_block(preferred: list[dict[str, str]]) -> str:
    if not preferred:
        return ""
    lines = "\n".join(
        f"  - {p['tag']}" + (f": {p['description']}" if p.get("description") else "")
        for p in preferred
    )
    return (
        "- PREFERRED KEYWORDS (each shown as 'label: meaning'): whenever one of "
        "these fits the paper, reuse the label EXACTLY as written; only introduce "
        "a new tag when none of them apply:\n" + lines + "\n"
    )


def extract_keywords(
    paper: dict[str, Any],
    description: str,
    preferred: Any = None,
    max_tags: int = 50,
    sources: Any = None,
    full_text: str | None = None,
) -> dict[str, Any]:
    if not (description or "").strip():
        return {"items": [], "tags": [], "available": False,
                "error": "No keyword description set."}

    model = get_chat_model(temperature=0.0)
    if model is None:
        return {
            "items": [],
            "tags": [],
            "available": False,
            "error": "LLM is not configured. Set a provider API key in .env to enable extraction.",
        }

    src = _clean_sources(sources)
    pref = _normalize_preferred(preferred)
    try:
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_template(_PROMPT)
        chain = prompt | model
        result = chain.invoke({
            "description": description.strip(),
            "preferred_block": _preferred_block(pref),
            "evidence_sources": _evidence_sources(src),
            "paper_block": _paper_block(paper, src, full_text),
        })
        content = getattr(result, "content", str(result))
        items = _parse_items(content, max_tags)
        return {
            "items": items,
            "tags": [it["tag"] for it in items],
            "available": True,
            "error": None,
        }
    except Exception as e:  # pragma: no cover - network/parsing safety net
        return {"items": [], "tags": [], "available": False,
                "error": f"Extraction failed: {e}"}


def _parse_items(content: str, max_tags: int) -> list[dict[str, str]]:
    """Parse the model output into [{'tag','evidence'}] with normalized tags.

    Accepts the preferred {"items":[{"tag","evidence"}]} shape, and degrades
    gracefully to a plain {"tags":[...]} / bare list (evidence empty).
    """
    text = content.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)

    raw_items: list[Any] = []
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            if isinstance(data.get("items"), list):
                raw_items = data["items"]
            elif isinstance(data.get("tags"), list):
                raw_items = data["tags"]
        elif isinstance(data, list):
            raw_items = data
    except Exception:
        raw_items = re.split(r"[,\n]", content)

    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for it in raw_items:
        if isinstance(it, dict):
            tag = normalize_tag(it.get("tag", ""))
            evidence = str(it.get("evidence", "") or "").strip()
        else:
            tag = normalize_tag(str(it))
            evidence = ""
        if tag and tag not in seen:
            seen.add(tag)
            out.append({"tag": tag, "evidence": evidence})
        if len(out) >= max_tags:
            break
    return out
