"""Band transport, tested against a mock of Band's Agent API (schemas from docs.band.ai/openapi.json)."""
import json
import time

import httpx
import pytest

from conftest import make_llm
from mesh.band import BandClient, BandError, load_clients, parse_payload, ROLES
from mesh.runner import ControlRoom


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
            msg = {"id": f"m{len(self.messages) + 1}", "content": m["content"], "to": m["mentions"][0]["id"], "sender_id": who["id"],
                   "sender_type": "Agent", "message_type": "text", "state": "pending"}
            self.messages.append(msg)
            return httpx.Response(201, json={"data": {"id": msg["id"], "success": True, "recipients": []}})
        if path.endswith("/messages/next"):
            nxt = next((m for m in self.messages if m["to"] == who["id"] and m["state"] == "pending"), None)
            return httpx.Response(200, json={"data": nxt}) if nxt else httpx.Response(204)
        for state in ("processing", "processed"):
            if path.endswith("/" + state):
                next(m for m in self.messages if m["id"] == path.split("/")[-2])["state"] = state
                return httpx.Response(200, json={"data": {}})
        return httpx.Response(404)


def band(fail_on=None):
    fb = FakeBand(fail_on)
    transport = httpx.MockTransport(fb.handler)
    return fb, {r: BandClient(r, f"key-{r}", "https://app.band.ai/api/v1", transport=transport) for r in ROLES}


def run_with(store, shared, clients, scenario="LIVE-1"):
    room = ControlRoom(store, shared, make_llm(), band_clients=clients)
    run = room.start(scenario)
    t = time.time()
    while run.status == "running" and time.time() - t < 30:
        time.sleep(0.05)
    return run


def test_the_with_path_hands_off_through_a_band_room(store, shared):
    fb, clients = band()
    run = run_with(store, shared, clients)
    assert run.status == "done" and run.transport["with"] == "band" and run.transport["without"] == "in-process"
    assert [m["sender_id"] for m in fb.messages] == ["id-dispatcher", "id-diagnostician", "id-parts", "id-verifier"]  # each agent posts with its own key
    assert all(m["state"] == "processed" for m in fb.messages)             # receivers read and acknowledged them
    assert sum(1 for c in fb.calls if c[1].endswith("/participants")) == 3 and ("POST", "/agent/chats", "sm_dispatcher") in fb.calls
    assert parse_payload(fb.messages[0]["content"])["alarm"]["code"] == "E3"
    hands = [e for e in run.events if e["kind"] == "handoff" and e["path"] == "with"]
    assert hands and all(e["data"]["via"] == "band" for e in hands)


def test_if_band_fails_midway_the_run_continues_in_process(store, shared):
    fb, clients = band(fail_on="/messages")
    run = run_with(store, shared, clients)
    assert run.status == "done" and "with" in run.plans and run.transport["with"] == "in-process"
    assert any("Band unreachable" in e["text"] for e in run.events if e["kind"] == "system")


def test_if_band_is_down_at_room_creation_we_still_run(store, shared):
    fb, clients = band(fail_on="/agent/chats")
    run = run_with(store, shared, clients)
    assert run.status == "done" and "with" in run.plans and run.transport["with"] == "in-process"


def test_unrelated_messages_to_an_agent_are_skipped_not_mistaken_for_the_handoff(store, shared):
    fb, clients = band()
    fb.messages.append({"id": "noise1", "content": "Room created", "to": "id-diagnostician", "sender_id": "system", "sender_type": "System",
                        "message_type": "event", "state": "pending"})
    run = run_with(store, shared, clients)
    assert run.transport["with"] == "band" and next(m for m in fb.messages if m["id"] == "noise1")["state"] == "processed"


def test_the_baseline_path_never_touches_band(store, shared):
    fb, clients = band()
    run_with(store, shared, clients)
    assert all(c[1] != "/agent/chats" or c[0] == "POST" for c in fb.calls) and sum(1 for c in fb.calls if c[1] == "/agent/chats") == 1


def test_load_clients_needs_all_four_keys(monkeypatch):
    for r in ROLES:
        monkeypatch.delenv(f"BAND_KEY_{r.upper()}", raising=False)
    assert load_clients() is None
    for r in ROLES[:3]:
        monkeypatch.setenv(f"BAND_KEY_{r.upper()}", "k")
    assert load_clients() is None
    monkeypatch.setenv(f"BAND_KEY_{ROLES[3].upper()}", "k")
    assert set(load_clients()) == set(ROLES) and ROLES == ("dispatcher", "diagnostician", "parts", "verifier")


def test_error_responses_raise_band_error():
    c = BandClient("x", "k", transport=httpx.MockTransport(lambda r: httpx.Response(401, text="nope")))
    with pytest.raises(BandError, match="401"):
        c.me()
