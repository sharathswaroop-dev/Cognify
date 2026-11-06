"""SiteMemory API + web UI.

Run from the project root:
    uvicorn backend.app:app --reload --port 8000      (or: python backend/app.py)
Then open http://localhost:8000
"""
from __future__ import annotations

import json
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT.parent / ".env")
except ImportError:
    pass

from agent import Agent  # noqa: E402
from memory import build_memory  # noqa: E402

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sitememory")
DATA = ROOT / "data"
FRONTEND = ROOT.parent / "frontend"


def _load(name: str):
    return json.loads((DATA / name).read_text())


class Store:
    """Read-only reference data + the visits logged live during the demo."""

    def __init__(self) -> None:
        self.company = _load("company.json")
        self.sites = _load("sites.json")
        self.machines = _load("machines.json")
        self.techs = _load("technicians.json")
        self.history = _load("job_history.json")
        self.open_jobs = _load("open_jobs.json")
        self.logged_path = DATA / "logged_visits.json"
        self.logged = json.loads(self.logged_path.read_text()) if self.logged_path.exists() else []
        self._m = {m["id"]: m for m in self.machines}
        self._s = {s["id"]: s for s in self.sites}
        self._t = {t["id"]: t for t in self.techs}

    def machine(self, mid):
        if mid not in self._m:
            raise HTTPException(404, f"Unknown machine {mid}")
        return self._m[mid]

    def site(self, sid):
        if sid not in self._s:
            raise HTTPException(404, f"Unknown site {sid}")
        return self._s[sid]

    def tech(self, tid):
        if tid not in self._t:
            raise HTTPException(404, f"Unknown technician {tid}")
        return self._t[tid]

    def job(self, jid):
        for j in self.open_jobs:
            if j["job_id"] == jid:
                return j
        raise HTTPException(404, f"Unknown job {jid}")

    def all_visits(self):
        return sorted(self.history + self.logged, key=lambda v: v["date"])

    def add_logged(self, visit):
        self.logged.append(visit)
        self.logged_path.write_text(json.dumps(self.logged, indent=1, ensure_ascii=False))

    def clear_logged(self):
        self.logged = []
        if self.logged_path.exists():
            self.logged_path.unlink()


store = Store()
memory = build_memory()
agent = Agent(memory, store)
state_path = DATA / "state.json"


def _state() -> dict:
    return json.loads(state_path.read_text()) if state_path.exists() else {}


def _set_state(**kw) -> None:
    s = _state()
    s.update(kw)
    state_path.write_text(json.dumps(s))


# Seed automatically on first run so the demo works out of the box.
if memory.name == "local" and memory.count() == 0:
    n = agent.seed()
    _set_state(seeded_local=n)
    log.info("seeded local memory with %d records", n)
elif memory.name == "hindsight" and not _state().get(f"seeded_hindsight_{memory.bank_id}"):
    try:
        n = agent.seed()
        _set_state(**{f"seeded_hindsight_{memory.bank_id}": n, "seeded_hindsight": n})
        log.info("sent %d records to Hindsight bank %s (processed in background)", n, memory.bank_id)
    except Exception as exc:
        log.error("Could not seed Hindsight (check HINDSIGHT_API_KEY / URL): %s", exc)

app = FastAPI(title="SiteMemory", version="0.1.0")


# ------------------------------------------------------------------ models
class Action(BaseModel):
    action: str = Field(min_length=2, max_length=300)
    result: Literal["worked", "failed", "partial"]
    detail: str = Field("", max_length=500)


class VisitLog(BaseModel):
    actions: list[Action] = Field(min_length=1, max_length=8)
    outcome: Literal["resolved", "revisit_needed"]
    root_cause: str = Field("", max_length=500)
    parts_used: list[str] = Field(default_factory=list, max_length=10)
    notes: str = Field("", max_length=800)
    technician_id: str | None = None


class BriefingRequest(BaseModel):
    job_id: str
    use_memory: bool = True


# ------------------------------------------------------------------ routes
@app.get("/api/status")
def status():
    s = _state()
    return {"memory_backend": memory.name, "memory_items": memory.count(), "llm": agent.llm.available,
            "llm_model": agent.llm.model if agent.llm.available else None,
            "bank_id": getattr(memory, "bank_id", None), "seeded": bool(s.get("seeded_hindsight") or s.get("seeded_local")),
            "company": store.company}


@app.get("/api/reference")
def reference():
    return {"sites": store.sites, "machines": store.machines, "technicians": store.techs}


