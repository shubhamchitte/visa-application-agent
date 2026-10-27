"""Groq adapter: page-text prompt in, strict json_schema out, temperature 0. SDK errors -> llm.base taxonomy."""
import json
import os
import time
from typing import Any

from .base import Malformed, map_error


class GroqLLM:
    name = "groq"

    def __init__(self, client: Any = None, model: str | None = None, pause: float = 0):
        if client is None:
            from groq import Groq  # lazy: tests never import the SDK
            client = Groq(api_key=os.environ["GROQ_API_KEY"])
        self.pause = pause  # free-tier pacing (seconds before each call)
        self.client, self.model = client, model or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    def _chat(self, prompt: str, schema: dict[str, Any], name: str = "extraction") -> dict[str, Any]:
        """One strict-json_schema call; keeps provenance (request id, raw text, usage) in `last_meta` for recordings."""
        time.sleep(self.pause)
        try:  # strict mode confirmed live: every key required, additionalProperties false
            resp = self.client.chat.completions.create(
                model=self.model, temperature=0, messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}})
            text = resp.choices[0].message.content
        except Exception as e:
            raise map_error(e) from e  # Retry-After read from e.response.headers
        xg = getattr(resp, "x_groq", None)
        self.last_meta = {"request_id": getattr(xg, "id", None) or getattr(resp, "id", None), "raw": text,
                          "usage": getattr(getattr(resp, "usage", None), "total_tokens", None)}
        try:
            return json.loads(text)
        except (TypeError, json.JSONDecodeError) as e:
            raise Malformed(f"not JSON: {e}") from e

    def extract(self, doc_id: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        return self._chat(prompt, schema)

    def propose_tool_call(self, state: dict, tools: list, history: list) -> dict[str, Any]:
        """Agent mode: one proposed call via strict json_schema (args as a JSON string; native tools can't combine with it)."""
        schema = {"type": "object", "additionalProperties": False, "required": ["done", "tool", "args_json"],
                  "properties": {"done": {"type": "boolean"}, "tool": {"type": ["string", "null"]}, "args_json": {"type": ["string", "null"]}}}
        out = self._chat("You operate a visa-application CRM. Propose ONE next tool call, or done=true when finished. "
                         "Use the verified state only; the plan field says what may be written. Args as a JSON object string.\n"
                         + json.dumps({"state": state, "tools": tools, "history": history}), schema, "tool_call")
        try:
            return {"done": True} if out["done"] else {"tool": out["tool"], "args": json.loads(out["args_json"] or "{}")}
        except (TypeError, json.JSONDecodeError) as e:
            raise Malformed(f"bad args_json: {e}") from e
