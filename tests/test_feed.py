import time

import pytest

from mesh.runner import AlarmFeed


def wait(run, timeout=20):
    t = time.time()
    while run.status == "running" and time.time() - t < timeout:
        time.sleep(0.05)
    return run


def test_alarm_history_is_realistic_and_internally_consistent(store):
    a = store.alarms
    assert len(a) >= 60 and a == sorted(a, key=lambda x: x["ts"])
    assert len({x["id"] for x in a}) == len(a)
    for x in a:
        assert x["machine_id"] in {m["id"] for m in store.machines}
        assert x["remote_result"] in ("cleared", "failed", "none")
        if x["remote_result"] == "cleared":
            assert x["remote_action"] and not x["dispatched"]
        if x["remote_action"] is None:
            assert x["remote_result"] == "none" and x["dispatched"]
    # every first visit in the history has an alarm that led to it
    linked = {x["incident_id"] for x in a if x["incident_id"]}
    assert {v["incident_id"] for v in store.history if v["visit_no"] == 1} <= linked


def test_each_live_scenario_names_a_real_machine_and_job(store):
    for sc in store.live_alarms:
        m = store.machine(sc["machine_id"])
        assert sc["site_id"] == m["site_id"] and sc["readings"]
        if sc["job_id"]:
            assert store.job(sc["job_id"])["machine_id"] == sc["machine_id"]


def test_firing_a_scenario_starts_a_run_and_records_it(build_mesh, store):
    mesh, _, _ = build_mesh()
    feed = AlarmFeed(mesh, store.live_alarms)
    run = wait(feed.fire("LIVE-1"))
    assert run.status == "done" and feed.state()["fired"][-1]["run_id"] == run.id
    assert feed.state()["fired"][-1]["alarm"]["id"].startswith("LIVE-1-")
    with pytest.raises(KeyError):
        feed.fire("NOPE")


def test_live_feed_fires_scenarios_one_after_another_and_can_be_stopped(build_mesh, store):
    mesh, _, _ = build_mesh()
    feed = AlarmFeed(mesh, store.live_alarms[:3])
    feed.start(interval=0.2)
    t = time.time()
    while len(feed.fired) < 3 and time.time() - t < 10:
        time.sleep(0.05)
    assert [f["alarm"]["machine_id"] for f in feed.fired] == [s["machine_id"] for s in store.live_alarms[:3]]
    feed.stop()
    assert feed.state()["running"] is False


def test_new_vrv_units_make_the_drift_scenario_possible(store):
    newer = [m for m in store.machines if m["model_family"] == "Daikin VRV IV" and m["installed"] >= 2023]
    assert len(newer) >= 4
    failed = [v for v in store.history if v["machine_id"] in {m["id"] for m in newer} and v["visit_no"] == 1]
    assert failed and all(v["actions"][0]["result"] == "failed" for v in failed)
