"""Company workspaces: who is allowed to see a company's knowledge, and which memory bank holds it.

Honest scope: this is a demo-grade gate, not identity verification. A person joins with the company's code and a work email; the server signs a token
that names the workspace and the email, and every chat, document and note is read from and written to THAT company's own memory bank, so one company
never sees another's knowledge. If the company limits itself to an email domain, other domains are refused. It does not prove the email is really
theirs: that needs a sign-in provider (for example Google), which needs credentials from whoever deploys this."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
DEMO_ID, DEMO_CODE = "coolcare", "COOLCARE-DEMO"
PERSONAL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "proton.me", "protonmail.com"}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TTL = 60 * 60 * 24 * 30


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.message, self.status = message, status


def _path() -> Path:
    return DATA / "workspaces.json"


def _load() -> dict:
    p = _path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save(d: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def _secret() -> bytes:
    p = DATA / "workspace_secret.txt"
    if not p.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        p.write_text(secrets.token_hex(32), encoding="utf-8")
    return p.read_text(encoding="utf-8").strip().encode()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "company"


def clean_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not EMAIL.match(e):
        raise AuthError("Enter a valid work email.", 422)
    return e


def ensure_demo(name: str, bank: str) -> dict:
    d = _load()
    if DEMO_ID not in d:
        d[DEMO_ID] = {"id": DEMO_ID, "name": name, "bank": bank, "code_hash": _hash(DEMO_CODE), "domain": None, "demo": True, "created": time.strftime("%Y-%m-%d")}
        _save(d)
    return d[DEMO_ID]


def get(ws_id: str) -> dict | None:
    return _load().get(ws_id)


def create(name: str, email: str, base_bank: str) -> tuple[dict, str]:
    """A new company with its own bank. The code is shown once; only its hash is kept."""
    name, e = name.strip(), clean_email(email)
    if len(name) < 2:
        raise AuthError("Give the company a name.", 422)
    d = _load()
    base = slug(name)
    wid = base
    while wid in d:
        wid = f"{base}-{secrets.token_hex(2)}"
    code = f"{base[:6].upper().replace('-', '')}-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
    dom = e.split("@", 1)[1]
    d[wid] = {"id": wid, "name": name, "bank": f"{base_bank}-{wid}", "code_hash": _hash(code), "domain": None if dom in PERSONAL else dom, "demo": False,
              "created": time.strftime("%Y-%m-%d"), "owner": e}
    _save(d)
    return d[wid], code


def join(code: str, email: str) -> dict:
    e = clean_email(email)
    h = _hash(code)
    ws = next((w for w in _load().values() if hmac.compare_digest(w["code_hash"], h)), None)
    if not ws:
        raise AuthError("That company code is not right. Ask your manager for it.", 403)
    if ws.get("domain") and e.split("@", 1)[1] != ws["domain"]:
        raise AuthError(f"{ws['name']} only lets people with an @{ws['domain']} email in.", 403)
    return ws


def token(ws_id: str, email: str) -> str:
    payload = f"{ws_id}|{email}|{int(time.time()) + TTL}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode()


def verify(tok: str | None) -> tuple[dict, str]:
    """The workspace and email behind a token, or AuthError."""
    if not tok:
        raise AuthError("Join your company's workspace first.")
    try:
        ws_id, email, exp, sig = base64.urlsafe_b64decode(tok.encode()).decode().rsplit("|", 3)
        good = hmac.new(_secret(), f"{ws_id}|{email}|{exp}".encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, good) or int(exp) < time.time():
            raise ValueError
    except Exception:
        raise AuthError("Your session is not valid any more. Join again.") from None
    ws = get(ws_id)
    if not ws:
        raise AuthError("That workspace no longer exists.")
    return ws, email


def local_memory_path(ws_id: str) -> Path:
    return DATA / f"local_memory_ws_{ws_id}.json"


def library_path(ws_id: str) -> Path:
    return DATA / "ws" / f"{ws_id}_library.json"


def library(ws_id: str) -> list[dict]:
    p = library_path(ws_id)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def add_to_library(ws_id: str, item: dict) -> None:
    p = library_path(ws_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(library(ws_id) + [item], indent=1, ensure_ascii=False), encoding="utf-8")
