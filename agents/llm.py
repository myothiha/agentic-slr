"""Shared LangChain LLM factory.

Returns a configured chat model for the provider selected via the LLM_PROVIDER
environment variable. DeepSeek is the default and uses the OpenAI-compatible
endpoint (langchain_openai.ChatOpenAI with a custom base_url).

The factory degrades gracefully: if the relevant API key is missing or the
provider package is not installed, get_chat_model() returns None and callers
fall back to deterministic logic.
"""
from __future__ import annotations

import os
from typing import Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv optional
    pass


def get_chat_model(temperature: float = 0.0):
    """Build a LangChain chat model, or return None if unavailable."""
    provider = os.getenv("LLM_PROVIDER", "deepseek").lower()

    try:
        if provider == "deepseek":
            key = os.getenv("DEEPSEEK_API_KEY", "")
            if not key or key.startswith("your_"):
                return None
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                api_key=key,
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                temperature=temperature,
                timeout=60,
            )
        if provider == "openai":
            key = os.getenv("OPENAI_API_KEY", "")
            if not key or key.startswith("your_"):
                return None
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(model="gpt-4o-mini", api_key=key, temperature=temperature)
        if provider == "anthropic":
            key = os.getenv("ANTHROPIC_API_KEY", "")
            if not key or key.startswith("your_"):
                return None
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model="claude-3-5-sonnet-latest", api_key=key, temperature=temperature
            )
        if provider == "google":
            key = os.getenv("GOOGLE_API_KEY", "")
            if not key or key.startswith("your_"):
                return None
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model="gemini-1.5-flash", google_api_key=key, temperature=temperature
            )
    except Exception:
        return None
    return None


def provider_name() -> Optional[str]:
    return os.getenv("LLM_PROVIDER", "deepseek").lower()
