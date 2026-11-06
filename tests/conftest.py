import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
for k in ("GROQ_API_KEY", "HINDSIGHT_API_KEY", "HINDSIGHT_BASE_URL", "BAND_KEY_DISPATCHER"):
    os.environ.pop(k, None)

from agent import Agent  # noqa: E402
from memory import LocalMemory  # noqa: E402
from store import Store  # noqa: E402


class FakeLLM:
    """Deterministic stand-in for Groq. replies maps a substring of the system prompt to a dict or callable(user)->dict."""
    available = True
    model = "fake"

    def __init__(self, replies=None):
        self.replies, self.calls = replies or {}, []

    def json_chat(self, system, user, required=(), attempts=3):
        self.calls.append((system[:40], user))
        for key, reply in self.replies.items():
            if key in system:
                d = reply(user) if callable(reply) else reply
                return d
        return None


DISPATCH_SEND = {"decision": "SEND_TECHNICIAN", "remote_action": None, "confidence": "high",
                 "rationale": "Remote resets failed before.", "evidence": ["Ledger says resets failed"]}


def diag_reply(user):
    ids = re.findall(r"\bJ-\d{3,5}\b", user)
    ev = [{"job_id": ids[0], "date": "2026-03-14", "fact": "contactor fixed it"}] if ids else []
    ev.append({"job_id": "J-9999", "date": "2020-01-01", "fact": "invented"})  # must be dropped
    return {"root_cause": "Compressor contactor burnt by voltage dips", "confidence": "high", "evidence": ev,
            "already_failed": ["Reset outdoor unit breaker"], "next_checks": ["Measure supply voltage"]}


PARTS_REPLY = {"carry": [{"part": "Compressor contactor 24V coil (DK-CTR-24V)", "qty": 1, "reason": "fixed it 9 times"},
                         {"part": "Inverter PCB A2P rev D (DK-PCB-A2P-D)", "qty": 1, "reason": "newer units"}],
               "also_consider": []}
BRIEF_REPLY = {"headline": "Replace the contactor", "likely_cause": "Burnt contactor", "confidence": "high",
               "do_first": ["Replace contactor"], "avoid": ["Reset breaker"], "bring": ["DK-CTR-24V"], "site_notes": ["Gate 4471"]}


def make_llm(**over):
    base = {"Dispatcher agent": DISPATCH_SEND, "Diagnostician agent": diag_reply, "Parts agent": PARTS_REPLY,
            "briefs HVAC field technicians": BRIEF_REPLY}
    base.update(over)
    return FakeLLM(base)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "DATA", store_mod.DATA)  # read real data...
    s = Store()
    s.logged_path = tmp_path / "logged.json"  # ...but never write into the repo
    s.logged = []
    return s


@pytest.fixture()
def build_mesh(store, tmp_path):
    from mesh.runner import Mesh

    def _build(llm=None, band=None):
        llm = llm or make_llm()
        mems = {r: LocalMemory(tmp_path / f"{r}.json") for r in ("field", "dispatcher", "diagnostician", "parts")}
        agent = Agent(mems["field"], store)
        agent.llm = llm
        mesh = Mesh(store, agent, mems, llm, band_clients=band if band is not None else {})
        state = {}
        agent.seed()
        mesh.seed_banks(lambda: state, lambda **kw: state.update(kw))
        return mesh, mems, llm
    return _build
