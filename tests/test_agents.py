import threading
import time

import pytest

import beliefs
import evidence as ev
import records
from agents import Case, Diagnostician, Dispatcher, PartsAgent, Verifier, ledger
from conftest import make_llm
from mesh.runner import ControlRoom
from store import UnknownMachine
from traced import NullMemory, TracedMemory


def case_for(store, memory, scenario_id, use_memory=True, as_of=None, llm=None, ops=None):
    sc = store.scenario(scenario_id)
    m = store.machine(sc["machine_id"])
    job = next((j for j in store.open_jobs if j["job_id"] == sc.get("job_id")), {"job_id": "AL-1", "date": "2026-11-07", "machine_id": m["id"], "symptom": sc["description"]})
    emit = (lambda e: ops.append(e)) if ops is not None else (lambda e: None)
    mem = TracedMemory(memory, emit, store) if use_memory else NullMemory(emit)
    alarm = {k: sc[k] for k in ("machine_id", "code", "description", "readings", "severity")} | {"id": sc["id"], "ts": "2026-11-07T09:00:00"}
    return Case(alarm, m, store.site(m["site_id"]), job, store, llm or make_llm(), mem, use_memory, as_of,
                store.visits_before(as_of) if use_memory else [], store.alarms_before(as_of) if use_memory else [])


# ------------------------------------------------------------------------------------ dispatcher
def test_remote_fixes_are_limited_to_reset_setpoint_and_log_reading(store):
    types = {a["remote_type"] for a in store.alarms if a["remote_type"]}
    assert types <= {"reset", "setpoint", "read_log"}


def test_dispatcher_sends_a_technician_for_a_trip_that_remote_resets_never_clear(store, shared):
    d = Dispatcher().decide(case_for(store, shared, "LIVE-1"))
    assert d["decision"] == "SEND_TECHNICIAN" and d["ledger"]["cleared"] == 0


def test_dispatcher_never_repeats_a_remote_fix_that_just_failed_on_this_machine(store, shared):
    d = Dispatcher().decide(case_for(store, shared, "LIVE-1"))
    assert d["blocked"] and d["blocked"]["type"] == "reset" and "not repeated" in d["rationale"]
    # a month later the block expires; the ledger alone (0 cleared) still says send a technician
    later = Dispatcher().decide(case_for(store, shared, "LIVE-1", as_of="2026-12-30"))
    assert later["blocked"] is None and later["decision"] == "SEND_TECHNICIAN"


def test_dispatcher_tries_a_remote_reset_for_a_single_unit_comm_glitch(store, shared):
    d = Dispatcher().decide(case_for(store, shared, "LIVE-2"))
    assert d["decision"] == "REMOTE_FIX" and d["remote_type"] == "reset" and d["ledger"]["rate"] >= 0.5


def test_without_memory_the_dispatcher_falls_back_to_the_generic_first_step(store, shared):
    d = Dispatcher().decide(case_for(store, shared, "LIVE-1", use_memory=False))
    assert d["decision"] == "REMOTE_FIX" and d["ledger"] is None and "No alarm history" in d["rationale"]


# ------------------------------------------------------------------------------------ diagnostician
def test_diagnostician_shows_n_verified_rate_and_interval_from_raw_records(store, shared):
    diag = Diagnostician().diagnose(case_for(store, shared, "LIVE-1"))
    c = diag["causes"][0]
    s = c["stats"]
    assert "contactor" in c["fix"] and s["n"] >= 20 and s["verified"] >= 15 and not s["weak"] and c["confidence"] == "high"
    assert 0 <= s["ci"][0] < s["rate"] < s["ci"][1] <= 1


def test_a_fix_with_fewer_than_five_attempts_is_a_weak_signal(store, shared):
    diag = Diagnostician().diagnose(case_for(store, shared, "LIVE-4"), feedback="x", prior={"_recalled": [], "site_notes": []})
    c = diag["causes"][0]
    assert "inverter" in c["fix"] and c["stats"]["n"] == 4 and c["stats"]["weak"] and c["confidence"] == "weak"


def test_confidence_comes_from_verified_outcomes_not_from_the_llm(store, shared):
    llm = make_llm(**{"Diagnostician agent": {"causes": [{"cause": "Totally certain", "fix": "Replaced the flux capacitor", "evidence_jobs": [], "why": "sure"}]}})
    c = Diagnostician().diagnose(case_for(store, shared, "LIVE-1", llm=llm))["causes"][0]
    assert c["stats"]["n"] == 0 and c["confidence"] == "weak"


