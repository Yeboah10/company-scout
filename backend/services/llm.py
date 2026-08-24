import json
import re
import time

from google import genai
from google.genai import errors as genai_errors

from backend.config import settings
from backend.services.usage import usage


class QuotaExhaustedError(Exception):
    """The daily free-tier allowance is spent.

    Distinct from ordinary rate limiting because waiting cannot help: the
    quota resets on a daily boundary, not in seconds.
    """


def _is_daily_quota_error(message: str) -> bool:
    """Tell a spent daily allowance apart from per-minute throttling.

    Both surface as HTTP 429, but only one is worth waiting out. Google names
    the specific quota in the error body, e.g.
    "GenerateRequestsPerDayPerProjectPerModel-FreeTier".
    """
    lowered = message.lower()
    return "perday" in lowered or "requests_per_day" in lowered


class AllModelsExhaustedError(QuotaExhaustedError):
    """Every model in the chain has spent its daily allowance."""


class LLMService:
    def __init__(self, model: str | None = None, fallbacks: list[str] | None = None):
        self.client = genai.Client(api_key=settings.google_api_key)
        self.model = model or settings.llm_model
        # The free tier's daily cap is per model, so an exhausted model is a
        # reason to switch rather than to stop.
        chain = [self.model] + (
            fallbacks if fallbacks is not None else settings.fallback_models
        )
        seen: set[str] = set()
        self.chain = [m for m in chain if not (m in seen or seen.add(m))]

    def _next_model(self) -> str | None:
        """The first model in the chain with budget left today."""
        for model in self.chain:
            if not usage.is_exhausted(model):
                return model
        return None

    def extract_structured(self, system_prompt: str, user_prompt: str, retries: int = 2) -> dict:
        for attempt in range(retries + 1):
            try:
                response = self._call_with_rate_limit_retry(system_prompt, user_prompt)
            except AllModelsExhaustedError:
                # Every Gemini model in the chain is spent for today — not
                # one model's bad call, the whole provider's free tier. Groq
                # is reached for only here, never as competition for a call
                # Gemini could still have served.
                from backend.services import external_llm, monitoring

                if external_llm.any_configured():
                    print(
                        "       Gemini's free tier is fully spent today — "
                        "trying external fallback providers",
                        flush=True,
                    )
                    monitoring.warn(
                        "Gemini daily quota exhausted; used external fallback"
                    )
                    return external_llm.extract_structured(system_prompt, user_prompt)
                raise
            except QuotaExhaustedError:
                # Retrying cannot succeed, and each attempt costs the caller
                # another wait for nothing.
                raise
            except Exception:
                if attempt < retries:
                    continue
                raise

            text = response.text
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                text = _clean_json(text)
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    if attempt < retries:
                        continue
                    raise

    def _call_with_rate_limit_retry(self, system_prompt: str, user_prompt: str, max_waits: int = 3):
        model = self._next_model()
        if model is None:
            raise AllModelsExhaustedError(
                "Every available Gemini model has used its daily free-tier "
                "allowance. They reset at midnight Pacific time."
            )
        if model != self.model:
            print(f"       Switching to {model} ({self.model} is spent)", flush=True)

        # Model switches and rate-limit waits are counted separately: moving to
        # a fresh model is not a failed attempt, and sharing one budget between
        # them would let a couple of switches consume the retry allowance.
        waits = 0
        while True:
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=f"{system_prompt}\n\n{user_prompt}",
                    config=genai.types.GenerateContentConfig(
                        temperature=0.1,
                        max_output_tokens=8192,
                        response_mime_type="application/json",
                    ),
                )
                usage.record_gemini(model)
                return response
            except genai_errors.ClientError as e:
                message = str(e)
                if "429" not in message:
                    raise

                # A spent daily allowance cannot be waited out, but it applies
                # only to this model. Note it and move on, so the other models'
                # untouched budgets still get used.
                if _is_daily_quota_error(message):
                    usage.mark_exhausted(model)
                    nxt = self._next_model()
                    if nxt is None:
                        raise AllModelsExhaustedError(
                            "Every available Gemini model has spent its daily "
                            "free-tier allowance. They reset at midnight "
                            "Pacific time."
                        ) from e
                    print(f"       {model} is spent; switching to {nxt}", flush=True)
                    model = nxt
                    continue

                # Per-minute throttling: this one is worth waiting out.
                if waits < max_waits:
                    waits += 1
                    wait_time = 20 * waits
                    print(
                        f"       Rate limited. Waiting {wait_time}s before retry...",
                        flush=True,
                    )
                    time.sleep(wait_time)
                    continue
                raise


def _clean_json(text: str) -> str:
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        start = text.find("[")
        end = text.rfind("]") + 1
    if start != -1 and end > 0:
        text = text[start:end]
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text
