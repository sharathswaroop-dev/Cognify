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
from fastapi.responses import FileResponse, StreamingResponse
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


from store import Store  # noqa: E402


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

# ------------------------------------------------------------------ multi-agent mesh (one Hindsight bank per agent)
from memory import build_memory as _build  # noqa: E402
from mesh.records import MISSIONS  # noqa: E402
from mesh.runner import AlarmFeed, Mesh  # noqa: E402

_memories = {"field": memory, **{r: _build(r, mission=MISSIONS[r]) for r in MISSIONS}}
mesh = Mesh(store, agent, _memories, agent.llm)
feed = AlarmFeed(mesh, store.live_alarms)
try:
    _seeded = mesh.seed_banks(_state, _set_state)
    if _seeded:
        log.info("seeded agent banks: %s", _seeded)
except Exception as exc:
    log.error("Could not seed agent banks: %s", exc)

app = FastAPI(title="SiteMemory", version="0.2.0")


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
    learned = mesh.record_visit(visit)  # the other agents learn their slice of this visit
    return {"saved": True, "visit": visit, "memory_text": rec["text"], "tags": rec["tags"],
            "memory_backend": memory.name, "agents_updated": ["field"] + list(learned)}


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


# ------------------------------------------------------------------ mesh + alarm feed
@app.get("/api/mesh/status")
def mesh_status():
    return mesh.status()


@app.get("/api/alarms")
def alarms():
    hist = sorted(store.alarms, key=lambda a: a["ts"], reverse=True)[:30]
    return {"live": store.live_alarms, "history": hist, "feed": feed.state()}


@app.post("/api/alarms/{alarm_id}/fire")
def fire_alarm(alarm_id: str):
    try:
        run = feed.fire(alarm_id)
    except KeyError:
        raise HTTPException(404, f"Unknown live alarm {alarm_id}")
    return {"run_id": run.id, "alarm": run.alarm}


@app.post("/api/alarm-feed/start")
def feed_start(interval: float = 45.0):
    feed.start(max(5.0, interval))
    return feed.state()


@app.post("/api/alarm-feed/stop")
def feed_stop():
    feed.stop()
    return feed.state()


@app.get("/api/alarm-feed")
def feed_state():
    return feed.state()


@app.get("/api/mesh/runs/{run_id}")
def mesh_run(run_id: str):
    run = mesh.get(run_id)
    if not run:
        raise HTTPException(404, "Unknown run")
    return run.public()


@app.get("/api/mesh/runs/{run_id}/stream")
def mesh_stream(run_id: str):
    run = mesh.get(run_id)
    if not run:
        raise HTTPException(404, "Unknown run")

    def gen():
        i = 0
        while True:
            with run.cond:
                while i >= len(run.events) and run.status == "running":
                    run.cond.wait(timeout=10)
                    if i >= len(run.events) and run.status == "running":
                        break
                batch, status = run.events[i:], run.status
            for ev in batch:
                yield f"data: {json.dumps(ev)}\n\n"
                i += 1
            if status != "running" and i >= len(run.events):
                yield f"event: end\ndata: {json.dumps({'status': status, 'result': run.result})}\n\n"
                return
            if not batch:
                yield ": keepalive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ replay evaluation
import threading  # noqa: E402
import time  # noqa: E402

from evaluation import PROGRESS, Evaluator, render_markdown  # noqa: E402
from memory import bank_prefix  # noqa: E402

EVAL_PATH = DATA / "eval_results.json"
EVAL_MD = ROOT.parent / "docs" / "EVALUATION.md"


def _run_eval(limit: int | None) -> None:
    try:
        mem = _build("eval", bank_id=f"{bank_prefix()}-eval-{int(time.time())}")
        if mem.name == "local":
            mem.reset()
        ea = Agent(mem, store)
        ea.llm, ea.belief_fn = agent.llm, agent.belief_fn
        ev = Evaluator(store, ea, agent.llm, mem, EVAL_PATH, site_records=[ea.site_record(x) for x in store.sites],
                       visit_record=ea.visit_record)
        ev.run(limit)
        EVAL_MD.parent.mkdir(exist_ok=True)
        EVAL_MD.write_text(render_markdown(json.loads(EVAL_PATH.read_text(encoding="utf-8"))), encoding="utf-8")
    except Exception as exc:
        log.exception("evaluation failed")
        PROGRESS.set(state="error", message=str(exc)[:300])


@app.post("/api/eval/run")
def eval_run(limit: int | None = None):
    if PROGRESS.state == "running":
        raise HTTPException(409, "An evaluation is already running")
    PROGRESS.set(state="running", done=0, total=0, message="Starting")
    threading.Thread(target=_run_eval, args=(limit,), daemon=True, name="eval").start()
    return PROGRESS.public()


@app.get("/api/eval/status")
def eval_status():
    return PROGRESS.public()


@app.get("/api/eval/results")
def eval_results():
    if not EVAL_PATH.exists():
        return {"available": False}
    d = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    return {"available": True, **d}


# ------------------------------------------------------------------ frontend
@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
