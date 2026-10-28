"""Groq adapter: page-text prompt in, strict json_schema out, temperature 0. SDK errors -> llm.base taxonomy."""
import json
import os
import time
from typing import Any

from .base import Fatal, Malformed, RateLimited, map_error

BIG_CALL_TOKENS, BIG_CALL_WAIT = 3000, 60  # free tier is ~8K tokens/min: after a big call wait a full minute
_S = {"calls": 0, "r429": 0, "wait": 0.0}  # per process, shared by every client (eval builds one per case)


class GroqLLM:
    name = "groq"

    def __init__(self, client: Any = None, model: str | None = None, pause: float = 0):
        if client is None:
            from groq import Groq  # lazy: tests never import the SDK
            client = Groq(api_key=os.environ["GROQ_API_KEY"])
        self.pause, self.max_calls = pause, int(os.getenv("GROQ_MAX_CALLS", "40"))  # free-tier pacing + call budget
        self.client, self.model = client, model or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    def _chat(self, prompt: str, schema: dict[str, Any], name: str = "extraction") -> dict[str, Any]:
        """One strict-json_schema call; keeps provenance (request id, raw text, usage) in `last_meta` for recordings."""
        if self.pause and (_S["calls"] >= self.max_calls or _S["r429"] >= 2):  # live: budget cap, repeated 429s stop
            raise Fatal(f"stopped: {_S['calls']} calls made, {_S['r429']} consecutive 429s")
        time.sleep(_S["wait"])
        _S["calls"] += 1
        try:  # strict mode confirmed live: every key required, additionalProperties false
            resp = self.client.chat.completions.create(
                model=self.model, temperature=0, messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}})
            text = resp.choices[0].message.content
        except Exception as e:
            err = map_error(e)  # Retry-After read from e.response.headers
            _S["r429"] = _S["r429"] + 1 if isinstance(err, RateLimited) else 0
            if isinstance(err, RateLimited) and self.pause:  # live pacing: honour Retry-After (uncapped), once
                _S["wait"] = max(err.retry_after or BIG_CALL_WAIT, self.pause)
                return self._chat(prompt, schema, name)
            raise err from e
        _S["r429"] = 0
        used = getattr(getattr(resp, "usage", None), "total_tokens", None) or 0
        _S["wait"] = BIG_CALL_WAIT if used > BIG_CALL_TOKENS and self.pause else self.pause
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