def test_without_memory_there_are_no_stats_and_no_recall(store, shared):
    ops = []
    diag = Diagnostician().diagnose(case_for(store, shared, "LIVE-1", use_memory=False, ops=ops))
    assert diag["causes"][0]["confidence"] == "none"


# ------------------------------------------------------------------------------------ verifier
def review(store, shared, sid, as_of=None):
    case = case_for(store, shared, sid, as_of=as_of)
    d, diag = Dispatcher().decide(case), Diagnostician().diagnose(case)
    parts = PartsAgent().plan(case, diag)
    return case, diag, parts, Verifier().review(case, d, diag, parts)


def test_verifier_vetoes_a_part_that_past_visits_replaced_on_a_hunch(store, shared):
    _, _, parts, v = review(store, shared, "LIVE-1")
    veto = next(x for x in v["vetoes"] if x["target"] == "parts")
    assert "DK-RLY-B2" in veto["item"] and "did not fix" in " ".join(veto["reasons"]).lower() or "fixed the fault in 0" in " ".join(veto["reasons"])
    assert any("DK-CTR-24V" in a["item"] for a in v["approvals"] if a["target"] == "parts")


def test_verifier_approves_the_contactor_for_an_older_unit(store, shared):
    _, _, _, v = review(store, shared, "LIVE-1")
    assert not any(x["target"] == "diagnostician" for x in v["vetoes"])
    assert any(a["target"] == "diagnostician" for a in v["approvals"])


def test_verifier_vetoes_the_contactor_for_a_newer_unit_because_recent_evidence_contradicts_it(store, shared):
    _, diag, _, v = review(store, shared, "LIVE-4")
    veto = next(x for x in v["vetoes"] if x["target"] == "diagnostician")
    assert "contactor" in diag["causes"][0]["fix"].lower() and "Recent evidence contradicts" in veto["reasons"][-1] and "installed from 2023" in veto["reasons"][-1]


def test_the_verifier_cannot_see_the_future(store, shared):
    # on 10 Sep 2026 no newer unit has failed yet, so there is nothing to contradict the lesson
    _, _, _, early = review(store, shared, "LIVE-4", as_of="2026-09-10")
    assert not any(x["target"] == "diagnostician" for x in early["vetoes"])
    _, _, _, late = review(store, shared, "LIVE-4", as_of="2026-10-25")
    assert any(x["target"] == "diagnostician" for x in late["vetoes"])


def test_verifier_rejects_citations_that_do_not_exist_or_do_not_support_the_claim(store, shared):
    case = case_for(store, shared, "LIVE-1")
    diag = Diagnostician().diagnose(case)
    diag["causes"][0]["evidence_jobs"] = ["J-9999", store.history[0]["job_id"]]
    v = Verifier().review(case, Dispatcher().decide(case), diag, {"carry": []})
    reasons = " ".join(next(x for x in v["vetoes"] if x["target"] == "diagnostician")["reasons"])
    assert "J-9999 is not in the visit records" in reasons


def test_verifier_has_nothing_to_check_without_records(store, shared):
    case = case_for(store, shared, "LIVE-1", use_memory=False)
    diag = Diagnostician().diagnose(case)
    v = Verifier().review(case, Dispatcher().decide(case), diag, {"carry": []})
    assert v["ok"] and "No records" in v["approvals"][-1]["note"]


# ------------------------------------------------------------------------------------ the control room
def wait(run, timeout=30):
    t = time.time()
    while run.status == "running" and time.time() - t < timeout:
        time.sleep(0.05)
    return run


@pytest.fixture()
def room(store, shared):
    return ControlRoom(store, shared, make_llm(), band_clients={})


def test_both_paths_run_side_by_side_and_the_with_path_is_checked(room):
    run = wait(room.start("LIVE-4"))
    assert run.status == "done" and set(run.plans) == {"with", "without"}
    kinds = [(e["path"], e["kind"]) for e in run.events]
    assert ("with", "veto") in kinds and ("with", "revise") in kinds and ("with", "consequence") in kinds
    assert ("without", "veto") not in kinds
    w = run.plans["with"]
    assert "inverter" in w["diagnosis"]["causes"][0]["fix"].lower() and w["diagnosis"]["causes"][0]["stats"]["weak"]
    assert w["briefing"]["confidence"] == "weak signal"


def test_with_memory_fixes_it_first_time_where_the_baseline_comes_back(room):
    run = wait(room.start("LIVE-4"))
    assert run.plans["with"]["consequence"]["outcome"] == "fixed first time"
    assert run.plans["without"]["consequence"]["outcome"] == "return visit needed"
    assert run.plans["with"]["consequence"]["visits"] == 1 and run.plans["without"]["consequence"]["visits"] == 2


