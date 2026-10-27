"""Adapters and ReplayLLM with mocked SDK clients: no network, no SDK import."""
import json
from types import SimpleNamespace as NS

import pytest

from visa_agent.llm.base import Fatal, Malformed, RateLimited, Transient, map_error
from visa_agent.llm.gemini import GeminiLLM
from visa_agent.llm.groq import GroqLLM
from visa_agent.llm.replay import ReplayLLM, StaleRecording, make_llm


class RateLimitError(Exception):
    status_code = 429
    response = NS(headers={"retry-after": "7"})


class APITimeoutError(Exception):
    pass


class ServerError(Exception):
    code = 503


class BadReq(Exception):
    status_code = 400


def groq_client(result=None, exc=None):
    def create(**kw):
        assert kw["temperature"] == 0 and kw["response_format"]["json_schema"]["strict"]
        if exc:
            raise exc
        return NS(choices=[NS(message=NS(content=result))])
    return NS(chat=NS(completions=NS(create=create)))


def gemini_client(text=None, exc=None):
    def gen(**kw):
        if exc:
            raise exc
        return NS(text=text)
    return NS(models=NS(generate_content=gen))


@pytest.mark.parametrize("exc,cls", [(RateLimitError("x"), RateLimited), (APITimeoutError("t"), Transient),
                                     (ServerError("s"), Transient), (BadReq("b"), Fatal)])
def test_groq_error_mapping(exc, cls):
    with pytest.raises(cls) as ei:
        GroqLLM(groq_client(exc=exc), "m").extract("d", "p", {})
    if cls is RateLimited:
        assert ei.value.retry_after == 7.0 and ei.value.retryable


def test_gemini_error_mapping_and_malformed():
    with pytest.raises(Transient):
        GeminiLLM(gemini_client(exc=ServerError("down")), "m").extract("d", "p", {})
    with pytest.raises(Malformed):
        GeminiLLM(gemini_client(text="not json"), "m").extract("d", "p", {})
    with pytest.raises(Malformed):
        GeminiLLM(gemini_client(text=None), "m").extract("d", "p", {})


def test_groq_success_and_malformed():
    assert GroqLLM(groq_client('{"a": 1}'), "m").extract("d", "p", {}) == {"a": 1}
    with pytest.raises(Malformed):
        GroqLLM(groq_client("nope"), "m").extract("d", "p", {})


def test_map_error_passthrough():
    e = Malformed("x")
    assert map_error(e) is e


def test_replay_record_then_replay_and_miss(tmp_path):
    inner = GroqLLM(groq_client('{"a": 1}'), "model-X")
    ReplayLLM("c", record_with=inner, directory=tmp_path).extract("d", "p", {})
    assert json.loads((tmp_path / "c.json").read_text())["model"] == "model-X"
    r = ReplayLLM("c", directory=tmp_path)  # no inner client, no env var: model comes from the file
    assert r.extract("d", "p", {}) == {"a": 1}
    with pytest.raises(StaleRecording, match="recording stale"):
        r.extract("d", "other prompt", {})


def test_stale_recording_stops_the_run_not_degrades_it(tmp_path):
    from visa_agent.extract import extract
    doc = {"doc_id": "d", "pages": [{"page": 1, "text": "x"}]}
    with pytest.raises(StaleRecording):
        extract(doc, "passport", ["full_name"], ReplayLLM("none", directory=tmp_path))


def test_schema_is_strict_compliant():
    from visa_agent.extract import schema_for
    s = schema_for(["a", "b"])
    def walk(n):
        if n.get("type") == "object":
            assert n["additionalProperties"] is False and set(n["required"]) == set(n["properties"])
            for v in n["properties"].values():
                walk(v)
    walk(s)
    assert s["properties"]["fields"]["required"] == ["a", "b"]


def test_noneval_does_not_write_results(tmp_path, monkeypatch):
    from visa_agent import commands
    monkeypatch.setattr(commands, "DOCS", tmp_path)
    assert commands.eval(type("A", (), {"live": False, "record": False})()) == 0
    assert not (tmp_path / "EVAL_RESULTS.md").exists()


def test_factory(monkeypatch):
    from pathlib import Path
    case = Path(__file__).resolve().parents[1] / "mock_data" / "cases" / "case01_happy"
    assert make_llm("case01_happy", case, provider="fake").name == "fake"
    assert make_llm("case01_happy", case, provider="replay").name == "replay"
    monkeypatch.setenv("LLM_PROVIDER", "bogus")
    with pytest.raises(ValueError):
        make_llm("x", case)


def test_provenance_recorded_and_ignored_on_replay(tmp_path):
    def create(**kw):
        return NS(choices=[NS(message=NS(content='{"a": 1}'))], x_groq=NS(id="req_123"), usage=NS(total_tokens=42))
    inner = GroqLLM(NS(chat=NS(completions=NS(create=create))), "model-X")
    ReplayLLM("p", record_with=inner, directory=tmp_path).extract("doc", "prompt", {})
    saved = json.loads((tmp_path / "p.json").read_text())
    e = next(iter(saved["entries"].values()))
    assert (e["request_id"], e["usage"], e["raw"], e["doc_id"]) == ("req_123", 42, '{"a": 1}', "doc") and e["ts"].endswith("+00:00")
    for v in saved["entries"].values():  # tamper with every provenance field: replay must not care
        v.update(request_id="x", ts="y", raw="z", usage=0)
    (tmp_path / "p.json").write_text(json.dumps(saved))
    assert ReplayLLM("p", directory=tmp_path).extract("doc", "prompt", {}) == {"a": 1}


def test_groq_propose_tool_call_and_agent_replay(tmp_path):
    out = '{"done": false, "tool": "crm.find", "args_json": "{\\"passport_no\\": \\"U1\\"}"}'
    g = GroqLLM(groq_client(out), "m")
    assert g.propose_tool_call({}, [], []) == {"tool": "crm.find", "args": {"passport_no": "U1"}}
    assert GroqLLM(groq_client('{"done": true, "tool": null, "args_json": null}'), "m").propose_tool_call({}, [], []) == {"done": True}
    ReplayLLM("agent_x", record_with=g, directory=tmp_path).propose_tool_call({"s": 1}, [], [])
    assert ReplayLLM("agent_x", directory=tmp_path).propose_tool_call({"s": 1}, [], []) == {"tool": "crm.find", "args": {"passport_no": "U1"}}