@app.get("/api/jobs/open")
def open_jobs():
    out = []
    for j in store.open_jobs:
        m = store.machine(j["machine_id"])
        out.append({**j, "machine": m, "site": store.site(m["site_id"]), "technician": store.tech(j["technician_id"])})
    return out


@app.get("/api/machines/{machine_id}/history")
def machine_history(machine_id: str):
    store.machine(machine_id)
    visits = [v for v in store.all_visits() if v["machine_id"] == machine_id]
    return [{**v, "technician": store.tech(v["technician_id"])["name"]} for v in reversed(visits)]


@app.post("/api/briefing")
def briefing(req: BriefingRequest):
    job = store.job(req.job_id)
    return agent.briefing(job, req.use_memory)


@app.post("/api/jobs/{job_id}/log")
def log_visit(job_id: str, body: VisitLog):
    job = store.job(job_id)
    prior = [v for v in store.logged if v.get("incident_id") == f"I-{job_id}"]
    visit = {
        "job_id": f"{job_id}-V{len(prior) + 1}",
        "incident_id": f"I-{job_id}",
        "visit_no": len(prior) + 1,
        "date": date.today().isoformat(),
        "technician_id": body.technician_id or job["technician_id"],
        "machine_id": job["machine_id"],
        "site_id": job["site_id"],
        "symptom": job["symptom"],
        "actions": [a.model_dump() for a in body.actions],
        "root_cause": body.root_cause,
        "fix": next((a.action for a in body.actions if a.result == "worked"), ""),
        "parts_used": body.parts_used,
        "outcome": body.outcome,
        "recommendation": "",
        "notes": body.notes,
        "live": True,
    }
    store.tech(visit["technician_id"])
    try:
        rec = agent.retain_visit(visit)
    except Exception as exc:
        log.exception("retain failed")
        raise HTTPException(502, f"Could not save to memory: {exc}") from exc
    store.add_logged(visit)
    return {"saved": True, "visit": visit, "memory_text": rec["text"], "tags": rec["tags"],
            "memory_backend": memory.name}


@app.post("/api/seed")
def seed():
    n = agent.seed()
    _set_state(**{f"seeded_{memory.name}": n})
    note = ("Hindsight is extracting facts in the background; recall improves over the next 1-3 minutes."
            if memory.name == "hindsight" else "Local memory seeded.")
    return {"seeded": n, "memory_backend": memory.name, "note": note}


@app.post("/api/reset-demo")
def reset_demo():
    """Remove live-logged visits. In local mode also rebuilds memory from history."""
    store.clear_logged()
    if memory.name == "local":
        memory.reset()
        n = agent.seed()
        return {"reset": True, "reseeded": n}
    return {"reset": True, "note": "Logged visits cleared from the app. Hindsight memories are kept (that is the point)."}


def _month_range(first: str, last: str) -> list[str]:
    y, m = int(first[:4]), int(first[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


@app.get("/api/stats")
def stats():
    visits = store.all_visits()
    incidents = defaultdict(list)
    for v in visits:
        incidents[v["incident_id"]].append(v)
    total = len(incidents)
    first_time = sum(1 for vs in incidents.values() if len(vs) == 1 and vs[0]["outcome"] == "resolved")
    wasted = Counter()
    for v in visits:
        for a in v.get("actions", []):
            if a["result"] == "failed":
                wasted[a["action"]] += 1
    by_month = Counter(v["date"][:7] for v in visits)
    revisit_by_month = Counter(v["date"][:7] for v in visits if v["outcome"] == "revisit_needed")
    repeat_machines = Counter(v["machine_id"] for v in visits if v["visit_no"] == 1)
    top_machines = [{"machine": store.machine(mid), "site": store.site(store.machine(mid)["site_id"])["name"], "incidents": n}
                    for mid, n in repeat_machines.most_common(5)]
    return {
        "visits": len(visits), "incidents": total, "first_time_fix_rate": round(first_time / total, 3) if total else 0,
        "repeat_visits": sum(1 for v in visits if v["visit_no"] > 1),
        "months": [{"month": k, "visits": by_month.get(k, 0), "revisit_needed": revisit_by_month.get(k, 0)}
                   for k in _month_range(min(by_month), max(by_month))] if by_month else [],
        "most_wasted_attempts": [{"action": k, "times": n} for k, n in wasted.most_common(5)],
        "top_machines": top_machines,
        "memory_items": memory.count(), "memory_backend": memory.name,
    }


# ------------------------------------------------------------------ frontend
@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
