import pytest

import evaluation as E
import evidence as ev
import records
from conftest import make_llm
from memory import LocalMemory


def make(store, tmp_path, **kw):
    return E.Evaluator(store, make_llm(), tmp_path / "res.json", progress=E.Progress(), **kw)


def test_train_and_test_use_different_machines_and_test_is_held_out_only(store, tmp_path):
    e = make(store, tmp_path)
    train, test = e.pick(None)
    hold = store.holdout_ids()
    assert train and test
    assert all(v["machine_id"] not in hold for v in train) and all(v["machine_id"] in hold for v in test)
    assert not {v["machine_id"] for v in train} & {v["machine_id"] for v in test}


def test_the_replay_never_holds_a_record_dated_on_or_after_the_incident(store, tmp_path):
    rp = E.Replay(store, sorted(records.build_all(store), key=lambda r: (r["date"] or "0000", r["doc_id"])), LocalMemory(tmp_path / "m.json"))
    for day in ("2026-02-01", "2026-06-01", "2026-10-15"):
        rp.advance(day)
        assert all((r["date"] or "0000") < day for r in rp.retained)
        assert not any(r["date"] and r["date"] >= day for r in rp.mem.items)


def test_the_guard_fails_loudly_if_a_future_record_gets_in(store, tmp_path):
    rp = E.Replay(store, sorted(records.build_all(store), key=lambda r: (r["date"] or "0000", r["doc_id"])), LocalMemory(tmp_path / "m.json"))
    rp.advance("2026-09-01")
    with pytest.raises(AssertionError, match="future"):
        rp.advance("2026-03-01")      # going back in time with the later records already retained


def test_truth_treats_a_fix_that_came_back_as_not_the_fix(store, tmp_path):
    e = make(store, tmp_path)
    topup = next(v for v in store.history if v["fault_class"] == "ductable_leak" and v["visit_no"] == 1 and "Topped up" in v["actions"][0]["action"]
                 and e.levels[v["job_id"]]["recurred"])
    t = E.truth_for(e.by_inc[topup["incident_id"]], e.levels, e.by_job)
    assert "Topped up" in " ".join(t["failed"]) and "brazed" in t["fix_key"].lower() and not t["first_time"]


def test_scoring_is_deterministic_and_needs_both_the_fix_and_the_parts():
    truth = {"fix_key": "Replaced compressor contactor and checked phase voltages.", "parts": ["Compressor contactor 24V coil (DK-CTR-24V)"],
             "failed": ["Reset outdoor unit breaker"]}
    good = {"diagnosis": {"causes": [{"fix": "Replaced compressor contactor"}]}, "parts": {"carry": [{"part": "Compressor contactor 24V coil (DK-CTR-24V)"}]}}
    no_part = {"diagnosis": good["diagnosis"], "parts": {"carry": []}}
    wrong = {"diagnosis": {"causes": [{"fix": "Reset outdoor unit breaker"}]}, "parts": good["parts"]}
    assert E.score(good, truth)["ftf"] and E.score(good, truth)["warn"]
    s = E.score(no_part, truth)
    assert s["fix"] and s["parts"] is False and not s["ftf"] and s["missing"]
    w = E.score(wrong, truth)
    assert not w["fix"] and w["warn"] is False             # it recommended the thing that failed
    generic = {"diagnosis": {"causes": [{"fix": "Run the standard checks and log everything you try"}]}, "parts": good["parts"]}
    assert not E.score(generic, truth)["fix"]


def test_a_small_replay_runs_end_to_end_and_reports_honestly(store, tmp_path):
    e = make(store, tmp_path, train_n=3)
    res = e.run(limit_test=4)
    assert res["test"]["n_incidents"] == 4 and set(res["test"]["arms"]) == {"none", "basic", "basic_verified"}
    assert res["skipped"] and "hindsight" in res["skipped"]                # not run, and it says so
    assert res["chosen_min_wins"] in (1, 2, 3) and "held-out machines were not looked at" in res["tuning"]
    for arm in res["test"]["arms"].values():
        assert arm["ftf"]["n"] == 4 and arm["ftf"]["ci"][0] <= arm["ftf"]["rate"] <= arm["ftf"]["ci"][1]
    md = E.render_markdown(res)
    for needle in ("Everything below is simulated", "Not run:", "Caveats", "held-out", "deterministic"):
        assert needle in md


def test_an_llm_outage_is_excluded_not_scored_as_a_wrong_answer(store, tmp_path):
    from conftest import FakeLLM
    e = E.Evaluator(store, FakeLLM({}), tmp_path / "r.json", progress=E.Progress(), train_n=2)   # every call returns None
    res = e.run(limit_test=3)
    assert res["llm_failures"] == res["llm_calls"] > 0
    assert all(a["ftf"]["n"] == 0 for a in res["test"]["arms"].values())      # nothing scored
    assert all("unavailable" in f["why"] for f in res["failures"])
