"""demo / eval / test-report commands (kept apart from cli.py's `run`)."""
import json
import os
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

from .cases import CASES, run_case
from .llm.replay import REPLAY_DIR, make_llm
from .report import to_markdown

DOCS = Path(__file__).resolve().parents[1] / "docs"
DEMO = ["case01_happy", "case01_happy+dry", "case02_missing_bank", "case03_name_conflict", "case07_hallucination",
        "case10_timeout_applied", "case11a_version_conflict", "case14_injection"]  # demo order (docs/DEMO.md)
FAKE_ONLY = {"case07_hallucination", "case13_llm_malformed"}  # the scenario *is* a scripted LLM misbehaviour


def _summary(res) -> str:
    p = res.plan
    return (f"  outcome={res.write_outcome} status={p.status if p else None} patch={len(p.field_patch) if p else 0} fields "
            f"flags={res.flags}\n  issues: " + ("; ".join(f"{i.kind.value}:{i.field}" for i in res.issues) or "none"))


def _model(llm) -> str:
    return getattr(llm, "model", "")


def demo(a) -> int:
    prov = os.getenv("LLM_PROVIDER") or "replay"
    with tempfile.TemporaryDirectory() as tmp:
        for entry in DEMO:
            name, dry = entry.split("+")[0], entry.endswith("+dry")
            exp = json.loads((CASES / name / "expected.json").read_text())
            use = prov if prov != "replay" or (name not in FAKE_ONLY and (REPLAY_DIR / f"{exp['packet']}.json").exists()) else "fake"
            exp, res, llm = run_case(name, lambda c, d, r: make_llm(c, d, r, provider=use), Path(tmp), dry_run=dry)
            print(f"\n=== {exp['scenario']:>2} {exp['title']}{' [dry-run]' if dry else ''}  (provider={use}{':' + _model(llm) if use == 'replay' else ''}) ===\n{_summary(res)}")
            if dry and res.plan:
                print("  CRM diff:", json.dumps(res.plan.field_patch))
    return 0


class _Tap:
    """Wraps a client and keeps the raw proposals, so hallucinations are counted before verify drops them."""
    def __init__(self, inner, pause: float = 0):
        self.pause, self.inner, self.name, self.model, self.raw = pause, inner, inner.name, getattr(inner, "model", inner.name), {}

    def extract(self, doc_id, prompt, schema):
        time.sleep(self.pause)  # free-tier pacing for --live
        out = self.raw[doc_id] = self.inner.extract(doc_id, prompt, schema)
        return out


def _provenance(names: list[str]) -> str:
    """Verbatim-quote rate and call count computed from the recording files (raw responses vs the PDF text)."""
    from . import ingest, verify
    ok = n = calls = 0
    for name in names:
        saved = json.loads((REPLAY_DIR / f"{name}.json").read_text())
        pages = {d["doc_id"]: " ".join(verify.normalize(p["text"]) for p in d["pages"]) for d in ingest.ingest(CASES / name)}
        for e in saved["entries"].values():
            calls += bool(e.get("request_id"))
            for f in ((e["response"].get("fields")) or {}).values():
                if f.get("evidence_quote"):
                    n += 1
                    ok += verify.normalize(f["evidence_quote"]) in pages.get(e["doc_id"], "")
    return (f"Run timestamp (UTC): {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}  \nRecorded calls with a provider request id: {calls}  \n"
            f"Verbatim-quote rate, computed from mock_data/replay/*.json vs PDF text: {ok}/{n} ({ok / max(n, 1):.0%})\n")


