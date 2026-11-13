"""Login on the dispatch routes: who may do what. Real FastAPI app, every external service switched off."""
import importlib
import os
import sys

import pytest

for k in ("HINDSIGHT_API_KEY", "HINDSIGHT_BASE_URL", "GROQ_API_KEY"):
    os.environ[k] = ""

from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend"))
import session  # noqa: E402

CODE = "COOLCARE-DEMO"


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("HINDSIGHT_BANK_ID", "test-bank")
    monkeypatch.setenv("DISPATCH_PRESENTER_KEY", "test-key")
    monkeypatch.delenv("DISPATCH_COMPANY_CODE", raising=False)
    sys.modules.pop("app", None)
    app_mod = importlib.import_module("app")
    import workspaces
    workspaces.DATA = tmp_path
    workspaces.ensure_demo("CoolCare Facility Services", "test-bank")
    from dispatch import Dispatch
    app_mod.dispatch = Dispatch(app_mod.store, tmp_path / "dispatch.json")
    app_mod._limiter = session.Limiter()
    c = TestClient(app_mod.app)

    def call(method, path, who=None, **kw):
        headers = {"X-Cognify-Session": who} if who else {}
        return c.request(method, path, headers=headers, **kw)

    call.client = c
    return call


def reporter(api, name="Priya Nair"):
    r = api("POST", "/api/dispatch/register", json={"name": name, "role": "reporter", "site_id": "S-01"})
    assert r.status_code == 200
    return r.json()


def tech(api, tid="T-04"):
    r = api("POST", "/api/dispatch/login", json={"tech_id": tid, "company_code": CODE})
    assert r.status_code == 200
    return r.json()


def presenter(api):
    r = api("POST", "/api/dispatch/presenter-login", json={"key": "test-key"})
    assert r.status_code == 200, r.text
    return r.json()["session"]


def test_nothing_on_the_dispatch_routes_works_without_signing_in(api):
    assert api("GET", "/api/dispatch/board").status_code == 401
    assert api("GET", "/api/dispatch/map").status_code == 401
    assert api("GET", "/api/tech/T-04/inbox").status_code == 401
    assert api("GET", "/api/reports").status_code == 401
    assert api("POST", "/api/dispatch/demo-report").status_code == 401
    assert api("POST", "/api/reports/R-0001/respond", json={"tech_id": "T-04", "action": "accept"}).status_code == 401


def test_a_technician_needs_the_company_code(api):
    bad = api("POST", "/api/dispatch/login", json={"tech_id": "T-04", "company_code": "nope"})
    assert bad.status_code == 403
    joined = api("POST", "/api/dispatch/register", json={"name": "Ravi Kumar", "role": "technician", "company_code": "wrong"})
    assert joined.status_code == 403
    ok = api("POST", "/api/dispatch/register", json={"name": "Ravi Kumar", "role": "technician", "company_code": CODE})
    assert ok.status_code == 200 and ok.json()["session"] and ok.json()["tech_id"]


def test_the_simulated_city_fleet_cannot_be_signed_in_as(api):
    assert api("POST", "/api/dispatch/login", json={"tech_id": "T-101", "company_code": CODE}).status_code == 403


def test_a_technician_can_only_act_as_themselves(api):
    me = tech(api, "T-04")["session"]
    assert api("GET", "/api/tech/T-04/inbox", me).status_code == 200
    assert api("GET", "/api/tech/T-01/inbox", me).status_code == 403                    # someone else's phone
    assert api("POST", "/api/tech/T-01/duty", me, json={"on": False}).status_code == 403
    assert api("POST", "/api/reports/R-0001/respond", me, json={"tech_id": "T-01", "action": "accept"}).status_code == 403
    assert api("POST", "/api/reports/R-0001/respond", me, json={"tech_id": "T-04", "action": "accept", "demo": True}).status_code == 403   # the demo flag is the presenter's


