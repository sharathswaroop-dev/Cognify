import re
from pathlib import Path

import pytest

from agent import Agent
from conftest import FakeLLM
from evaluation import Evaluator, Progress, ground_truth, rate, render_markdown, tokens, wilson
from memory import LocalMemory


def brief_from_memory(user: str) -> dict:
    """A stand-in LLM that only knows what is written in the memories it is given."""
    worked = re.findall(r"Tried: (.+?) -> FIXED IT", user)
    failed = re.findall(r"Tried: (.+?) -> DID NOT FIX IT", user)
    parts = re.findall(r"Parts used: (.+?)\.\n", user)
    return {"headline": "brief", "likely_cause": "unknown", "confidence": "high" if worked else "low",
            "do_first": list(dict.fromkeys(worked))[:3] or ["Check the error code"], "avoid": list(dict.fromkeys(failed))[:3],
            "bring": [p for ps in parts[:2] for p in ps.split(", ")][:4] or ["Multimeter"], "site_notes": []}


def judge(user: str) -> dict:
    truth, briefing = user.split("BRIEFING")
    fix = re.search(r"Fix that WORKED: (.*)", truth).group(1)
    failed = re.search(r"Fixes that FAILED: (.*)", truth).group(1)
    parts = re.search(r"Parts needed: (.*)", truth).group(1)
    do_first = re.search(r"Do first: (.*)", briefing).group(1)
    avoid = re.search(r"Avoid: (.*)", briefing).group(1)
    bring = re.search(r"Bring: (.*)", briefing).group(1)
    f = [x for x in re.findall(r"'([^']+)'", failed)]
    p = [x for x in re.findall(r"'([^']+)'", parts)]
    return {"recommends_working_fix": fix.lower()[:30] in do_first.lower(),
            "warned_against": [x.lower()[:25] in avoid.lower() for x in f],
            "parts_listed": [x.lower()[:25] in bring.lower() for x in p]}


@pytest.fixture()
def evaluator(store, tmp_path):
    llm = FakeLLM({"briefs HVAC field technicians": brief_from_memory, "strict grader": judge})
    mem = LocalMemory(tmp_path / "eval_mem.json")
    agent = Agent(mem, store)
    agent.llm = llm
    seen = []
    orig = agent.briefing

    def spy(job, use_memory, extra="", as_of=None, visits=None):
        seen.append((job["date"], use_memory, [v["date"] for v in (visits or [])], mem.count()))
        return orig(job, use_memory, extra, as_of, visits)

    agent.briefing = spy
    ev = Evaluator(store, agent, llm, mem, tmp_path / "res.json", site_records=[agent.site_record(s) for s in store.sites],
                   visit_record=agent.visit_record, progress=Progress())
    ev.seen = seen
    return ev


def test_helpers():
    assert wilson(0, 0) == (0.0, 0.0)
    lo, hi = wilson(8, 10)
    assert 0.4 < lo < 0.8 < hi < 1
    assert rate([True, False, None]) == {"k": 1, "n": 2, "rate": 0.5, "ci": list(wilson(1, 2))}
    assert tokens("Replaced the compressor contactor") == {"compressor", "contactor"}


def test_ground_truth_reads_failed_and_working_actions(store):
    inc = [v for v in store.history if v["incident_id"] == "I-901"]
    t = ground_truth(inc)
    assert t["failed"] == ["Reset outdoor unit breaker"] and "contactor" in t["fix"] and t["parts"] and not t["first_time"]


def test_no_future_visit_ever_reaches_the_memory_used_for_an_earlier_incident(evaluator):
    evaluator.run(limit=25)
    for date, use_memory, visit_dates, _ in evaluator.seen:
        assert all(d < date for d in visit_dates), f"future leak at {date}: {visit_dates}"
    with_arm = [s for s in evaluator.seen if s[1]]
    assert with_arm[0][2] == [] and with_arm[-1][2], "memory starts empty and grows"


def test_memory_arm_beats_no_memory_and_the_curve_rises(evaluator):
    out = evaluator.run()
    s = out["summary"]
    assert s["without"]["fix"]["k"] == 0 or s["with"]["fix"]["rate"] > s["without"]["fix"]["rate"]
    assert s["with"]["ftf"]["rate"] > s["without"]["ftf"]["rate"]
    first, last = out["thirds"][0], out["thirds"][-1]
    assert last["with"]["rate"] >= first["with"]["rate"], "accuracy should not fall as memory grows"
    assert out["curve"][0]["memory_visits"] == 0 and out["curve"][-1]["memory_visits"] > 20


def test_judge_failure_falls_back_to_keyword_scoring(evaluator):
    evaluator.llm = FakeLLM({})  # judge returns None
    truth = {"failed": ["Reset outdoor unit breaker"], "fix": "Replaced compressor contactor", "parts": ["Compressor contactor coil"],
             "first_time": False}
    b = {"headline": "", "likely_cause": "", "do_first": ["Replaced compressor contactor"], "avoid": ["Reset outdoor unit breaker"],
         "bring": ["Compressor contactor coil"]}
    sc = evaluator.score(b, truth)
    assert sc["judge_error"] and sc["fix_hit"] and sc["warn_hit"] and sc["part_hit"] and sc["ftf"]


def test_markdown_report_contains_the_honest_caveats(evaluator):
    md = render_markdown(evaluator.run(limit=12))
    for needle in ("Without memory", "With memory", "Caveats", "Small sample", "Synthetic data", "same model family", "95% CI"):
        assert needle in md
