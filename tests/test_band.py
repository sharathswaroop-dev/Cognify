"""Band transport, tested against a mock of Band's Agent API (schemas from docs.band.ai/openapi.json)."""
import json
import time

import httpx

from conftest import make_llm
from mesh.band import BandClient, BandError, load_clients, parse_payload

ROLES = ("dispatcher", "diagnostician", "parts", "field")


class FakeBand:
    """Just enough of the Agent API: me, rooms, participants, messages, next, processing/processed."""

    def __init__(self, fail_on=None):
        self.agents = {f"key-{r}": {"id": f"id-{r}", "handle": f"sm_{r}", "name": f"SM {r}"} for r in ROLES}
        self.messages, self.calls, self.fail_on = [], [], fail_on

    def handler(self, req: httpx.Request) -> httpx.Response:
        who = self.agents[req.headers["x-api-key"]]
        path = req.url.path.replace("/api/v1", "")
        self.calls.append((req.method, path, who["handle"]))
        if self.fail_on and self.fail_on in path:
            return httpx.Response(500, json={"error": "boom"})
        if path == "/agent/me":
            return httpx.Response(200, json={"data": who})
        if path == "/agent/chats" and req.method == "POST":
            assert "title" in json.loads(req.content)["chat"]
            return httpx.Response(201, json={"data": {"id": "room-1"}})
        if path.endswith("/participants"):
            assert "participant_id" in json.loads(req.content)["participant"]
            return httpx.Response(201, json={"data": {"id": "p", "role": "member", "status": "active", "type": "Agent"}})
        if path.endswith("/messages") and req.method == "POST":
            m = json.loads(req.content)["message"]
            assert m["mentions"] and m["mentions"][0]["id"], "Band requires at least one mention"
            msg = {"id": f"m{len(self.messages) + 1}", "content": m["content"], "to": m["mentions"][0]["id"],
                   "sender_id": who["id"], "sender_type": "Agent", "message_type": "text", "state": "pending"}
            self.messages.append(msg)
            return httpx.Response(201, json={"data": {"id": msg["id"], "success": True, "recipients": []}})
        if path.endswith("/messages/next"):
            nxt = next((m for m in self.messages if m["to"] == who["id"] and m["state"] == "pending"), None)
            return httpx.Response(200, json={"data": nxt}) if nxt else httpx.Response(204)
        for state in ("processing", "processed"):
            if path.endswith("/" + state):
                mid = path.split("/")[-2]
                next(m for m in self.messages if m["id"] == mid)["state"] = state
                return httpx.Response(200, json={"data": {}})
        return httpx.Response(404)


def band(fail_on=None):
    fb = FakeBand(fail_on)
    transport = httpx.MockTransport(fb.handler)
    clients = {r: BandClient(r, f"key-{r}", "https://app.band.ai/api/v1", transport=transport) for r in ROLES}
    return fb, clients


def wait(run, timeout=20):
    t = time.time()
    while run.status == "running" and time.time() - t < timeout:
        time.sleep(0.05)
    return run


def live(store, i):
    sc = next(a for a in store.live_alarms if a["id"] == i)
    return {**sc, "id": sc["id"] + "-b", "remote_action": None, "remote_result": "none", "dispatched": False}


def test_handoffs_travel_through_a_band_room(build_mesh, store):
    fb, clients = band()
    mesh, _, _ = build_mesh(band=clients)
    run = wait(mesh.start(live(store, "LIVE-1")))
    assert run.status == "done" and run.transport == "band"
    assert [e["transport"] for e in run.events if e["kind"] == "handoff"] == ["band"] * 3
    senders = [m["sender_id"] for m in fb.messages]
    assert senders == ["id-dispatcher", "id-diagnostician", "id-parts"]  # each agent posted with its own key
    assert all(m["state"] == "processed" for m in fb.messages)          # receivers read and acknowledged them
    assert ("POST", "/agent/chats", "sm_dispatcher") in fb.calls
    assert sum(1 for c in fb.calls if c[1].endswith("/participants")) == 3
    assert parse_payload(fb.messages[0]["content"])["alarm"]["code"] == "E3"


def test_if_band_fails_the_run_continues_in_process(build_mesh, store):
    fb, clients = band(fail_on="/messages")
    mesh, _, _ = build_mesh(band=clients)
    run = wait(mesh.start(live(store, "LIVE-1")))
    assert run.status == "done" and run.result["decision"] == "SEND_TECHNICIAN"
    assert run.transport == "local"
    assert any("Band unreachable" in e["text"] for e in run.events if e["kind"] == "system")


def test_if_band_is_down_at_room_creation_we_still_run(build_mesh, store):
    fb, clients = band(fail_on="/agent/chats")
    mesh, _, _ = build_mesh(band=clients)
    run = wait(mesh.start(live(store, "LIVE-1")))
    assert run.status == "done" and run.transport == "local"


def test_load_clients_needs_all_four_keys(monkeypatch):
    for r in ROLES:
        monkeypatch.delenv(f"BAND_KEY_{r.upper()}", raising=False)
    assert load_clients() is None
    for r in ROLES[:3]:
        monkeypatch.setenv(f"BAND_KEY_{r.upper()}", "k")
    assert load_clients() is None
    monkeypatch.setenv("BAND_KEY_FIELD", "k")
    assert set(load_clients()) == set(ROLES)


def test_error_responses_raise_band_error():
    c = BandClient("x", "k", transport=httpx.MockTransport(lambda r: httpx.Response(401, text="nope")))
    try:
        c.me()
        assert False
    except BandError as exc:
        assert "401" in str(exc)
