"""API tests against the real FastAPI app, with every external service switched off (no Hindsight, no Groq, no Band)."""
import importlib
import json
import os
import sys
import time

import pytest

for k in ("HINDSIGHT_API_KEY", "HINDSIGHT_BASE_URL", "GROQ_API_KEY"):
    os.environ[k] = ""          # present but empty: .env cannot refill them

from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HINDSIGHT_BANK_ID", "test-bank")
    sys.modules.pop("app", None)
    app_mod = importlib.import_module("app")
    app_mod.store.logged_path = tmp_path / "logged.json"
    app_mod.store.logged = []
    app_mod.store.notes_path = tmp_path / "notes.json"
    app_mod.store.notes = []
    app_mod.state_path = tmp_path / "state.json"
    import workspaces
    workspaces.DATA = tmp_path                                     # companies, secrets and libraries live in the test's own folder
    workspaces.ensure_demo("CoolCare Facility Services", "test-bank")
    app_mod._ws_mem.clear()
    tc = TestClient(app_mod.app)
    tok = tc.post("/api/workspace/join", json={"code": workspaces.DEMO_CODE, "email": "priya@coolcare.example"}).json()["token"]
    tc.headers.update({"Authorization": "Bearer " + tok})           # signed in to the demo company, as the browser is
    return tc, app_mod


def test_status_says_which_memory_is_in_use(client):
    c, _ = client
    s = c.get("/api/status").json()
    assert s["machines"] == 51 and s["sites"] == 12 and s["backend"] in ("local", "none") or "local" in s["backend"]
    assert s["agents"] == ["dispatcher", "diagnostician", "parts", "verifier"] and s["llm"] is False


def test_the_hidden_truth_is_never_sent_to_the_browser(client):
    c, _ = client
    assert "truth" not in json.dumps(c.get("/api/scenarios").json())
    rid = c.post("/api/runs", json={"scenario_id": "LIVE-1"}).json()["run_id"]
    for _ in range(100):
        run = c.get(f"/api/runs/{rid}").json()
        if run["status"] != "running":
            break
        time.sleep(0.1)
    assert run["status"] == "done" and "truth" not in json.dumps(run)
    assert set(run["plans"]) == {"with", "without"} and run["plans"]["with"]["consequence"]["label"] == "Simulated"


def test_the_event_stream_ends_with_the_plans(client):
    c, _ = client
    rid = c.post("/api/runs", json={"scenario_id": "LIVE-2"}).json()["run_id"]
    body = c.get(f"/api/runs/{rid}/stream").text
    assert "event: end" in body and body.count("data: ") > 5
    assert '"kind": "memory"' in body and '"path": "with"' in body and '"path": "without"' in body


def test_unknown_scenario_and_run_are_clean_404s(client):
    c, _ = client
    assert c.post("/api/runs", json={"scenario_id": "NOPE"}).status_code == 404
    assert c.get("/api/runs/nope").status_code == 404


def test_logging_a_visit_retains_it_and_refuses_an_invented_machine(client):
    c, app_mod = client
    ok = {"actions": [{"action": "Replaced the compressor contactor", "result": "worked", "detail": ""}], "outcome": "resolved",
          "root_cause": "burnt coil", "parts_used": ["DK-CTR-24V"], "notes": ""}
    r = c.post("/api/jobs/J-1201/log", json=ok)
    assert r.status_code == 200 and r.json()["saved"] and r.json()["ops"][0]["op"] == "retain"
    assert "Verified outcome at the time: Fixed at visit" in r.json()["memory_text"] and len(app_mod.store.logged) == 1
    bad = c.post("/api/jobs/J-1201/log", json={**ok, "machine_id": "M-9999"})
    assert bad.status_code == 422 and "unknown machine" in bad.json()["detail"].lower() and len(app_mod.store.logged) == 1


