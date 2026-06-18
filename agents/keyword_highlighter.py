"""Keyword Highlighting Agent.

Converts a complex Boolean keyword string (the kind used to query academic
databases) into a deterministic set of highlight rules: a list of search terms
plus compiled regular expressions.

Design notes
------------
* Highlighting MUST be deterministic and reproducible, so the regex patterns
  are always compiled locally from the extracted term list — never by the LLM.
* A LangChain agent (DeepSeek by default) is used, when available, only to
  *extract and normalise* the meaningful terms from a messy Boolean string
  (handling nesting, near-operators, field tags like TITLE-ABS-KEY, etc.).
* If no LLM is configured, a robust deterministic tokenizer extracts the terms,
  so the feature works fully offline.

Public API
----------
    build_highlight_rules(keyword_string, use_llm=True) -> dict
    update_metadata_highlighting(metadata, use_llm=True) -> dict
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .llm import get_chat_model

# Boolean operators / stop tokens that are never themselves search terms.
_OPERATORS = {"AND", "OR", "NOT", "NEAR", "ONEAR", "W", "PRE", "ADJ"}
# Common database field qualifiers to strip (Scopus / WoS / etc.).
_FIELD_TAGS = {
    "TITLE", "ABS", "KEY", "TITLE-ABS-KEY", "TS", "TI", "AB", "AK", "AU",
    "SO", "ALL", "PUBYEAR", "DOCTYPE", "LANGUAGE",
}


# --------------------------------------------------------------------------- #
# Deterministic extraction
# --------------------------------------------------------------------------- #
def extract_terms_deterministic(keyword_string: str) -> list[str]:
    """Pull quoted phrases and bare keywords out of a Boolean query."""
    if not keyword_string:
        return []

    s = keyword_string

    # Remove field qualifiers like  TITLE-ABS-KEY( ... )  -> keep inner content.
    s = re.sub(r"\b[A-Z][A-Z\-]+\s*\(", "(", s)
    # Drop NEAR/n, W/n, PRE/n proximity operators.
    s = re.sub(r"\b(?:NEAR|ONEAR|W|PRE|ADJ)\s*/?\s*\d+\b", " ", s, flags=re.IGNORECASE)

    terms: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        t = term.strip().strip(".,;:")
        if not t:
            return
        if t.upper() in _OPERATORS or t.upper() in _FIELD_TAGS:
            return
        if len(t) <= 1:
            return
        key = t.lower()
        if key not in seen:
            seen.add(key)
            terms.append(t)

    # 1. Quoted phrases first (single or double quotes / typographic quotes).
    quote_pat = re.compile(r'[\"“”\'‘’]([^\"“”\'‘’]+)[\"“”\'‘’]')
    for m in quote_pat.finditer(s):
        _add(m.group(1))
    remainder = quote_pat.sub(" ", s)

    # 2. Bare tokens, splitting on operators, parentheses and whitespace.
    remainder = re.sub(r"[()]", " ", remainder)
    for token in re.split(r"\s+", remainder):
        token = token.strip()
        if not token:
            continue
        _add(token)

    return terms


def _term_to_regex(term: str) -> str:
    r"""Compile a single term into a highlight regex string.

    * `*` -> `\w*`   (truncation/wildcard)
    * `?` -> `\w`    (single-character wildcard)
    * phrases allow flexible internal whitespace
    * word boundaries are applied where the edge is alphanumeric
    """
    # Tokenise into words, keeping wildcard characters attached.
    words = re.split(r"\s+", term.strip())
    parts = []
    for w in words:
        chunk = ""
        for ch in w:
            if ch == "*":
                chunk += r"\w*"
            elif ch == "?":
                chunk += r"\w"
            else:
                chunk += re.escape(ch)
        parts.append(chunk)
    body = r"\s+".join(parts)

    # Apply word boundaries only when the outer edge is a word character.
    left = r"\b" if re.match(r"\w", term[0]) else ""
    right = r"\b" if re.search(r"\w$", term) and not term.endswith("*") else ""
    return f"{left}{body}{right}"


def compile_patterns(terms: list[str]) -> list[str]:
    patterns = []
    for t in terms:
        pat = _term_to_regex(t)
        try:
            re.compile(pat, re.IGNORECASE)
            patterns.append(pat)
        except re.error:
            patterns.append(re.escape(t))
    return patterns


# --------------------------------------------------------------------------- #
# LangChain-assisted extraction
# --------------------------------------------------------------------------- #
_EXTRACT_PROMPT = (
    "You are a systematic-literature-review assistant. Extract the meaningful "
    "search terms and phrases from the Boolean query below. Rules:\n"
    "- Return ONLY the substantive concepts a reader should see highlighted.\n"
    "- Keep multi-word phrases intact (e.g. \"machine learning\").\n"
    "- Preserve truncation wildcards such as optimi* exactly as written.\n"
    "- Exclude Boolean operators (AND, OR, NOT), proximity operators, field "
    "tags (TITLE-ABS-KEY, TS, etc.) and parentheses.\n"
    "- Deduplicate case-insensitively.\n"
    'Respond with a JSON object: {{"terms": ["term1", "term2", ...]}} and nothing else.\n\n'
    "Boolean query:\n{query}"
)


def extract_terms_llm(keyword_string: str) -> list[str] | None:
    """Use the configured LangChain model to extract terms. None on failure."""
    model = get_chat_model(temperature=0.0)
    if model is None:
        return None
    try:
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_template(_EXTRACT_PROMPT)
        chain = prompt | model
        result = chain.invoke({"query": keyword_string})
        content = getattr(result, "content", str(result))
        terms = _parse_terms_json(content)
        return terms or None
    except Exception:
        return None


def _parse_terms_json(content: str) -> list[str]:
    # Strip markdown fences if present.
    text = content.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
    except Exception:
        return []
    terms = data.get("terms", []) if isinstance(data, dict) else []
    out, seen = [], set()
    for t in terms:
        if isinstance(t, str) and t.strip() and t.strip().lower() not in seen:
            seen.add(t.strip().lower())
            out.append(t.strip())
    return out


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #
def build_highlight_rules(keyword_string: str, use_llm: bool = True) -> dict[str, Any]:
    """Produce highlight rules for a keyword string.

    Returns dict: {terms, patterns, compiled_at, source}
    """
    source = "deterministic"
    terms: list[str] = []

    if use_llm and keyword_string.strip():
        llm_terms = extract_terms_llm(keyword_string)
        if llm_terms:
            terms = llm_terms
            source = "agent"

    if not terms:
        terms = extract_terms_deterministic(keyword_string)

    patterns = compile_patterns(terms)
    return {
        "terms": terms,
        "patterns": patterns,
        "compiled_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
    }


def update_metadata_highlighting(metadata: dict[str, Any], use_llm: bool = True) -> dict[str, Any]:
    """Recompute highlight rules from metadata['keyword_string'] in place."""
    rules = build_highlight_rules(metadata.get("keyword_string", ""), use_llm=use_llm)
    metadata["highlight_rules"] = rules
    return metadata


if __name__ == "__main__":  # quick manual check
    q = '("machine learning" OR ML) AND (secur* OR privacy) AND "neural network"'
    print(json.dumps(build_highlight_rules(q, use_llm=False), indent=2))
