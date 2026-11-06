import pytest

import beliefs
from agent import Agent
from beliefs import BeliefEngine, analyse, detect, fix_key, timeline
from conftest import make_llm
from memory import LocalMemory


def mk(store):
    return store.machine


def test_fix_key_groups_different_wordings_of_the_same_fix():
    a = fix_key("Replaced compressor contactor and checked phase voltages.")
    b = fix_key("Replaced compressor contactor (DK-CTR-24V) and checked phases")
    assert a == b == "replaced compressor contactor"
    assert fix_key("Reset outdoor unit breaker") != a


def test_contradicting_evidence_creates_one_scoped_belief(store):
    bl = analyse(store.history, mk(store))
    assert len(bl) == 1, "only the contactor lesson should be contradicted, nothing else in the history"
    b = bl[0]
    assert b["family"] == "Daikin VRV IV" and "contactor" in b["fix"]
    assert (b["earlier"]["worked"], b["earlier"]["n"]) == (9, 9)
    assert b["recent"]["failed"] == 4 and b["recent"]["since"] == "2026-09-09"
    assert b["cohort_from"] == 2023, "failures are all on units installed 2023+, successes all on older units"
    assert "inverter PCB" in b["alternative"] and b["alternative_count"] == 4
    assert b["text"].startswith("Belief updated:") and "older units keep the original lesson" in b["text"]


def test_belief_appears_only_once_the_evidence_is_strong_enough(store):
    # as_of is exclusive: visits before that date only
    assert analyse(store.history, mk(store), as_of="2026-09-09") == []   # nothing contradicts yet
    assert analyse(store.history, mk(store), as_of="2026-09-10") == []   # one failure is just bad luck
    assert analyse(store.history, mk(store), as_of="2026-09-24")[0]["recent"]["failed"] == 2  # two in a row after 9 straight successes
    assert analyse(store.history, mk(store), as_of="2026-10-07")[0]["recent"]["failed"] == 3


def test_a_recovery_retires_the_belief(store):
    extra = [{"job_id": f"J-9{i}", "incident_id": f"I-9{i}", "visit_no": 1, "date": f"2026-10-2{i}", "technician_id": "T-01",
              "machine_id": "M-92", "site_id": "S-09", "symptom": "trip", "outcome": "resolved", "parts_used": [],
              "actions": [{"action": "Replaced compressor contactor and checked phase voltages.", "result": "worked", "detail": ""}]}
             for i in (1, 2)]
    assert analyse(store.history + extra, mk(store)) == []  # the trailing run of failures is broken


def test_noise_does_not_trigger_a_belief():
    def att(res):
        return [{"result": r, "installed": 2020, "date": f"2026-01-{i + 1:02d}", "machine_id": "M", "job_id": "J", "incident_id": "I", "label": "x"}
                for i, r in enumerate(res)]
    assert detect(att(["worked"] * 5 + ["failed"])) is None                   # a single failure
    assert detect(att(["worked", "failed"] * 3 + ["failed", "failed"])) is None  # earlier record was never reliable
    assert detect(att(["worked"] * 3 + ["failed"] * 2)) is None               # not enough history
    assert detect(att(["worked"] * 9 + ["failed"] * 2)) is not None


def test_belief_applies_to_newer_units_but_not_older_ones(store):
    eng = BeliefEngine(store)
    text_new, upd_new = eng.for_machine(store.machine("M-91"))      # installed 2024
    text_old, upd_old = eng.for_machine(store.machine("M-07"))      # installed 2019
    assert len(upd_new) == 1 and "CORRECTED LESSON" in text_new and "inverter PCB" in text_new
    assert upd_old == [] and "original lesson still holds" in text_old
    assert eng.for_machine(store.machine("M-12")) == ("", [])        # a different family is untouched


def test_briefing_prompt_carries_the_correction_and_returns_it(store, tmp_path):
    llm = make_llm()
    mem = LocalMemory(tmp_path / "m.json")
    agent = Agent(mem, store)
    agent.llm, agent.belief_fn = llm, BeliefEngine(store).for_machine
    res = agent.briefing(store.job("J-1202"), True)  # M-91, installed 2024
    assert res["belief_updates"] and "Belief updated" in res["belief_updates"][0]["text"]
    sent = next(u for s, u in llm.calls if s.startswith("You are SiteMemory"))
    assert "CORRECTED LESSON" in sent
    res_old = agent.briefing(store.job("J-1201"), True)  # M-07, installed 2019
    assert res_old["belief_updates"] == []
    assert "CORRECTED LESSON" not in next(u for s, u in llm.calls[::-1] if s.startswith("You are SiteMemory"))


def test_correction_is_retained_to_hindsight_once_and_again_when_it_changes(store, tmp_path):
    mems = {r: LocalMemory(tmp_path / f"{r}.json") for r in ("field", "diagnostician")}
    state = {}
    eng = BeliefEngine(store, mems, lambda: state, lambda **kw: state.update(kw))
    assert eng.sync() == ["belief-daikin-vrv-iv-replaced-compressor-contactor"]
    assert all(m.count() == 1 for m in mems.values())
    assert "kind:belief" in mems["field"].items[0]["tags"] and mems["field"].items[0]["text"].startswith("BELIEF CORRECTION")
    assert eng.sync() == [] and all(m.count() == 1 for m in mems.values())  # idempotent
    store.history.append({**store.history[-1], "job_id": "J-9999", "incident_id": "I-999", "visit_no": 1, "date": "2026-10-30",
                          "machine_id": "M-93", "actions": [{"action": "Replaced compressor contactor and checked phase voltages.",
                                                              "result": "failed", "detail": ""}], "outcome": "revisit_needed"})
    assert eng.sync() and all(m.count() == 1 for m in mems.values())  # same document id, updated in place


def test_timeline_shows_each_fix_over_time_with_the_belief(store):
    rows = timeline(store.history, mk(store), "Daikin VRV IV")
    c = next(r for r in rows if "contactor" in r["fix"])
    assert (c["worked"], c["failed"]) == (9, 4) and c["belief"]
    assert [a["result"] for a in c["attempts"]] == ["worked"] * 9 + ["failed"] * 4
    assert [a["date"] for a in c["attempts"]] == sorted(a["date"] for a in c["attempts"])