def test_watchlist_and_fix_outcomes_explain_themselves(client):
    c, _ = client
    w = c.get("/api/watchlist").json()
    assert w and all(x["reasons"] for x in w) and w == sorted(w, key=lambda x: -x["score"])
    fx = c.get("/api/fix-outcomes", params={"family": "Daikin VRV IV"}).json()["fixes"]
    top = next(f for f in fx if "contactor" in f["fix"].lower())
    assert top["belief"] and top["n"] >= 20 and {a["result"] for a in top["attempts"]} >= {"verified", "failed"}


def test_the_voice_endpoint_refuses_empty_audio_politely(client):
    c, _ = client
    r = c.post("/api/voice/report", data={"job_id": "J-1201"}, files={"audio": ("x.webm", b"", "audio/webm")})
    assert r.status_code == 422 and r.json()["detail"]["code"] in ("no_stt", "empty")


def test_reset_demo_clears_logged_visits_and_rebuilds_the_memory(client):
    c, app_mod = client
    body = {"actions": [{"action": "Replaced compressor contactor", "result": "failed"}], "outcome": "revisit_needed"}
    assert c.post("/api/jobs/J-1204/log", json=body).status_code == 200
    assert app_mod.store.logged
    r = c.post("/api/reset-demo")
    assert r.status_code == 200 and r.json()["reset"] and not app_mod.store.logged
    assert not any("J-1204-V1" == i["doc_id"] for i in app_mod.memory.items)


def test_a_new_hire_can_ask_the_memory_and_gets_sources(client):
    c, app_mod = client
    r = c.post("/api/ask", json={"question": "What usually goes wrong with the Daikin VRV IV compressor?"})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] and body["answer"] and body["sources"]
    assert c.post("/api/ask", json={"question": "hi"}).status_code == 422


def test_knowledge_shared_by_a_senior_person_is_retained_and_found_later(client):
    c, app_mod = client
    note = {"author": "Raghu Murthy", "role": "senior technician", "years": 15, "machine_id": "M-91",
            "text": "On this rooftop unit the breaker trips are caused by the inverter board, never the contactor. Check the DC bus first."}
    r = c.post("/api/knowledge", json=note)
    assert r.status_code == 200 and "Raghu Murthy" in r.json()["memory_text"] and "kind:note" in r.json()["tags"]
    found = c.post("/api/ask", json={"question": "Raghu Murthy rooftop unit breaker trips inverter board DC bus"}).json()
    assert any("Raghu Murthy" in s["text"] for s in found["sources"])
    bad = c.post("/api/knowledge", json={**note, "machine_id": "M-999"})
    assert bad.status_code == 422


def test_company_overview_shows_who_holds_the_knowledge_and_counts_shared_notes(client):
    c, app_mod = client
    before = c.get("/api/company").json()
    tot = before["totals"]
    assert tot["visits"] > 200 and tot["verified"] > 0 and before["people"] and before["families"]
    assert sum(p["visits"] for p in before["people"]) == tot["visits"]
    assert all(f["status"] in ("thin", "single holder", "ok") for f in before["families"])
    note = {"author": before["people"][0]["name"], "role": "senior technician", "years": 9, "machine_id": "M-91",
            "text": "On this rooftop unit the trips are the inverter board. Check the DC bus before touching the contactor."}
    assert c.post("/api/knowledge", json=note).status_code == 200
    after = c.get("/api/company").json()
    assert after["totals"]["notes"] == 1 and after["people"][0]["notes"] == 1
    assert any(f["notes"] == 1 for f in after["families"])


def test_chat_tells_questions_from_things_to_remember():
    import chatintent as ci
    for q in ("What usually goes wrong with the Daikin VRV IV?", "how do I reset the breaker", "Which fixes should I not repeat?", "tell me about M-91"):
        assert ci.intent(q) == "ask", q
    for s in ("Remember the key for Brookfield is kept at the security desk", "I replaced the inverter board on M-91 and the trips stopped",
              "On the rooftop units the real cause is always the inverter board, never the contactor, so check the DC bus first before you order any parts"):
        assert ci.intent(s) == "share", s
    assert ci.machine_in("it happened on m-91 again") == "M-91" and ci.machine_in("no machine here") is None


