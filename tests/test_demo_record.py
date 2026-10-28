"""`demo --record` must be byte-for-byte reproducible (no timestamps or random ids in docs/demo_output)."""
import shutil
from pathlib import Path

from visa_agent import commands, report


def _snapshot(d: Path) -> dict[str, str]:
    return {p.name: p.read_text() for p in sorted(d.iterdir())}


def test_demo_record_is_deterministic(monkeypatch, tmp_path):
    monkeypatch.setattr(commands, "DOCS", tmp_path)
    class A: record = True
    assert commands.demo(A) == 0
    first = _snapshot(tmp_path / "demo_output")
    shutil.rmtree(tmp_path / "demo_output")
    assert commands.demo(A) == 0
    assert _snapshot(tmp_path / "demo_output") == first
    assert {"README.md", "TRANSCRIPT.md", "case01_happy.md"} <= set(first)
    assert "Run timestamp" not in "".join(first.values())


def test_save_writes_md_and_json(tmp_path):
    from visa_agent.schemas import RunResult
    d = report.save(RunResult(case="c1"), tmp_path)
    assert (d / "report.md").exists() and (d / "report.json").exists()
