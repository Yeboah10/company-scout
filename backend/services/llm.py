import json
import re
import time

from google import genai
from google.genai import errors as genai_errors

from backend.config import settings


class LLMService:
    def __init__(self):
        self.client = genai.Client(api_key=settings.google_api_key)
        self.model = settings.llm_model

    def extract_structured(self, system_prompt: str, user_prompt: str, retries: int = 2) -> dict:
        for attempt in range(retries + 1):
            try:
                response = self._call_with_rate_limit_retry(system_prompt, user_prompt)
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
        for wait_attempt in range(max_waits + 1):
            try:
                return self.client.models.generate_content(
                    model=self.model,
                    contents=f"{system_prompt}\n\n{user_prompt}",
                    config=genai.types.GenerateContentConfig(
                        temperature=0.1,
                        max_output_tokens=8192,
                        response_mime_type="application/json",
                    ),
                )
            except genai_errors.ClientError as e:
                if "429" in str(e) and wait_attempt < max_waits:
                    wait_time = 20 * (wait_attempt + 1)
                    print(f"       Rate limited. Waiting {wait_time}s before retry...")
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
