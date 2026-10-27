"""Deterministic offline LLM for tests: canned responses keyed by (case, doc_id)."""
import json
from typing import Any

from .base import LLMError, Malformed


class FakeLLM:
    """`script[(case, doc_id)]` is a list consumed one item per call.
    An item is a dict (returned), an LLMError (raised), or a str (raw text -> Malformed if not JSON)."""
    name = "fake"

    def __init__(self, case: str, script: dict[tuple[str, str], list[Any]], agent_script: list | None = None):
        self.case = case
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[str] = []
        self.agent_script = list(agent_script or [])  # agent mode: tool-call proposals, one per step

    def propose_tool_call(self, state: dict, tools: list, history: list) -> dict[str, Any]:
        """Next scripted {"tool", "args"} (or {"done": True}); a callable item gets (state, history)."""
        item = self.agent_script.pop(0) if self.agent_script else {"done": True}
        return item(state, history) if callable(item) else item

    def extract(self, doc_id: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(doc_id)
        queue = self.script.get((self.case, doc_id))
        if not queue:
            raise KeyError(f"FakeLLM has no response for {(self.case, doc_id)}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]  # last item repeats
        if isinstance(item, LLMError):
            raise item
        if isinstance(item, str):
            try:
                return json.loads(item)
            except json.JSONDecodeError as e:
                raise Malformed(f"not JSON: {e}") from e
        return item
