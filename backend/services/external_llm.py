"""External fallback providers, tried only after Gemini's whole free tier is
spent for the day.

None of these compete with Gemini for a call. LLMService reaches here in one
situation only: AllModelsExhaustedError, meaning every model in the Gemini
chain has already used its daily allowance today, not just one.

Groq and Cerebras both speak the same OpenAI-compatible chat-completions
shape, so one small class covers both rather than two near-identical files.
Tried in order; the first configured provider that succeeds wins. A provider
that isn't configured is skipped silently — a provider that IS configured but
fails prints why and moves to the next one, so a bad key is diagnosable
rather than a bare stack trace.
"""

import json

import httpx

from backend.config import settings
from backend.services.llm import _clean_json
from backend.services.usage import usage

_TIMEOUT = 60.0


class _Provider:
    def __init__(self, name, base_url, get_key, get_model, record_usage):
        self.name = name
        self.base_url = base_url
        self._get_key = get_key
        self._get_model = get_model
        self._record_usage = record_usage

    def is_configured(self) -> bool:
        return bool(self._get_key())

    def call(self, system_prompt: str, user_prompt: str) -> dict:
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._get_key()}"},
            json={
                "model": self._get_model(),
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
        self._record_usage()

        text = response.json()["choices"][0]["message"]["content"]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return json.loads(_clean_json(text))


# Order matters: tried top to bottom, first configured success wins.
PROVIDERS = [
    _Provider(
        "Groq", "https://api.groq.com/openai/v1",
        lambda: settings.groq_api_key, lambda: settings.groq_model,
        usage.record_groq,
    ),
    _Provider(
        "Cerebras", "https://api.cerebras.ai/v1",
        lambda: settings.cerebras_api_key, lambda: settings.cerebras_model,
        usage.record_cerebras,
    ),
]


def any_configured() -> bool:
    return any(p.is_configured() for p in PROVIDERS)


def extract_structured(system_prompt: str, user_prompt: str) -> dict:
    """Try each configured provider in order.

    Raises the last provider's own error if every configured one failed —
    that error is more informative than a generic "no fallback available"
    would be, since by that point at least one really was tried.
    """
    last_error: Exception | None = None
    for provider in PROVIDERS:
        if not provider.is_configured():
            continue
        try:
            print(f"       Trying {provider.name} as fallback...", flush=True)
            return provider.call(system_prompt, user_prompt)
        except Exception as e:
            print(f"       {provider.name} fallback failed: {e}", flush=True)
            last_error = e
            continue

    if last_error is not None:
        raise last_error
    raise RuntimeError("No fallback LLM provider is configured")
