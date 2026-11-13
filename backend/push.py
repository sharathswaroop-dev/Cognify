"""Push notifications through Firebase Cloud Messaging (the HTTP v1 API).

Best effort by design: sending never blocks a request and never raises into the dispatch engine. Without a service-account file the pusher is switched off
and the phones simply keep polling, exactly as before. The service-account file is a secret: it lives outside git (see .gitignore) and is never logged."""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Callable

log = logging.getLogger("sitememory.push")
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


def default_path() -> Path:
    env = os.getenv("FIREBASE_SERVICE_ACCOUNT", "").strip()
    return Path(env) if env else Path(__file__).resolve().parent / "data" / "firebase-service-account.json"


class Pusher:
    def __init__(self, path: Path | None = None, sender: Callable[[str, str, str, dict], str] | None = None):
        self.path = path or default_path()
        self._sender = sender                     # tests inject a fake; it returns "ok", "dead" (token no longer valid) or "error"
        self._creds = None
        self._project = None
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._sender) or self.path.exists()

    def _auth(self) -> tuple[str, str]:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        with self._lock:
            if self._creds is None:
                self._creds = service_account.Credentials.from_service_account_file(str(self.path), scopes=[SCOPE])
                self._project = json.loads(self.path.read_text(encoding="utf-8"))["project_id"]
            if not self._creds.valid:
                self._creds.refresh(Request())
            return self._creds.token, self._project

    def _send_one(self, token: str, title: str, body: str, data: dict) -> str:
        if self._sender:
            return self._sender(token, title, body, data)
        import requests
        access, project = self._auth()
        msg = {"message": {"token": token, "notification": {"title": title, "body": body}, "data": {k: str(v) for k, v in (data or {}).items()},
                           "android": {"priority": "HIGH", "notification": {"channel_id": "cognify_default"}}}}
        r = requests.post(f"https://fcm.googleapis.com/v1/projects/{project}/messages:send", headers={"Authorization": f"Bearer {access}"}, json=msg, timeout=10)
        if r.status_code == 200:
            return "ok"
        if r.status_code in (400, 404) and any(x in r.text for x in ("UNREGISTERED", "INVALID_ARGUMENT", "NOT_FOUND")):
            return "dead"
        log.warning("push failed: HTTP %s", r.status_code)
        return "error"

    def send(self, tokens: list[str], title: str, body: str, data: dict | None = None, on_dead: Callable[[str], None] | None = None) -> None:
        """Send to every token in a background thread. A token Firebase says is gone is handed to `on_dead` so it can be forgotten."""
        if not tokens or not self.enabled:
            return

        def run():
            for t in tokens:
                try:
                    if self._send_one(t, title, body, data or {}) == "dead" and on_dead:
                        on_dead(t)
                except Exception as exc:                      # never let a failed push touch the engine
                    log.warning("push error: %s", type(exc).__name__)

        threading.Thread(target=run, daemon=True, name="push").start()
