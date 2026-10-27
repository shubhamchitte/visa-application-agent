"""ReplayLLM: responses keyed by sha256(model, prompt, doc_id). Replay never touches the network;
record wraps a real client and saves to mock_data/replay/<case>.json. `make_llm` picks the provider from LLM_PROVIDER."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import LLMClient

REPLAY_DIR = Path(__file__).resolve().parents[2] / "mock_data" / "replay"


class StaleRecording(RuntimeError):
    """Not an LLMError on purpose: it must stop the run, not degrade fields to UNVERIFIABLE."""


def key(model: str, prompt: str, doc_id: str) -> str:
    return hashlib.sha256("\x00".join((model, prompt, doc_id)).encode()).hexdigest()


class ReplayLLM:
    name = "replay"

    def __init__(self, case: str, model: str = "recorded", record_with: LLMClient | None = None, directory: Path = REPLAY_DIR):
        self.path, self.inner = directory / f"{case}.json", record_with
        saved = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.cache: dict[str, Any] = saved.get("entries", {})
        self.model = getattr(record_with, "model", None) or saved.get("model", model)  # replay reads the model from the file

    def _cached(self, doc_id: str, prompt: str, call) -> Any:
        k = key(self.model, prompt, doc_id)
        if k not in self.cache:
            if self.inner is None:
                raise StaleRecording(f"recording stale: no entry in {self.path.name} for doc={doc_id} (prompt or schema changed, "
                                     "or never recorded); re-record with `make eval-live` or use LLM_PROVIDER=fake")
            out = call()  # provenance fields are for audit only; replay reads just "response"
            self.cache[k] = {"response": out, "doc_id": doc_id, "ts": datetime.now(timezone.utc).isoformat(),
                             **getattr(self.inner, "last_meta", {})}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"model": self.model, "entries": self.cache}, indent=1))
        return self.cache[k]["response"]

    def extract(self, doc_id: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        return self._cached(doc_id, prompt, lambda: self.inner.extract(doc_id, prompt, schema))

    def propose_tool_call(self, state: dict, tools: list, history: list) -> dict[str, Any]:
        return self._cached("agent", json.dumps([state, tools, history], sort_keys=True, default=str),
                            lambda: self.inner.propose_tool_call(state, tools, history))


def make_llm(case: str, packet: Path, replay: str | None = None, provider: str | None = None, record: bool = False) -> LLMClient:
    """packet = dir holding fake_llm.json; replay = recording name (default case; cases sharing a packet share prompts).
    provider: fake | gemini | groq | replay (default env LLM_PROVIDER, else fake)."""
    p = (provider or os.getenv("LLM_PROVIDER") or "fake").lower()
    if p == "fake":
        from .fake import FakeLLM
        script = json.loads((packet / "fake_llm.json").read_text())["script"]
        return FakeLLM(case, {(case, k): v for k, v in script.items()})
    if p == "replay":
        return ReplayLLM(replay or case)
    if p in ("gemini", "groq"):
        if p == "gemini":
            from .gemini import GeminiLLM as C
        else:
            from .groq import GroqLLM as C
        real = C(pause=8) if p == "groq" and record else C()
        return ReplayLLM(replay or case, record_with=real) if record else real
    raise ValueError(f"unknown LLM_PROVIDER {p!r}")
