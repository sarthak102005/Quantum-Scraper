"""
shared/utils/llm_utils.py

Provides common LLM fallback logic to decouple agents and extraction MCPs.
"""

from __future__ import annotations

import asyncio
from typing import Any
from google import genai
from google.genai import types as genai_types
from groq import AsyncGroq
from openai import AsyncOpenAI

from shared.utils.config import Config
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class LLMProviderError(Exception):
    """Raised when all LLM providers are exhausted."""


async def _try_gemini(model: str, api_key: str, prompt: str) -> str:
    """Attempt a Gemini API call using the new google.genai package."""
    client = genai.Client(api_key=api_key)
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=model,
        contents=prompt,
    )
    return response.text



async def _try_groq(model: str, api_key: str, prompt: str) -> str:
    """Attempt a Groq API call."""
    client = AsyncGroq(api_key=api_key)
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4096,
    )
    return response.choices[0].message.content or ""


async def _try_openrouter(model: str, api_key: str, prompt: str) -> str:
    """Attempt an OpenRouter API call (OpenAI-compatible)."""
    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4096,
    )
    return response.choices[0].message.content or ""


async def llm_with_fallback(prompt: str, config: Config) -> str:
    """Execute a prompt through the LLM fallback chain.

    Order: Gemini → Groq → OpenRouter
    """
    providers = [
        ("gemini", _try_gemini, config.llm.gemini_model, config.llm.google_api_key),
        ("groq", _try_groq, config.llm.groq_model, config.llm.groq_api_key),
        ("openrouter", _try_openrouter, config.llm.openrouter_model, config.llm.openrouter_api_key),
    ]

    last_error: Exception | None = None
    for name, fn, model, api_key in providers:
        if not api_key:
            logger.warning("LLM provider skipped — no API key", provider=name)
            continue
        try:
            logger.info("Trying LLM provider", provider=name, model=model)
            # Strip system instructions if calling Groq to avoid function parse issues
            clean_prompt = prompt
            if name == "groq":
                clean_prompt = prompt.replace("Extract product details from the web page source text provided below.", "").strip()
            result = await fn(model, api_key, clean_prompt)
            logger.info("LLM provider succeeded", provider=name)
            return result
        except Exception as e:
            logger.warning("LLM provider failed", provider=name, error=str(e))
            last_error = e

    raise LLMProviderError(f"All LLM providers exhausted. Last error: {last_error}")

