import time

from conftest import make_llm
from mesh.roles import ledger


def wait(run, timeout=20):
    t = time.time()
    while run.status == "running" and time.time() - t < timeout:
        time.sleep(0.05)
    return run


def alarm(store, live_id):
    sc = next(a for a in store.live_alarms if a["id"] == live_id)
    return {**sc, "id": sc["id"] + "-t", "remote_action": None, "remote_result": "none", "dispatched": False}


def test_each_agent_has_its_own_bank_with_different_content(build_mesh):
    mesh, mems, _ = build_mesh()
    kinds = {r: {t for i in m.items for t in i["tags"] if t.startswith("kind:")} for r, m in mems.items()}
    assert "kind:alarm" in kinds["dispatcher"] and "kind:visit" not in kinds["dispatcher"]
    assert "kind:visit" in kinds["diagnostician"] and "kind:alarm" not in kinds["diagnostician"]
    assert kinds["parts"] == {"kind:parts"}
    assert "kind:site" in kinds["field"]
    assert len({id(m) for m in mems.values()}) == 4


def test_ledger_separates_single_unit_from_multi_unit_comm_faults(store):
    single = ledger(store.alarms, "U4", units=1)
    multi = ledger(store.alarms, "U4", units=4)
    assert single["rate"] >= 0.5 > multi["rate"]
    assert ledger(store.alarms, "E3")["cleared"] == 0  # remote reset never cleared a VRV trip


def test_dispatcher_chooses_remote_fix_when_memory_supports_it(build_mesh, store):
    llm = make_llm(**{"Dispatcher agent": {"decision": "REMOTE_FIX", "remote_action": "Remote power-cycle of the indoor group via BMS",
                                           "confidence": "medium", "rationale": "Single unit glitch.", "evidence": ["8 cleared"]}})
    mesh, _, _ = build_mesh(llm)
    run = wait(mesh.start(alarm(store, "LIVE-2")))
    assert run.result["decision"] == "REMOTE_FIX"
    kinds = [e["kind"] for e in run.events]
    assert "decision" in kinds and run.events[-1]["from"] == "field"
    assert not any(e["from"] == "diagnostician" for e in run.events)  # nobody else was woken up


def test_guard_blocks_a_remote_fix_that_memory_says_fails(build_mesh, store):
    llm = make_llm(**{"Dispatcher agent": {"decision": "REMOTE_FIX", "remote_action": "Remote fault reset via controller",
                                           "confidence": "high", "rationale": "Try a reset.", "evidence": []}})
    mesh, _, _ = build_mesh(llm)
    d = mesh.roles["dispatcher"].decide(alarm(store, "LIVE-1"), store.machine("M-07"), store.site("S-01"))
    assert d["decision"] == "SEND_TECHNICIAN" and "Guard" in d["rationale"]


def test_full_flow_runs_all_four_agents_in_order_and_cites_only_real_jobs(build_mesh, store):
    mesh, _, _ = build_mesh()
    run = wait(mesh.start(alarm(store, "LIVE-1")))
    assert run.status == "done" and run.result["decision"] == "SEND_TECHNICIAN"
    speakers = [e["from"] for e in run.events if e["kind"] in ("decision", "result")]
    assert speakers == ["dispatcher", "diagnostician", "parts", "field"]
    handoffs = [(e["from"], e["to"]) for e in run.events if e["kind"] == "handoff"]
    assert handoffs == [("dispatcher", "diagnostician"), ("diagnostician", "parts"), ("parts", "field")]
    ev = run.result["diagnosis"]["evidence"]
    assert ev and all(e["job_id"] != "J-9999" for e in ev)  # invented citation was dropped
    diag_event = next(e for e in run.events if e["from"] == "diagnostician" and e["kind"] == "decision")
    assert diag_event["memories"], "UI must show which memories the agent used"
    assert all(e["transport"] == "local" for e in run.events if e["kind"] == "handoff")


def test_parts_agent_flags_stock_problems(build_mesh, store):
    mesh, _, _ = build_mesh()
    run = wait(mesh.start(alarm(store, "LIVE-1")))
    carry = {c["part"]: c for c in run.result["parts"]["carry"]}
    pcb = next(c for k, c in carry.items() if "PCB" in k)
    assert "NOT on the van" in pcb["stock"]
    assert any("warehouse" in f for f in run.result["parts"]["flags"])


def test_visit_fans_out_to_the_other_agents(build_mesh, store):
    mesh, mems, _ = build_mesh()
    run = wait(mesh.start(alarm(store, "LIVE-1")))
    job_id = run.result["job"]["job_id"]
    before = {r: mems[r].count() for r in ("diagnostician", "parts", "dispatcher")}
    visit = {"job_id": f"{job_id}-V1", "incident_id": "I-J1201", "visit_no": 1, "date": "2026-11-07", "technician_id": "T-06",
             "machine_id": "M-07", "site_id": "S-01", "symptom": "trips", "actions": [{"action": "Replaced contactor", "result": "worked", "detail": ""}],
             "root_cause": "burnt contactor", "fix": "Replaced contactor", "parts_used": ["Compressor contactor 24V coil (DK-CTR-24V)"],
             "outcome": "resolved", "recommendation": "", "notes": ""}
    mesh.job_alarm[visit["job_id"]] = run.alarm
    done = mesh.record_visit(visit)
    assert set(done) == {"diagnostician", "parts", "dispatcher"}
    assert all(mems[r].count() == before[r] + 1 for r in before)


def test_run_survives_an_agent_crash(build_mesh, store):
    llm = make_llm()
    mesh, _, _ = build_mesh(llm)
    mesh.roles["parts"].plan = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    run = wait(mesh.start(alarm(store, "LIVE-1")))
    assert run.status == "error" and run.events[-1]["kind"] == "error"
