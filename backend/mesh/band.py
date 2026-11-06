"""Band (band.ai) Agent API client, plain REST so no extra SDK is required.

Endpoints and schemas follow https://docs.band.ai/openapi.json:
  GET  /agent/me                                   identity of the agent that owns the API key
  POST /agent/chats            {chat:{title}}      create a room
  POST /agent/chats/{id}/participants {participant:{participant_id, role}}
  POST /agent/chats/{id}/messages     {message:{content, mentions:[{id,handle,name}]}}
  GET  /agent/chats/{id}/messages/next             next message addressed to this agent
  POST /agent/chats/{id}/messages/{mid}/(processing|processed|failed)
Auth: X-API-Key header, one key per agent.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger("sitememory.band")
DEFAULT_BASE = "https://app.band.ai/api/v1"
ROLES = ("dispatcher", "diagnostician", "parts", "verifier")
_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


class BandError(RuntimeError):
    pass


@dataclass
class Identity:
    id: str
    handle: str
    name: str


class BandClient:
    def __init__(self, role: str, api_key: str, base_url: str = DEFAULT_BASE, transport=None, timeout: float = 8.0):
        self.role = role
        self.http = httpx.Client(base_url=base_url.rstrip("/"), headers={"X-API-Key": api_key},
                                 timeout=timeout, transport=transport)
        self._me: Identity | None = None

    def _req(self, method: str, path: str, **kw) -> dict:
        try:
            r = self.http.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise BandError(f"{self.role}: {method} {path} failed: {exc}") from exc
        if r.status_code in (204, 404) and method == "GET" and path.endswith("/messages/next"):
            return {}
        if r.status_code >= 400:
            raise BandError(f"{self.role}: {method} {path} -> {r.status_code} {r.text[:200]}")
        try:
            return r.json() if r.content else {}
        except ValueError as exc:
            raise BandError(f"{self.role}: {method} {path} returned non-JSON") from exc

    def me(self) -> Identity:
        if not self._me:
            d = self._req("GET", "/agent/me").get("data", {})
            if not d.get("id"):
                raise BandError(f"{self.role}: /agent/me returned no id")
            self._me = Identity(d["id"], d.get("handle", ""), d.get("name", self.role))
        return self._me

    def create_room(self, title: str) -> str:
        d = self._req("POST", "/agent/chats", json={"chat": {"title": title[:120]}}).get("data", {})
        if not d.get("id"):
            raise BandError(f"{self.role}: create room returned no id")
        return d["id"]

    def add_participant(self, room_id: str, participant_id: str, role: str = "member") -> None:
        self._req("POST", f"/agent/chats/{room_id}/participants",
                  json={"participant": {"participant_id": participant_id, "role": role}})

    def send(self, room_id: str, content: str, to: Identity) -> str:
        body = {"message": {"content": f"@{to.handle} {content}" if to.handle else content,
                            "mentions": [{"id": to.id, "handle": to.handle, "name": to.name}]}}
        d = self._req("POST", f"/agent/chats/{room_id}/messages", json=body).get("data", {})
        return d.get("id", "")

    def next_message(self, room_id: str) -> dict | None:
        d = self._req("GET", f"/agent/chats/{room_id}/messages/next").get("data")
        return d or None

    def mark(self, room_id: str, message_id: str, state: str) -> None:
        self._req("POST", f"/agent/chats/{room_id}/messages/{message_id}/{state}")


def parse_payload(content: str) -> dict | None:
    m = _JSON_BLOCK.search(content or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def load_clients(transport=None) -> dict[str, BandClient] | None:
    """Build one client per role from BAND_KEY_<ROLE> env vars. None when Band is not configured."""
    base = os.getenv("BAND_BASE_URL", DEFAULT_BASE)
    keys = {r: os.getenv(f"BAND_KEY_{r.upper()}", "").strip() for r in ROLES}
    if not all(keys.values()):
        return None
    return {r: BandClient(r, k, base, transport=transport) for r, k in keys.items()}


class BandRoom:
    """A Band room for one mesh run. All four agents are participants; each handoff is a real
    Band message that the receiving agent reads back (and acknowledges) before it acts on it."""

    def __init__(self, clients: dict[str, BandClient], title: str, poll_s: float = 6.0):
        self.c = clients
        self.poll_s = poll_s
        self.ids = {r: cl.me() for r, cl in clients.items()}
        self.room_id = clients["dispatcher"].create_room(title)
        for r in ROLES:
            if r != "dispatcher":
                clients["dispatcher"].add_participant(self.room_id, self.ids[r].id)

    def deliver(self, sender: str, to: str, content: str, payload: dict) -> dict:
        """Post a handoff in the room and read it back as the receiver. Returns the received payload."""
        body = f"{content}\n\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```"
        mid = self.c[sender].send(self.room_id, body, self.ids[to])
        deadline = time.time() + self.poll_s
        while time.time() < deadline:
            msg = self.c[to].next_message(self.room_id)
            if msg and not (not mid or msg.get("id") == mid or parse_payload(msg.get("content", "")) is not None):
                # something else addressed to this agent (a notice, an earlier message): acknowledge it and keep waiting for ours
                try:
                    self.c[to].mark(self.room_id, msg["id"], "processing")
                    self.c[to].mark(self.room_id, msg["id"], "processed")
                except BandError:
                    pass
                continue
            if msg:
                got = parse_payload(msg.get("content", ""))
                try:
                    self.c[to].mark(self.room_id, msg["id"], "processing")
                    self.c[to].mark(self.room_id, msg["id"], "processed")
                except BandError as exc:
                    log.warning("could not acknowledge Band message: %s", exc)
                return {"payload": got if got is not None else payload, "message_id": mid, "room_id": self.room_id}
            time.sleep(0.4)
        raise BandError(f"{to} did not receive message {mid} within {self.poll_s}s")