def eval(a) -> int:  # noqa: A001 (CLI verb)
    prov = (os.getenv("LLM_PROVIDER") or "gemini") if a.live else "fake"
    stats: dict[str, list[int]] = {}  # field -> [correct, total]
    halluc, model, prop = [], prov, [0, 0]  # prop: [proposals with a value, of which survived verify]
    names = sorted(p.name for p in CASES.iterdir() if (p / "truth.json").exists() and (p / "fake_llm.json").exists()
                   and json.loads((p / "expected.json").read_text())["packet"] == p.name)  # one run per distinct packet
    with tempfile.TemporaryDirectory() as tmp:
        for name in names:
            tap = {}
            def mk(c, d, r, tap=tap):
                tap["t"] = _Tap(make_llm(c, d, r, provider=prov, record=a.record), 8 if a.live else 0)
                return tap["t"]
            _, res, _ = run_case(name, mk, Path(tmp), dry_run=True)
            truth = json.loads((CASES / name / "truth.json").read_text())["documents"]
            model = tap["t"].model
            for dt, raw in tap["t"].raw.items():
                for f, v in (raw.get("fields") or {}).items():
                    if v.get("value") is not None and v["value"] != truth.get(dt, {}).get(f):
                        halluc.append(f"{name}/{dt}.{f}: proposed {v['value']!r}, truth {truth.get(dt, {}).get(f)!r}")
            for dt, ext in res.extractions.items():
                for f, fld in ext.fields.items():
                    s = stats.setdefault(f, [0, 0])
                    s[1] += 1
                    prop[0] += fld.value is not None or fld.status.value == "UNVERIFIABLE"
                    prop[1] += fld.value is not None and fld.status.value == "VERIFIED"
                    s[0] += fld.status.value == "VERIFIED" and fld.value == truth.get(dt, {}).get(f)
    tot = [sum(s[i] for s in stats.values()) for i in (0, 1)]
    lines = [f"# Eval results\n\nDate: {date.today()}  \nProvider: {prov}  \nModel: {model}  \nCases (distinct packets): {', '.join(names)}\n",
             "| field | correct VERIFIED / total | accuracy |\n|---|---|---|"]
    lines += [f"| {f} | {c}/{n} | {c / n:.0%} |" for f, (c, n) in sorted(stats.items())]
    lines += [f"| **all** | {tot[0]}/{tot[1]} | {tot[0] / max(tot[1], 1):.0%} |",
              f"\nHallucinations (non-null proposal differing from truth, before verify): **{len(halluc)}**  \nEvidence pass rate (proposals surviving verify / proposals): {prop[1]}/{prop[0]}\n"] + [f"- {h}" for h in halluc]
    if a.live:  # only a real-provider run may write the accuracy file
        if a.record:
            lines.insert(1, _provenance(names))
        (DOCS / "EVAL_RESULTS.md").write_text("\n".join(lines) + "\n")
    else:
        lines.insert(0, "**Provider: fake. This checks the control logic only; it is NOT extraction accuracy. Nothing written.**\n")
    print("\n".join(lines))
    return 0


def _check(exp, res) -> list[str]:
    """Return a list of mismatches (empty = pass) for the headline golden fields."""
    bad, got = [], {(i.kind.value, i.field) for i in res.issues}
    bad += [f"missing issue {e['kind']}:{e['field']}" for e in exp["issues"] if (e["kind"], e["field"]) not in got]
    if sorted(res.flags) != sorted(exp["flags"]):
        bad.append(f"flags {res.flags}")
    if res.write_outcome != exp["write_outcome"]:
        bad.append(f"outcome {res.write_outcome}")
    c = exp["crm"]
    if c["action"] != "NO_WRITE" and (res.plan.record_id, res.plan.status, res.plan.field_patch) != (c["target_record"], c["status"], c["field_patch"]):
        bad.append("plan differs")
    if c["action"] == "NO_WRITE" and res.plan.record_id is not None:
        bad.append("unexpected write plan")
    return bad


def test_report(a) -> int:
    rows, fails = [], 0
    with tempfile.TemporaryDirectory() as tmp:
        for name in sorted(p.name for p in CASES.iterdir() if (p / "expected.json").exists()):
            exp, res, _ = run_case(name, lambda c, d, r: make_llm(c, d, r, provider="fake"), Path(tmp))
            bad, c = _check(exp, res), exp["crm"]
            fails += bool(bad)
            e_iss = ", ".join(f"{i['kind']}:{i['field']}" for i in exp["issues"]) or "none"
            g_iss = ", ".join(sorted({f"{i.kind.value}:{i.field}" for i in res.issues})) or "none"
            rows.append(f"| {exp['scenario']} | {name} | {exp['title']} | {exp['write_outcome']} / {c['status'] or c['action']} / {e_iss} "
                        f"| {res.write_outcome} / {res.plan.status or res.plan.reason} / {g_iss} | {'PASS' if not bad else 'FAIL: ' + '; '.join(bad)} |")
    out = (f"# Test results (generated {date.today()}; FakeLLM, frozen clock per case)\n\n"
           "These offline tests prove the control logic (verification, policy, gateway guards, retries) using scripted LLM output. "
           "They do not measure extraction accuracy; that lives in EVAL_RESULTS.md (real model, separate evidence).\n\n"
           f"{len(rows) - fails}/{len(rows)} scenarios match their golden. Issues listed are the expected subset vs everything raised.\n\n"
           "| # | case | scenario | expected (outcome / status / issues) | actual (outcome / status / issues) | result |\n|---|---|---|---|---|---|\n"
           + "\n".join(rows) + "\n")
    (DOCS / "TEST_RESULTS.md").write_text(out)
    print(out)
    return 1 if fails else 0