def test_chat_answers_questions_and_remembers_what_it_is_told(client):
    c, app_mod = client
    a = c.post("/api/chat", json={"message": "What usually goes wrong with the Daikin VRV IV compressor?", "author": "Priya"}).json()
    assert a["kind"] == "answer" and a["answer"] and a["sources"]
    s = c.post("/api/chat", json={"message": "Remember that on M-91 the trips are always the inverter board, never the contactor. Check the DC bus first.", "author": "Raghu Murthy"}).json()
    assert s["kind"] == "saved" and s["machine_id"] == "M-91" and "Raghu Murthy" in s["memory_text"]
    assert app_mod.store.notes and app_mod.store.notes[0]["author"] == "Raghu Murthy"
    again = c.post("/api/chat", json={"message": "Raghu Murthy inverter board DC bus trips on M-91?", "author": "Priya"}).json()
    assert any("Raghu Murthy" in x["text"] for x in again["sources"])
    short = c.post("/api/chat", json={"message": "Remember this", "author": "Priya"}).json()
    assert short["kind"] == "clarify"
    follow = c.post("/api/chat", json={"message": "and for 2024 units?", "author": "Priya", "context": "What usually goes wrong with the Daikin VRV IV compressor?"}).json()
    assert follow["kind"] == "answer"


def _fresh(app_mod):
    from fastapi.testclient import TestClient
    return TestClient(app_mod.app)


