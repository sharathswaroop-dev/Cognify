"""SiteMemory API + web UI.

Run from the project root:   python backend/app.py      then open http://localhost:8000
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT.parent / ".env")
except ImportError:
    pass

import beliefs as beliefs_mod  # noqa: E402
import evidence as ev  # noqa: E402
import records  # noqa: E402
import simulate  # noqa: E402
import voice  # noqa: E402
from llm import LLM  # noqa: E402
from memory import FallbackMemory, LocalMemory, build_memory  # noqa: E402
from mesh.runner import ControlRoom  # noqa: E402
from store import DATA, NotFound, Store, UnknownMachine  # noqa: E402
from traced import TracedMemory  # noqa: E402
from watchlist import watchlist  # noqa: E402

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sitememory")
FRONTEND = ROOT.parent / "frontend"
EVAL_PATH = DATA / "eval_results.json"

store = Store()
llm = LLM()
_primary = build_memory("shared", bank_id=os.getenv("HINDSIGHT_BANK_ID", "sitememory-v3-coolcare"), mission=records.MISSION)
# Hindsight when it works; the local keyword memory (kept in step) when it does not, with the reason shown in the UI
memory = FallbackMemory(_primary, LocalMemory(DATA / "local_memory_shared.json")) if _primary.name == "hindsight" else _primary
state_path = DATA / "state.json"


def _state() -> dict:
    return json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}


def _set_state(**kw) -> None:
    s = _state()
    s.update(kw)
    state_path.write_text(json.dumps(s), encoding="utf-8")


def seed() -> int:
    recs = records.build_all(store, visits=store.history)
    memory.retain_many(recs)
    return len(recs)


_key = f"seeded_{getattr(memory, 'bank_id', 'local')}"
if isinstance(memory, FallbackMemory) and memory.secondary.count() == 0:
    memory.secondary.retain_many(records.build_all(store, visits=store.history))   # the local copy is cheap and always kept
if not _state().get(_key) and (memory.name == "hindsight" or memory.count() == 0):
    try:
        _n = seed()
        if not getattr(memory, "degraded", False):
            _set_state(**{_key: _n})
        log.info("seeded the shared bank %s with %d records (Hindsight processes them in the background)", getattr(memory, "bank_id", "local"), _n)
    except Exception as exc:
        log.error("Could not seed memory: %s", exc)

beliefs_engine = beliefs_mod.BeliefEngine(store, memory, _state, _set_state)
try:
    _b = beliefs_engine.sync()
    if _b:
        log.info("retained belief corrections to the shared bank: %s", _b)
except Exception as exc:
    log.error("Could not retain belief corrections: %s", exc)

room = ControlRoom(store, memory, llm)
app = FastAPI(title="SiteMemory", version="1.0.0")


@app.exception_handler(UnknownMachine)
def _unknown_machine(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(NotFound)
def _not_found(request, exc):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


# ------------------------------------------------------------------ status + reference
@app.get("/api/status")
def status():
    s = room.status()
    return {**s, "memory_degraded": bool(getattr(memory, "degraded", False)), "memory_degraded_reason": getattr(memory, "reason", ""),
            "memory_items": memory.count(), "llm": llm.available, "llm_model": llm.model if llm.available else None, "company": store.company,
            "seeded": bool(_state().get(_key)), "machines": len(store.machines), "sites": len(store.sites), "visits": len(store.all_visits())}


@app.get("/api/scenarios")
def scenarios():
    out = []
    for s in store.scenarios:
        m = store.machine(s["machine_id"])
        out.append({**{k: v for k, v in s.items() if k != "truth"}, "machine": m, "site": store.site(m["site_id"]), "holdout": bool(m.get("holdout"))})
    return out


@app.get("/api/reference")
def reference():
    return {"sites": store.sites, "machines": store.machines, "technicians": store.techs, "params": simulate.PARAMS}


# ------------------------------------------------------------------ the control room
class RunReq(BaseModel):
    scenario_id: str


@app.post("/api/runs")
def start_run(req: RunReq):
    run = room.start(req.scenario_id)
    return {"run_id": run.id, "alarm": run.alarm}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = room.get(run_id)
    if not run:
        raise HTTPException(404, "Unknown run")
    return run.public()


@app.get("/api/runs/{run_id}/stream")
def stream_run(run_id: str):
    run = room.get(run_id)
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
                batch, status_ = run.events[i:], run.status
            for e in batch:
                yield f"data: {json.dumps(e)}\n\n"
                i += 1
            if status_ != "running" and i >= len(run.events):
                yield f"event: end\ndata: {json.dumps({'status': status_, 'plans': run.public()['plans']})}\n\n"
                return
            if not batch:
                yield ": keepalive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ technician: log a visit (typed or by voice), retained to the shared bank
class Action(BaseModel):
    action: str = Field(min_length=2, max_length=300)
    result: Literal["worked", "failed", "partial"]
    detail: str = Field("", max_length=500)


class VisitLog(BaseModel):
    actions: list[Action] = Field(min_length=1, max_length=8)
    outcome: Literal["resolved", "revisit_needed"]
    root_cause: str = Field("", max_length=500)
    suspected_cause: str = Field("", max_length=300)
    parts_used: list[str] = Field(default_factory=list, max_length=10)
    notes: str = Field("", max_length=800)
    technician_id: str | None = None
    machine_id: str | None = None
    symptom: str | None = None


def _log_visit(job: dict, body: VisitLog) -> dict:
    m = store.machine(body.machine_id or job["machine_id"])           # validated: an invented machine id never reaches memory
    prior = [v for v in store.logged if v.get("incident_id") == f"I-{job['job_id']}"]
    visit = {"job_id": f"{job['job_id']}-V{len(prior) + 1}", "incident_id": f"I-{job['job_id']}", "visit_no": len(prior) + 1, "date": ev.NOW,
             "technician_id": body.technician_id or job.get("technician_id") or "T-06", "machine_id": m["id"], "site_id": m["site_id"],
             "fault_class": m.get("fault_class", ""), "symptom": body.symptom or job["symptom"], "suspected_cause": body.suspected_cause,
             "actions": [a.model_dump() for a in body.actions], "root_cause": body.root_cause,
             "fix": next((a.action for a in body.actions if a.result == "worked"), ""), "parts_used": body.parts_used, "parts_missing": [],
             "outcome": body.outcome, "evidence": "", "wrong_diagnosis": False, "recommendation": "", "notes": body.notes, "live": True}
    tech = store.tech(visit["technician_id"])
    ops: list[dict] = []
    traced = TracedMemory(memory, ops.append, store, who="technician")
    rec = records.validate(records.visit_record(visit, m, store.site(m["site_id"]), tech), store)
    try:
        traced.retain(rec["text"], rec["tags"], rec["date"], rec["doc_id"], rec["meta"])
    except Exception as exc:
        log.exception("retain failed")
        raise HTTPException(502, f"Could not save to memory: {exc}") from exc
    store.add_logged(visit)
    try:
        beliefs_engine.sync()
    except Exception:
        log.exception("belief sync failed")
    return {"saved": True, "visit": visit, "memory_text": rec["text"], "tags": rec["tags"], "memory_backend": memory.name, "ops": ops}


@app.post("/api/jobs/{job_id}/log")
def log_visit(job_id: str, body: VisitLog):
    return _log_visit(store.job(job_id), body)


@app.get("/api/jobs/open")
def open_jobs():
    out = []
    for j in store.open_jobs:
        m = store.machine(j["machine_id"])
        sc = next((s["id"] for s in store.scenarios if s.get("job_id") == j["job_id"]), None)
        out.append({**j, "machine": m, "site": store.site(m["site_id"]), "technician": store.tech(j["technician_id"]), "scenario_id": sc})
    return out


@app.post("/api/runs/{run_id}/sample-log")
def sample_log(run_id: str):
    """The technician follows the WITH-memory plan; what happened (per the simulation) is logged and retained. Demonstrates retain."""
    run = room.get(run_id)
    if not run or "with" not in run.plans:
        raise HTTPException(404, "Run not finished")
    plan, truth = run.plans["with"], run.scenario["truth"]
    fix, ok = plan["diagnosis"]["causes"][0], plan["consequence"]["outcome"] != "return visit needed"
    body = VisitLog(actions=[Action(action=fix["fix"], result="worked" if ok else "failed",
                                    detail="Followed the briefing." if ok else "The plan did not match what was found on site.")],
                    outcome="resolved" if ok else "revisit_needed", root_cause=truth["cause"] if ok else "", suspected_cause=fix["cause"],
                    parts_used=[p["part"] for p in plan["parts"]["carry"]][:3] if ok else [],
                    notes="Logged from the control-room demo (simulated outcome).", machine_id=run.alarm["machine_id"], symptom=run.scenario["description"])
    job = next((j for j in store.open_jobs if j["job_id"] == run.scenario.get("job_id")),
               {"job_id": f"AL-{run.alarm['id']}", "machine_id": run.alarm["machine_id"], "symptom": run.scenario["description"], "technician_id": "T-06"})
    return _log_visit(job, body)


# ------------------------------------------------------------------ voice
@app.post("/api/voice/report")
async def voice_report(job_id: str = Form(...), audio: UploadFile = File(...)):
    job = store.job(job_id)
    data = await audio.read(voice.MAX_BYTES + 1)
    try:
        tr = await run_in_threadpool(voice.transcribe, llm.client, data, audio.filename or "report.webm")
    except voice.VoiceError as exc:
        raise HTTPException(422, {"code": exc.code, "message": exc.message})
    structured, warnings = await run_in_threadpool(voice.extract_visit, llm, tr["text"], job)
    return {"transcript": tr["text"], "duration": tr["duration"], "structured": structured, "warnings": warnings}


@app.post("/api/voice/extract")
async def voice_extract(body: dict):
    text = str(body.get("transcript", "")).strip()
    if len(text.split()) < 3:
        raise HTTPException(422, {"code": "empty", "message": "Write at least a short sentence about the visit."})
    job = store.job(body["job_id"]) if body.get("job_id") else None
    structured, warnings = await run_in_threadpool(voice.extract_visit, llm, text, job)
    return {"transcript": text, "structured": structured, "warnings": warnings}


# ------------------------------------------------------------------ dashboard
@app.get("/api/beliefs")
def current_beliefs():
    return beliefs_engine.current()


@app.get("/api/families")
def families():
    return sorted({m["model_family"] for m in store.machines})


@app.get("/api/fix-outcomes")
def fix_outcomes(family: str):
    return {"family": family, "fixes": beliefs_mod.timeline(store.all_visits(), store.machine, family)[:6]}


@app.get("/api/watchlist")
def get_watchlist():
    return watchlist(store)


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
    inc = defaultdict(list)
    for v in visits:
        inc[v["incident_id"]].append(v)
    first_time = sum(1 for vs in inc.values() if len(vs) == 1 and vs[0]["outcome"] == "resolved")
    wasted = Counter(a["action"] for v in visits for a in v.get("actions", []) if a["result"] == "failed")
    by_month = Counter(v["date"][:7] for v in visits)
    revisit = Counter(v["date"][:7] for v in visits if v["outcome"] == "revisit_needed")
    lv = ev.visit_levels(visits)
    return {"visits": len(visits), "incidents": len(inc), "first_time_fix_rate": round(first_time / len(inc), 3) if inc else 0,
            "repeat_visits": sum(1 for v in visits if v["visit_no"] > 1),
            "wrong_diagnoses": sum(1 for v in visits if v.get("wrong_diagnosis")), "parts_shortages": sum(1 for v in visits if v.get("parts_missing")),
            "came_back_in_30_days": sum(1 for v in visits if lv.get(v["job_id"], {}).get("recurred")),
            "months": [{"month": k, "visits": by_month.get(k, 0), "revisit_needed": revisit.get(k, 0)} for k in _month_range(min(by_month), max(by_month))],
            "most_wasted_attempts": [{"action": k, "times": n} for k, n in wasted.most_common(5)],
            "memory_items": memory.count(), "memory_backend": memory.name, "bank": getattr(memory, "bank_id", "local"),
            "machines": len(store.machines), "holdout_machines": len(store.holdout_ids())}


@app.get("/api/machines/{machine_id}/history")
def machine_history(machine_id: str):
    store.machine(machine_id)
    lv = ev.visit_levels(store.all_visits())
    return [{**v, "technician": store.tech(v["technician_id"])["name"], "level": lv.get(v["job_id"], {}).get("level", "suspected")}
            for v in reversed([x for x in store.all_visits() if x["machine_id"] == machine_id])]


# ------------------------------------------------------------------ evaluation
@app.post("/api/eval/run")
def eval_run(limit: int | None = None):
    import evaluation
    if evaluation.PROGRESS.state == "running":
        raise HTTPException(409, "An evaluation is already running")
    evaluation.PROGRESS.set(state="running", done=0, total=0, message="Starting")
    threading.Thread(target=evaluation.run_in_process, args=(store, llm, limit), daemon=True, name="eval").start()
    return evaluation.PROGRESS.public()


@app.get("/api/eval/status")
def eval_status():
    import evaluation
    return evaluation.PROGRESS.public()


@app.get("/api/eval/results")
def eval_results():
    if not EVAL_PATH.exists():
        return {"available": False}
    return {"available": True, **json.loads(EVAL_PATH.read_text(encoding="utf-8"))}


@app.post("/api/reset-demo")
def reset_demo():
    store.clear_logged()
    return {"reset": True, "note": "Visits logged during the demo are cleared from the app. Hindsight keeps its memories (that is the point)."}


# ------------------------------------------------------------------ frontend
@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