def test_a_reporter_can_only_report_and_read_as_themselves(api):
    me, other = reporter(api), reporter(api, "Asha Rao")
    ok = api("POST", "/api/reports", me["session"], json={"user_id": me["id"], "site_id": "S-01", "machine_id": "M-07", "symptom": "Not cooling at all", "severity": "high"})
    assert ok.status_code == 200
    rid = ok.json()["id"]
    assert api("POST", "/api/reports", me["session"], json={"user_id": other["id"], "site_id": "S-01", "symptom": "Not cooling at all"}).status_code == 403
    assert api("GET", f"/api/reports/{rid}", me["session"]).status_code == 200
    assert api("GET", f"/api/reports/{rid}", other["session"]).status_code == 403          # not their request
    mine = api("GET", f"/api/reports?user_id={other['id']}", me["session"]).json()          # asking for someone else's list still returns only their own
    assert [r["id"] for r in mine] == [rid]
    assert api("GET", "/api/dispatch/board", me["session"]).status_code == 403             # the live board is the presenter's


def test_only_the_reporter_sees_the_otp(api):
    me, t = reporter(api), tech(api, "T-04")
    rid = api("POST", "/api/reports", me["session"], json={"user_id": me["id"], "site_id": "S-05", "machine_id": "M-42", "symptom": "Not cooling at all", "severity": "high", "manual": True}).json()["id"]
    assert api("GET", f"/api/tech/{t['tech_id']}/inbox", t["session"]).status_code == 200
    api("POST", f"/api/reports/{rid}/respond", t["session"], json={"tech_id": "T-04", "action": "accept"})
    import time
    import app as app_mod
    app_mod.dispatch.state["reports"][-1]["decide_at"] = time.time() - 1
    app_mod.dispatch.tick()
    assert api("GET", f"/api/reports/{rid}", me["session"]).json().get("otp")
    assert not api("GET", f"/api/reports/{rid}", t["session"]).json().get("otp")


def test_the_demo_controls_are_the_presenters(api):
    me = reporter(api)
    assert api("POST", "/api/dispatch/demo-report", me["session"]).status_code == 403
    assert api("POST", "/api/dispatch/fleet", me["session"], json={"big": True}).status_code == 403
    p = presenter(api)
    assert api("POST", "/api/dispatch/demo-report", p).status_code == 200
    assert api("GET", "/api/dispatch/board", p).status_code == 200


def test_the_presenter_key_rules(api, monkeypatch):
    monkeypatch.setenv("DISPATCH_PRESENTER_KEY", "s3cret")
    assert api("POST", "/api/dispatch/presenter-login", json={"key": "wrong"}).status_code == 403
    assert api("POST", "/api/dispatch/presenter-login", json={"key": "s3cret"}).status_code == 200
    monkeypatch.delenv("DISPATCH_PRESENTER_KEY")
    behind_tunnel = api.client.post("/api/dispatch/presenter-login", json={"key": ""}, headers={"X-Forwarded-For": "203.0.113.5"})
    assert behind_tunnel.status_code == 403                  # no key set and the request came through a proxy: refused


def test_tokens_expire_and_cannot_be_forged(api):
    tok = session.issue("technician", "T-04", "T-04", now=1_000_000)
    with pytest.raises(session.SessionError):
        session.verify(tok, now=1_000_000 + session.TTL + 5)
    body, sig = tok.rsplit(".", 1)
    forged = body + "." + ("0" * len(sig))
    with pytest.raises(session.SessionError):
        session.verify(forged, now=1_000_001)
    assert api("GET", "/api/tech/T-04/inbox", forged).status_code == 401


def test_guessing_the_company_code_is_rate_limited(api):
    codes = [api("POST", "/api/dispatch/login", json={"tech_id": "T-04", "company_code": f"guess{i}"}).status_code for i in range(15)]
    assert 429 in codes


def test_without_a_key_only_the_laptop_itself_may_be_the_presenter(monkeypatch):
    monkeypatch.delenv("DISPATCH_PRESENTER_KEY", raising=False)
    assert session.presenter_ok("", "127.0.0.1", False) is True
    assert session.presenter_ok("", "127.0.0.1", True) is False         # came through a tunnel or proxy
    assert session.presenter_ok("", "192.168.1.20", False) is False     # another machine on the network
