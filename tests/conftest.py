import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
for k in ("GROQ_API_KEY", "HINDSIGHT_API_KEY", "HINDSIGHT_BASE_URL", "BAND_KEY_DISPATCHER"):
    os.environ.pop(k, None)

import records  # noqa: E402
from memory import LocalMemory  # noqa: E402
from store import Store  # noqa: E402


class FakeLLM:
    """Deterministic stand-in for Groq. replies maps a substring of the system prompt to a dict or callable(user) -> dict."""
    available = True
    model = "fake"

    def __init__(self, replies=None):
        self.replies, self.calls = replies or {}, []

    def json_chat(self, system, user, required=(), attempts=3):
        self.calls.append((system[:40], user))
        for key, reply in self.replies.items():
            if key in system:
                return reply(user) if callable(reply) else reply
        return None


def _blocks(user):
    return [b for b in user.split("\n---\n")]


def _ids(user, needle, extra=None):
    out = []
    for b in _blocks(user):
        m = re.search(r"\[source (J-\d+)", b)
        if m and needle.lower() in b.lower() and (extra is None or extra.lower() in b.lower()):
            out.append(m.group(1))
    return out[:5]


def diag_reply(user):
    """Like a real LLM: it proposes what the memories show most often. After Verifier feedback it proposes the other fix."""
    if "VERIFIER FEEDBACK" in user:
        return {"causes": [{"cause": "Inverter PCB revision C", "fix": "Replaced inverter PCB (A2P) and updated its firmware.",
                            "evidence_jobs": _ids(user, "inverter PCB", "FIXED IT"), "why": "Fixed the newer units"}]}
    return {"causes": [{"cause": "Burnt compressor contactor", "fix": "Replaced compressor contactor and checked phase voltages.",
                        "evidence_jobs": _ids(user, "contactor", "FIXED IT"), "why": "Fixed this model many times"}]}


def parts_reply(user):
    fix = re.search(r"\(fix: (.*?)\)", user).group(1)
    if "inverter" in fix.lower():
        return {"carry": [{"part": "Inverter PCB A2P rev D (DK-PCB-A2P-D)", "qty": 1, "reason": "fixed the newer units",
                           "evidence_jobs": _ids(user, "inverter PCB", "FIXED IT")}]}
    carry = [{"part": "Compressor contactor 24V coil (DK-CTR-24V)", "qty": 1, "reason": "fixed it before", "evidence_jobs": _ids(user, "DK-CTR-24V", "FIXED IT")}]
    if "VERIFIER FEEDBACK" not in user:   # the trap: a part that past visits replaced on a hunch
        carry.append({"part": "Compressor relay board (DK-RLY-B2)", "qty": 1, "reason": "was suspected before", "evidence_jobs": _ids(user, "DK-RLY-B2")})
    return {"carry": carry}


BRIEF = lambda user: {"headline": "Brief", "likely_cause": "x", "do_first": ["Replace the part named in the plan"], "avoid": ["The vetoed fix"],
                      "bring": ["Part from the plan"], "site_notes": ["Gate 4471"]}


def make_llm(**over):
    base = {"Diagnostician agent": diag_reply, "Parts agent": parts_reply, "field technician reads": BRIEF}
    base.update(over)
    return FakeLLM(base)


@pytest.fixture()
def store(tmp_path):
    s = Store()
    s.logged_path = tmp_path / "logged.json"   # never write into the repo
    s.logged = []
    return s


@pytest.fixture()
def shared(store, tmp_path):
    """The one shared memory bank, seeded exactly as the app seeds Hindsight (but the local keyword backend)."""
    mem = LocalMemory(tmp_path / "shared.json")
    mem.retain_many(records.build_all(store))
    return mem