def test_the_company_chat_needs_a_workspace_and_rejects_a_wrong_code(client):
    _, app_mod = client
    anon = _fresh(app_mod)
    assert anon.post("/api/chat", json={"message": "What goes wrong with the Daikin VRV IV?"}).status_code == 401
    assert anon.get("/api/docs").status_code == 401
    assert anon.post("/api/workspace/join", json={"code": "NOT-A-CODE", "email": "a@b.co"}).status_code == 403
    assert anon.post("/api/workspace/join", json={"code": "COOLCARE-DEMO", "email": "not-an-email"}).status_code == 422
    assert anon.post("/api/chat", json={"message": "hello there friend"}, headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_a_company_keeps_its_knowledge_to_itself_and_can_limit_by_email_domain(client):
    _, app_mod = client
    anon = _fresh(app_mod)
    made = anon.post("/api/workspace/create", json={"name": "Acme Cooling", "email": "boss@acme-cooling.example"}).json()
    code, tok = made["code"], made["token"]
    assert made["workspace"]["domain"] == "acme-cooling.example" and "Only @acme-cooling.example" in made["note"]
    assert anon.post("/api/workspace/join", json={"code": code, "email": "x@other.example"}).status_code == 403          # wrong email domain
    ok = anon.post("/api/workspace/join", json={"code": code, "email": "tech@acme-cooling.example"})
    assert ok.status_code == 200
    acme = {"Authorization": "Bearer " + tok}
    note = "Remember that our chillers at the east plant always trip on low water flow, so clean the strainer before anything else."
    assert anon.post("/api/chat", json={"message": note, "author": "Boss"}, headers=acme).json()["kind"] == "saved"
    mine = anon.post("/api/chat", json={"message": "chillers east plant low water flow strainer?"}, headers=acme).json()
    assert any("strainer" in x["text"] for x in mine["sources"])
    other = _fresh(app_mod)
    demo_tok = other.post("/api/workspace/join", json={"code": "COOLCARE-DEMO", "email": "p@x.co"}).json()["token"]
    theirs = other.post("/api/chat", json={"message": "chillers east plant low water flow strainer?"}, headers={"Authorization": "Bearer " + demo_tok}).json()
    assert not any("strainer" in x["text"] and "east plant" in x["text"] for x in theirs["sources"])                         # Acme's note never reaches CoolCare


def test_a_document_dropped_into_the_chat_is_learned_and_cited(client):
    c, app_mod = client
    body = ("Case study: the Orion rooftop chiller kept tripping every afternoon.\n\n" + "The cause was a failing condenser fan capacitor, not the compressor. " * 12 +
            "\n\nLesson: always measure the fan capacitor before ordering a compressor.")
    r = c.post("/api/docs", files={"file": ("orion-case-study.md", body.encode(), "text/markdown")}, data={"author": "Meena Iyer"})
    assert r.status_code == 200 and r.json()["sections"] >= 1 and r.json()["name"] == "orion-case-study.md"
    assert [d["name"] for d in c.get("/api/docs").json()] == ["orion-case-study.md"]
    found = c.post("/api/chat", json={"message": "Orion rooftop chiller tripping condenser fan capacitor?"}).json()
    assert any("orion-case-study.md" in x["text"] for x in found["sources"])
    assert c.post("/api/docs", files={"file": ("photo.png", b"\x89PNG", "image/png")}).status_code == 422
    assert c.post("/api/docs", files={"file": ("empty.txt", b"   ", "text/plain")}).status_code == 422


def test_sources_are_labelled_by_kind_and_the_answer_says_how_well_supported_it_is(client):
    import provenance as pv
    c, _ = client
    assert pv.classify(["kind:visit", "evidence:stable_90d"])["tier"] == "verified"
    assert pv.classify(["kind:visit", "evidence:suspected"])["label"] == "Suspected cause"
    assert pv.classify(["kind:note"])["label"] == "Colleague's note" and pv.classify(["kind:doc"])["tier"] == "doc"
    assert pv.basis([])["level"] == "weak"
    assert pv.basis([{"tier": "verified"}, {"tier": "verified"}])["level"] == "strong"
    assert pv.basis([{"tier": "note"}])["level"] == "partial"
    r = c.post("/api/chat", json={"message": "What usually goes wrong with the Daikin VRV IV compressor?"}).json()
    assert r["basis"]["level"] in ("strong", "partial", "weak") and all("label" in s and "tier" in s for s in r["sources"])


def test_a_correction_is_retained_shown_ahead_of_the_answer_and_logged(client):
    c, app_mod = client
    q = "Why does the Orion lobby unit short cycle?"
    first = c.post("/api/chat", json={"message": q}).json()
    fb = c.post("/api/feedback", json={"question": q, "answer": first["answer"], "rating": "down", "refs": ["J-1"],
                                       "correction": "It short cycles because the thermostat sits in direct sun; move the sensor, do not replace the compressor."})
    assert fb.status_code == 200 and fb.json()["correction_retained"] is True
    again = c.post("/api/chat", json={"message": "Orion lobby unit short cycle thermostat direct sun?"}).json()
    assert again["answer"].startswith("Heads up, a colleague corrected this:") and any(s["tier"] == "correction" for s in again["sources"])
    up = c.post("/api/feedback", json={"question": q, "rating": "up"}).json()
    assert up["saved"] and not up["correction_retained"]
    short = c.post("/api/feedback", json={"question": q, "rating": "down", "correction": "wrong"}).json()
    assert not short["correction_retained"]                                    # too short to be a usable correction


def test_only_the_admin_can_reset_or_run_the_evaluation_and_the_tour_has_a_guest_session(client):
    c, app_mod = client
    assert c.get("/api/workspace/me").json()["admin"] is True                  # priya joined first, so she is the admin
    other = _fresh(app_mod)
    tok = other.post("/api/workspace/join", json={"code": "COOLCARE-DEMO", "email": "ravi@coolcare.example"}).json()
    assert tok["admin"] is False
    member = {"Authorization": "Bearer " + tok["token"]}
    assert other.post("/api/reset-demo", headers=member).status_code == 403
    assert other.post("/api/eval/run", headers=member).status_code == 403
    guest = other.post("/api/workspace/guest").json()
    assert guest["email"] == "guest@demo.local" and guest["admin"] is False
    assert other.post("/api/reset-demo", headers={"Authorization": "Bearer " + guest["token"]}).status_code == 403
    assert other.post("/api/runs", json={"scenario_id": "LIVE-4", "paths": "with"}).status_code == 401              # running agents needs a session
    assert other.post("/api/runs", json={"scenario_id": "LIVE-4", "paths": "with"}, headers={"Authorization": "Bearer " + guest["token"]}).status_code == 200
    assert c.post("/api/reset-demo").status_code == 200                         # the admin can