def test_the_veto_on_the_trap_part_is_followed_by_a_revision(room):
    run = wait(room.start("LIVE-1"))
    vetoes = [e for e in run.events if e["path"] == "with" and e["kind"] == "veto"]
    assert any("DK-RLY-B2" in e["text"] for e in vetoes)
    carry = [p["part"] for p in run.plans["with"]["parts"]["carry"]]
    assert any("DK-CTR-24V" in c for c in carry) and not any("DK-RLY-B2" in c for c in carry)


def test_every_memory_operation_is_streamed_for_the_memory_panel(room):
    run = wait(room.start("LIVE-1"))
    ops = [e["data"] for e in run.events if e["kind"] == "memory" and e["path"] == "with"]
    assert {"recall", "reflect"} <= {o["op"] for o in ops} and all(o["bank"] for o in ops)
    off = [e["data"] for e in run.events if e["kind"] == "memory" and e["path"] == "without"]
    assert off and all(o.get("skipped") and not o["hits"] for o in off)


def test_a_remote_fix_that_works_ends_the_run_without_a_visit(room):
    run = wait(room.start("LIVE-2"))
    c = run.plans["with"]["consequence"]
    assert run.plans["with"]["dispatch"]["decision"] == "REMOTE_FIX" and c["outcome"] == "fixed remotely" and c["visits"] == 0


def test_unknown_machine_ids_are_refused_everywhere(store, shared, room):
    with pytest.raises(UnknownMachine):
        store.machine("M-9999")
    with pytest.raises(UnknownMachine):
        TracedMemory(shared, lambda e: None, store).recall("x", ["machine:M-9999"])
    with pytest.raises(UnknownMachine):
        TracedMemory(shared, lambda e: None, store).retain("x", ["machine:M-9999"], "2026-01-01", "d", {})
    with pytest.raises(UnknownMachine):
        records.validate({"tags": ["machine:M-9999"]}, store)
    store.scenarios.append({"id": "BAD", "machine_id": "M-9999", "site_id": "S-01", "code": "E3", "description": "x", "readings": {}, "severity": "major", "truth": {}})
    with pytest.raises(UnknownMachine):
        room.start("BAD")


def test_a_crash_in_one_path_does_not_take_down_the_other(room, monkeypatch):
    monkeypatch.setattr(room.parts, "plan", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")) if a[0].use_memory is False else PartsAgentReal(*a, **k))
    PartsAgentReal = type(room.parts).plan.__get__(room.parts)
    run = wait(room.start("LIVE-1"))
    assert any(e["kind"] == "error" and e["path"] == "without" for e in run.events) and "with" in run.plans


# ------------------------------------------------------------------------------------ records + the shared bank
def test_one_shared_bank_holds_every_kind_of_record(store):
    recs = records.build_all(store)
    kinds = {t for r in recs for t in r["tags"] if t.startswith("kind:")}
    assert kinds == {"kind:visit", "kind:followup", "kind:alarm", "kind:site"}
    assert {t.split(":")[1] for r in recs for t in r["tags"] if t.startswith("evidence:")} == {"suspected", "fixed_at_visit", "stable_30d", "stable_90d", "failed"}


def test_visit_records_state_cause_action_and_the_verified_outcome(store):
    r = next(x for x in records.build_all(store) if x["doc_id"] == "visit-J-0902")
    for needle in ("Suspected cause", "Tried:", "FIXED IT", "Verified outcome at the time: Fixed at visit"):
        assert needle in r["text"]
    assert "evidence:fixed_at_visit" in r["tags"]


def test_the_memory_as_of_a_date_contains_nothing_from_after_it(store):
    recs = records.build_all(store, as_of="2026-06-01")
    assert max(r["date"] for r in recs if r["date"]) < "2026-06-01"
    assert not any(r["doc_id"] == "visit-J-0949" for r in recs)       # a 21 Aug visit
    assert not any(r["doc_id"].startswith("followup-stable_90d-J-0902") for r in recs)  # 14 Jun follow-up


def test_the_dataset_has_the_messy_cases_real_logs_have(store):
    h = store.history
    assert len(store.sites) == 12 and 45 <= len(store.machines) <= 55 and 200 <= len(h) <= 280
    assert sum(1 for v in h if v["wrong_diagnosis"]) >= 10 and sum(1 for v in h if v["parts_missing"]) >= 10
    lv = ev.visit_levels(h)
    assert sum(1 for v in h if lv[v["job_id"]]["recurred"]) >= 3, "some fixes came back within 30 days"
    assert len(store.holdout_ids()) >= 6
