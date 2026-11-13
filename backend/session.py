"""Who is calling the dispatch routes.

A person signs in once (a reporter by registering, a technician with the company code, the presenter with the presenter key) and gets a signed session
token. The routes then check WHO the token belongs to, so a technician can only act as themselves, a reporter can only see their own requests,
and only the presenter can run the demo controls. Tokens are HMAC-signed with the workspace secret and expire after 12 hours."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import time
from collections import defaultdict, deque

TTL = 12 * 3600
ROLES = ("reporter", "technician", "presenter")


class SessionError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.message, self.status = message, status


def _secret() -> bytes:
    import workspaces
    return workspaces._secret()


def _sign(body: str) -> str:
    return hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:40]


def issue(role: str, uid: str, tid: str | None = None, now: float | None = None) -> str:
    if role not in ROLES:
        raise ValueError("Unknown role")
    payload = {"r": role, "u": uid, "t": tid, "e": int((now or time.time()) + TTL)}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return f"{body}.{_sign(body)}"


def verify(tok: str | None, now: float | None = None) -> dict:
    """The claims {role, uid, tid} behind a token, or SessionError."""
    if not tok:
        raise SessionError("Sign in first.")
    try:
        body, sig = tok.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sign(body)):
            raise ValueError
        p = json.loads(base64.urlsafe_b64decode(body.encode()).decode())
        if int(p["e"]) < (now or time.time()) or p["r"] not in ROLES:
            raise ValueError
    except Exception:
        raise SessionError("Your session is not valid any more. Sign in again.") from None
    return {"role": p["r"], "uid": p["u"], "tid": p.get("t")}


def company_code() -> str:
    """The code a technician needs to sign in. Set DISPATCH_COMPANY_CODE to change it; the demo company's code is the default."""
    import workspaces
    return os.getenv("DISPATCH_COMPANY_CODE", "").strip() or workspaces.DEMO_CODE


def code_ok(code: str | None) -> bool:
    return bool(code) and hmac.compare_digest((code or "").strip().upper().encode(), company_code().upper().encode())


def presenter_key() -> str:
    return os.getenv("DISPATCH_PRESENTER_KEY", "").strip()


def presenter_ok(key: str | None, client_host: str | None, forwarded: bool) -> bool:
    """With DISPATCH_PRESENTER_KEY set, only that key signs in. Without one, only the laptop itself (never through a tunnel or proxy) may."""
    want = presenter_key()
    if want:
        return bool(key) and hmac.compare_digest((key or "").encode(), want.encode())
    return (client_host in ("127.0.0.1", "::1", "localhost")) and not forwarded


class Limiter:
    """At most `limit` hits per `per` seconds for each key (an address): a guard on sign-in so codes cannot be guessed."""

    def __init__(self):
        self.lock = threading.Lock()
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str, limit: int = 12, per: float = 60.0, now: float | None = None) -> None:
        t = now if now is not None else time.time()
        with self.lock:
            q = self.hits[key]
            while q and q[0] < t - per:
                q.popleft()
            if len(q) >= limit:
                raise SessionError("Too many attempts. Wait a minute and try again.", 429)
            q.append(t)
