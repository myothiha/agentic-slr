"""Keyword Definition Suggester Agent (Phase 5 helper).

Given a keyword dimension (the "Task", e.g. "LLM technique") and the metadata of
the Include papers, suggest either:
  * a concise natural-language *description* of what the dimension means for this
    corpus, or
  * a list of general, canonical *preferred keywords* for it.

Reads a compact digest of the corpus (all titles, the most frequent author
keywords, and a spread of sampled abstracts) rather than every full abstract, so
the prompt stays within a reasonable size. Degrades gracefully when no LLM is
configured.

Public API
----------
    suggest(name, description, papers, target) -> dict
        target ∈ {"description", "keywords"}
        returns {"description": str|None, "keywords": list[str]|None,
                 "available": bool, "error": str|None}
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from .keyword_extraction import normalize_tag
from .llm import get_chat_model

_DESC_PROMPT = (
    "You are helping set up a keyword dimension for a systematic literature "
    "review. The dimension (the 'Task') is named:\n\"{name}\"\n\n"
    "Below is a digest of the papers to be tagged (titles, frequent author "
    "keywords, and sampled abstracts).\n\n{digest}\n\n"
    "Write a concise 2-4 sentence DESCRIPTION of what this dimension means for "
    "THIS corpus: what kind of keyword should be extracted from each paper, with "
    "a few representative examples that actually appear above. End by telling the "
    "extractor to ignore unrelated aspects. Respond with ONLY JSON:\n"
    '{{"description": "..."}}'
)

_KW_PROMPT = (
    "You are helping set up a keyword dimension for a systematic literature "
    "review. The dimension (the 'Task') is named:\n\"{name}\"\n"
    "Its description is:\n\"{description}\"\n\n"
    "Below is a digest of the papers to be tagged (titles, frequent author "
    "keywords, and sampled abstracts).\n\n{digest}\n\n"
    "Suggest 15-25 PREFERRED KEYWORDS for this dimension: general, canonical, "
    "reusable labels (lowercase, 1-4 words each) grounded in what appears above. "
    "Use the most general form (e.g. 'fine-tuning', not 'LoRA fine-tuning of "
    "BERT'). For EACH keyword add a one-sentence description explaining what it "
    "means and when a paper should get it. Do not include keywords unrelated to "
    "the dimension. Respond with ONLY JSON:\n"
    '{{"keywords": [{{"tag": "...", "description": "..."}}]}}'
)

_DESCRIBE_PROMPT = (
    "For a systematic-literature-review keyword dimension named \"{name}\" "
    "(meaning: {description}), write a ONE-sentence description for each keyword "
    "tag below — explaining what it means and when a paper should receive it. "
    "Keep each description concise and specific to this dimension.\n\n"
    "TAGS:\n{tags}\n\n"
    "Respond with ONLY JSON mapping each tag to its description:\n"
    '{{"descriptions": {{"tag one": "...", "tag two": "..."}}}}'
)


def _digest(
    papers: list[dict[str, Any]],
    max_titles: int = 150,
    max_keywords: int = 80,
    sample_abstracts: int = 20,
) -> str:
    titles = [str(p.get("title", "")).strip() for p in papers if p.get("title")]
    titles = titles[:max_titles]

    kw: Counter = Counter()
    for p in papers:
        for k in (p.get("keywords") or []):
            norm = str(k).strip().lower()
            if norm:
                kw[norm] += 1
    top_kw = [f"{k} ({c})" for k, c in kw.most_common(max_keywords)]

    abstracts = [str(p.get("abstract", "")).strip() for p in papers if p.get("abstract")]
    step = max(1, len(abstracts) // sample_abstracts) if abstracts else 1
    sampled = [a[:300] for a in abstracts[::step][:sample_abstracts]]

    parts = [f"PAPER COUNT: {len(papers)}"]
    if titles:
        parts.append("TITLES:\n" + "\n".join(f"- {t}" for t in titles))
    if top_kw:
        parts.append("FREQUENT AUTHOR KEYWORDS:\n" + ", ".join(top_kw))
    if sampled:
        parts.append("SAMPLE ABSTRACTS:\n" + "\n---\n".join(sampled))
    return "\n\n".join(parts)


def suggest(
    name: str,
    description: str,
    papers: list[dict[str, Any]],
    target: str = "description",
) -> dict[str, Any]:
    base = {"description": None, "keywords": None, "available": False, "error": None}
    if not (name or "").strip():
        return {**base, "error": "Set the dimension name first."}
    if not papers:
        return {**base, "error": "No Include papers available to learn from."}

    model = get_chat_model(temperature=0.2)
    if model is None:
        return {**base, "error": "LLM is not configured. Set a provider API key in .env."}

    digest = _digest(papers)
    try:
        from langchain_core.prompts import ChatPromptTemplate

        if target == "keywords":
            prompt = ChatPromptTemplate.from_template(_KW_PROMPT)
            result = (prompt | model).invoke({
                "name": name.strip(),
                "description": (description or "").strip() or "(not set yet)",
                "digest": digest,
            })
            content = getattr(result, "content", str(result))
            return {**base, "keywords": _parse_keyword_pairs(content), "available": True}
        else:
            prompt = ChatPromptTemplate.from_template(_DESC_PROMPT)
            result = (prompt | model).invoke({"name": name.strip(), "digest": digest})
            content = getattr(result, "content", str(result))
            return {**base, "description": _parse_description(content), "available": True}
    except Exception as e:  # pragma: no cover - network/parse safety net
        return {**base, "error": f"Suggestion failed: {e}"}


def _json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_description(content: str) -> str:
    data = _json_object(content)
    desc = data.get("description")
    if isinstance(desc, str) and desc.strip():
        return desc.strip()
    # Fallback: use the raw text if the model didn't return clean JSON.
    return content.strip()


def _parse_keyword_pairs(content: str) -> list[dict[str, str]]:
    """Parse suggested keywords as [{tag, description}] (tolerant of bare lists)."""
    data = _json_object(content)
    raw = data.get("keywords")
    if not isinstance(raw, list):
        raw = re.split(r"[,\n]", content)
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for k in raw:
        if isinstance(k, dict):
            tag = normalize_tag(k.get("tag", ""))
            desc = str(k.get("description", "") or "").strip()
        else:
            tag = normalize_tag(str(k))
            desc = ""
        if tag and tag not in seen:
            seen.add(tag)
            out.append({"tag": tag, "description": desc})
    return out


def describe_tags(
    name: str, description: str, tags: list[str]
) -> dict[str, Any]:
    """Generate a short description for each tag in ``tags``.

    Used to describe NEW tags the extraction agent invents (and any preferred
    tag missing a description). Returns
    {"descriptions": {tag: desc}, "available": bool, "error": str|None}.
    """
    tags = [normalize_tag(t) for t in tags if normalize_tag(t)]
    if not tags:
        return {"descriptions": {}, "available": True, "error": None}
    model = get_chat_model(temperature=0.2)
    if model is None:
        return {"descriptions": {}, "available": False,
                "error": "LLM is not configured."}
    try:
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_template(_DESCRIBE_PROMPT)
        result = (prompt | model).invoke({
            "name": (name or "").strip() or "(unnamed)",
            "description": (description or "").strip() or "(none)",
            "tags": "\n".join(f"- {t}" for t in tags),
        })
        content = getattr(result, "content", str(result))
        data = _json_object(content)
        raw = data.get("descriptions", {})
        out: dict[str, str] = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                tag = normalize_tag(k)
                if tag in tags and isinstance(v, str):
                    out[tag] = v.strip()
        return {"descriptions": out, "available": True, "error": None}
    except Exception as e:  # pragma: no cover
        return {"descriptions": {}, "available": False, "error": f"Describe failed: {e}"}
