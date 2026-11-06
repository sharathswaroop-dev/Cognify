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
    app_mod.state_path = tmp_path / "state.json"
    return TestClient(app_mod.app), app_mod


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
