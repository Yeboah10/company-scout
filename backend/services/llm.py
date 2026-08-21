import json

import anthropic

from backend.config import settings


class LLMService:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.llm_model

    def extract_structured(self, system_prompt: str, user_prompt: str) -> dict:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            start = text.find("[")
            end = text.rfind("]") + 1
        return json.loads(text[start:end])
