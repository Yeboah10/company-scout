"""Groq — the last resort when every Gemini model's daily allowance is spent.

This is not a substitute for Gemini and never competes with it for a call.
LLMService reaches for this module in exactly one situation: every model in
its Gemini chain has already hit AllModelsExhaustedError today. Until then,
Gemini behaves exactly as it always has.

Groq's API is OpenAI-compatible, so this is one httpx call rather than a new
SDK dependency — httpx is already required. Off unless GROQ_API_KEY is set;
with no key, the pipeline's behaviour is unchanged from before this file
existed, because LLMService still just raises.
"""

import httpx

from backend.config import settings
from backend.services.llm import _clean_json
from backend.services.usage import usage

_API = "https://api.groq.com/openai/v1/chat/completions"
_TIMEOUT = 60.0


def is_configured() -> bool:
    return bool(settings.groq_api_key)


def extract_structured(system_prompt: str, user_prompt: str) -> dict:
    """Same contract as LLMService.extract_structured: prompts in, a dict
    out. Raises on failure — there is nowhere further to fall back to."""
    import json

    response = httpx.post(
        _API,
        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
        json={
            "model": settings.groq_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        },
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    usage.record_groq()

    text = response.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_clean_json(text))
