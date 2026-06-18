"""Abstract/Title Screening Agent (Phase 3).

Given a paper (title, abstract, keywords, year) and the review's inclusion /
exclusion criteria, the agent suggests a screening label
(Include / Exclude / Maybe) together with a short reasoning.

Implemented with LangChain (DeepSeek by default). If no LLM is configured the
caller receives a clear "unavailable" result rather than a crash.

Public API
----------
    LABELS  -> the valid label set
    screen_paper(paper, inclusion, exclusion, research_questions="") -> dict
        returns {"label": <Include|Exclude|Maybe|None>, "reasoning": str,
                 "available": bool}
"""
from __future__ import annotations

import json
import re
from typing import Any

from .llm import get_chat_model

LABELS = ("Include", "Exclude", "Maybe")

_PROMPT = (
    "You are screening a paper for a systematic literature review. Decide whether "
    "the paper should be INCLUDED, EXCLUDED, or marked MAYBE (uncertain) based "
    "strictly on the criteria below.\n\n"
    "INCLUSION CRITERIA:\n{inclusion}\n\n"
    "EXCLUSION CRITERIA:\n{exclusion}\n\n"
    "{rq_block}"
    "PAPER\n"
    "Title: {title}\n"
    "Year: {year}\n"
    "Keywords: {keywords}\n"
    "Abstract: {abstract}\n\n"
    "Decide using only the information given. If the abstract is insufficient to "
    "judge a criterion, lean towards 'Maybe'. Respond with ONLY a JSON object:\n"
    '{{"label": "Include" | "Exclude" | "Maybe", "reasoning": "<2-4 sentence justification '
    'referencing the relevant criteria>"}}'
)


def _fmt_list(items: Any) -> str:
    if isinstance(items, list):
        return "\n".join(f"- {i}" for i in items) if items else "(none provided)"
    if isinstance(items, str) and items.strip():
        return items
    return "(none provided)"


def screen_paper(
    paper: dict[str, Any],
    inclusion: Any,
    exclusion: Any,
    research_questions: str = "",
) -> dict[str, Any]:
    model = get_chat_model(temperature=0.0)
    if model is None:
        return {
            "label": None,
            "reasoning": "LLM is not configured. Set a provider API key in .env to enable AI suggestions.",
            "available": False,
        }

    rq_block = ""
    if research_questions and research_questions.strip():
        rq_block = f"RESEARCH QUESTIONS (for context):\n{research_questions.strip()}\n\n"

    try:
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_template(_PROMPT)
        chain = prompt | model
        result = chain.invoke({
            "inclusion": _fmt_list(inclusion),
            "exclusion": _fmt_list(exclusion),
            "rq_block": rq_block,
            "title": paper.get("title", "") or "(no title)",
            "year": paper.get("year") or "n/a",
            "keywords": ", ".join(paper.get("keywords", []) or []) or "(none)",
            "abstract": paper.get("abstract", "") or "(no abstract provided)",
        })
        content = getattr(result, "content", str(result))
        label, reasoning = _parse_decision(content)
        return {"label": label, "reasoning": reasoning, "available": True}
    except Exception as e:  # pragma: no cover - network/parsing safety net
        return {
            "label": None,
            "reasoning": f"AI suggestion failed: {e}",
            "available": False,
        }


def _parse_decision(content: str) -> tuple[str | None, str]:
    text = content.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
    except Exception:
        # Fall back to scanning the raw text for a label keyword.
        low = content.lower()
        for lab in LABELS:
            if lab.lower() in low:
                return lab, content.strip()[:600]
        return None, content.strip()[:600]

    label = str(data.get("label", "")).strip().capitalize()
    if label not in LABELS:
        label = None
    reasoning = str(data.get("reasoning", "")).strip()
    return label, reasoning
