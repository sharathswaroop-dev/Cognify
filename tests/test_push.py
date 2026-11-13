"""Push notifications: who is told what, and when. A fake sender stands in for Firebase, so nothing leaves the machine."""
import importlib
import os
import sys
import time
from pathlib import Path

import pytest

for k in ("HINDSIGHT_API_KEY", "HINDSIGHT_BASE_URL", "GROQ_API_KEY"):
    os.environ[k] = ""

from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend"))
import push  # noqa: E402
import session  # noqa: E402

CODE = "COOLCARE-DEMO"
TOKEN_A = "a" * 40
TOKEN_B = "b" * 40


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("HINDSIGHT_BANK_ID", "test-bank")
    monkeypatch.setenv("DISPATCH_PRESENTER_KEY", "test-key")
    sys.modules.pop("app", None)
    app_mod = importlib.import_module("app")
    import workspaces
    workspaces.DATA = tmp_path
    workspaces.ensure_demo("CoolCare Facility Services", "test-bank")
    from dispatch import Dispatch
    app_mod.dispatch = Dispatch(app_mod.store, tmp_path / "dispatch.json")
    app_mod._limiter = session.Limiter()
    sent, verdict = [], {"v": "ok"}

    def fake(token, title, body, data):
        sent.append({"token": token, "title": title, "body": body, "data": data})
        return verdict["v"]

    app_mod.pusher = push.Pusher(path=Path(tmp_path / "none.json"), sender=fake)
    d = app_mod.dispatch
    d.push_hook = lambda key, title, body, data: app_mod.pusher.send(d.push_tokens(key), title, body, data, on_dead=lambda t: d.unregister_push(key, t))
    c = TestClient(app_mod.app)

    def call(method, path, who=None, **kw):
        return c.request(method, path, headers={"X-Cognify-Session": who} if who else {}, **kw)

    return call, sent, verdict, d, app_mod


def wait_for(cond, secs=3.0):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def sign_in(call):
    rep = call("POST", "/api/dispatch/register", json={"name": "Priya Nair", "role": "reporter", "site_id": "S-05"}).json()
    tech = call("POST", "/api/dispatch/login", json={"tech_id": "T-04", "company_code": CODE}).json()
    return rep, tech


def test_phones_register_by_person_and_a_login_is_required(world):
    call, _, _, d, _ = world
    assert call("POST", "/api/push/register", json={"token": TOKEN_A}).status_code == 401
    rep, tech = sign_in(call)
    assert call("POST", "/api/push/register", rep["session"], json={"token": TOKEN_A}).status_code == 200
    assert call("POST", "/api/push/register", tech["session"], json={"token": TOKEN_B}).status_code == 200
    assert d.push_tokens(rep["id"]) == [TOKEN_A] and d.push_tokens("T-04") == [TOKEN_B]       # a technician by technician id, a reporter by user id
    p = call("POST", "/api/dispatch/presenter-login", json={"key": "test-key"}).json()["session"]
    assert call("POST", "/api/push/register", p, json={"token": TOKEN_A}).status_code == 403   # the presenter has no phone
    assert call("POST", "/api/push/register", rep["session"], json={"token": "short"}).status_code == 422
    call("POST", "/api/push/unregister", rep["session"], json={"token": TOKEN_A})
    assert d.push_tokens(rep["id"]) == []


def test_the_right_person_is_told_at_each_step(world):
    call, sent, _, d, app_mod = world
    rep, tech = sign_in(call)
    call("POST", "/api/push/register", rep["session"], json={"token": TOKEN_A})
    call("POST", "/api/push/register", tech["session"], json={"token": TOKEN_B})
    clock = {"t": time.time()}
    d.now = lambda: clock["t"]
    rid = call("POST", "/api/reports", rep["session"], json={"user_id": rep["id"], "site_id": "S-05", "machine_id": "M-42", "symptom": "Not cooling at all", "severity": "high", "manual": True}).json()["id"]
    assert wait_for(lambda: any(m["title"] == "New job offer" and m["token"] == TOKEN_B for m in sent))             # the offer reaches the technician's phone
    assert not any(m["token"] == TOKEN_A for m in sent)                                                              # the reporter is not told about offers
    call("POST", f"/api/reports/{rid}/respond", tech["session"], json={"tech_id": "T-04", "action": "accept"})
    clock["t"] += 10
    d.tick()
    assert wait_for(lambda: any(m["title"] == "Technician confirmed" and m["token"] == TOKEN_A for m in sent))        # the reporter is told it is confirmed
    assert wait_for(lambda: any(m["title"] == "You got the job" and m["token"] == TOKEN_B for m in sent))
    call("POST", f"/api/reports/{rid}/status", tech["session"], json={"tech_id": "T-04", "status": "on_site"})
    assert wait_for(lambda: any(m["title"] == "Technician arrived" for m in sent))
    arrived = next(m for m in sent if m["title"] == "Technician arrived")
    otp = d.get(rid)["otp"]
    assert otp not in arrived["body"]                                                                                # the OTP never goes on a lock screen
    call("POST", f"/api/reports/{rid}/start", tech["session"], json={"tech_id": "T-04", "otp": otp})
    call("POST", f"/api/reports/{rid}/status", tech["session"], json={"tech_id": "T-04", "status": "resolved", "done": True})
    assert wait_for(lambda: any(m["title"] == "Work done" and m["token"] == TOKEN_A for m in sent))


def test_a_token_firebase_says_is_dead_is_forgotten(world):
    call, sent, verdict, d, _ = world
    rep, _ = sign_in(call)
    call("POST", "/api/push/register", rep["session"], json={"token": TOKEN_A})
    verdict["v"] = "dead"
    d._push(rep["id"], "Hello", "test", {})
    assert wait_for(lambda: d.push_tokens(rep["id"]) == [])


def test_a_failed_send_never_breaks_dispatch(world):
    call, _, _, d, app_mod = world
    rep, tech = sign_in(call)
    call("POST", "/api/push/register", tech["session"], json={"token": TOKEN_B})

    def boom(*a, **k):
        raise RuntimeError("firebase is down")

    app_mod.pusher._sender = boom
    r = call("POST", "/api/reports", rep["session"], json={"user_id": rep["id"], "site_id": "S-05", "machine_id": "M-42", "symptom": "Not cooling at all", "severity": "high", "manual": True})
    assert r.status_code == 200 and r.json()["status"] == "offered"


def test_without_a_service_account_file_push_is_simply_off(tmp_path):
    p = push.Pusher(path=tmp_path / "missing.json")
    assert p.enabled is False
    p.send([TOKEN_A], "x", "y")                    # does nothing, raises nothing
