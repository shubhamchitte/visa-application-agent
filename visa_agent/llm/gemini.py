"""Gemini adapter: page-text prompt in, JSON out, temperature 0. SDK errors -> llm.base taxonomy."""
import json
import os
from typing import Any

from .base import Malformed, map_error


class GeminiLLM:
    name = "gemini"

    def __init__(self, client: Any = None, model: str | None = None):
        if client is None:
            from google import genai  # lazy: tests never import the SDK
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.client, self.model = client, model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")  # VERIFY-P0 model id

    def extract(self, doc_id: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        try:
            from google.genai import types  # VERIFY-P0 types.GenerateContentConfig + response_json_schema
            resp = self.client.models.generate_content(model=self.model, contents=prompt, config=types.GenerateContentConfig(
                temperature=0, response_mime_type="application/json", response_json_schema=schema))
            text = resp.text
        except Exception as e:
            raise map_error(e) from e  # VERIFY-P0 Gemini 429 Retry-After: may be in error details (RetryInfo), not a header
        try:
            return json.loads(text)
        except (TypeError, json.JSONDecodeError) as e:  # blocked/empty response gives text None
            raise Malformed(f"not JSON: {e}") from e
