"""Cognify API + web UI.

Run from the project root:   python backend/app.py      then open http://localhost:8000
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import threading
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
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
import chatintent  # noqa: E402
import converse  # noqa: E402
import dispatch as dispatch_mod  # noqa: E402
import documents  # noqa: E402
import knowledge  # noqa: E402
import learning  # noqa: E402
import provenance  # noqa: E402
import push as push_mod  # noqa: E402
import records  # noqa: E402
import session as session_mod  # noqa: E402
import simulate  # noqa: E402
import voice  # noqa: E402
import workspaces  # noqa: E402
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
state_path = DATA / "state.json"
_BASE_BANK = os.getenv("HINDSIGHT_BANK_ID", "sitememory-v3-coolcare")
_bank = (json.loads(state_path.read_text(encoding="utf-8")).get("bank_id") if state_path.exists() else None) or _BASE_BANK   # a reset moves to a fresh bank
_primary = build_memory("shared", bank_id=_bank, mission=records.MISSION)
# Hindsight when it works; the local keyword memory (kept in step) when it does not, with the reason shown in the UI
memory = FallbackMemory(_primary, LocalMemory(DATA / "local_memory_shared.json")) if _primary.name == "hindsight" else _primary


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

_demo_ws = workspaces.ensure_demo(store.company["name"], getattr(memory, "bank_id", "local"))
_ws_mem: dict = {}


def ws_memory(ws: dict):
    """The memory bank that belongs to one company. The demo company uses the app's own bank; every other company has a bank of its own,
    so knowledge never crosses from one company to another."""
    if ws.get("demo"):
        return memory
    if ws["id"] not in _ws_mem:
        local = LocalMemory(workspaces.local_memory_path(ws["id"]))
        prim = build_memory("shared", bank_id=ws["bank"], mission=records.MISSION)
        _ws_mem[ws["id"]] = FallbackMemory(prim, local) if prim.name == "hindsight" else local
    return _ws_mem[ws["id"]]


def current(authorization: str | None = Header(None)) -> dict:
    """Who is asking: the workspace and email behind the bearer token."""
    tok = authorization.split(" ", 1)[1] if authorization and authorization.lower().startswith("bearer ") else None
    try:
        ws, email = workspaces.verify(tok)
    except workspaces.AuthError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return {"ws": ws, "email": email, "memory": ws_memory(ws), "name": email.split("@", 1)[0].replace(".", " ").title(),
            "admin": workspaces.is_admin(ws, email), "guest": email == workspaces.GUEST_EMAIL}


def admin_only(ctx: dict = Depends(current)) -> dict:
    if not ctx["admin"]:
        raise HTTPException(403, "Only the workspace admin (the first person who joined) can do that.")
    return ctx


beliefs_engine = beliefs_mod.BeliefEngine(store, memory, _state, _set_state)
dispatch = dispatch_mod.Dispatch(store, DATA / "dispatch_state.json", watch=watchlist(store, limit=80))
pusher = push_mod.Pusher()
dispatch.push_hook = lambda key, title, body, data: pusher.send(dispatch.push_tokens(key), title, body, data, on_dead=lambda t: dispatch.unregister_push(key, t))
try:
    _b = beliefs_engine.sync()
    if _b:
        log.info("retained belief corrections to the shared bank: %s", _b)
except Exception as exc:
    log.error("Could not retain belief corrections: %s", exc)

room = ControlRoom(store, memory, llm)
app = FastAPI(title="Cognify", version="1.0.0")


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
            "memory_items": memory.count(), "llm": llm.available, "llm_model": llm.model if llm.available else None, "llm_models": list(getattr(llm, "models", []) or []), "llm_used": dict(getattr(llm, "used", {}) or {}), "company": store.company,
            "seeded": bool(_state().get(_key)), "machines": len(store.machines), "sites": len(store.sites), "visits": len(store.all_visits())}


@app.get("/api/scenarios")
def scenarios():
    out = []
    for s in store.scenarios:
        m = store.machine(s["machine_id"])
        out.append({**{k: v for k, v in s.items() if k != "truth"}, "machine": m, "site": store.site(m["site_id"]), "holdout": bool(m.get("holdout"))})
    return out


@app.get("/api/learning")
def learning_replay(family: str = "Daikin VRV IV"):
    """The learning replay: incidents in date order, each answered from only the records dated before it (instant, no model, no key needed)."""
    if family not in learning.families(store):
        raise HTTPException(404, "Unknown model family")
    return learning.replay(store, family)


@app.get("/api/learning/families")
def learning_families():
    return learning.families(store)


@app.get("/api/reference")
def reference():
    return {"sites": store.sites, "machines": store.machines, "technicians": store.techs, "params": simulate.PARAMS}


# ------------------------------------------------------------------ the control room
class RunReq(BaseModel):
    scenario_id: str
    chaos: Literal["none", "band", "memory", "llm"] = "none"        # a drill: switch one dependency off for this run
    paths: Literal["both", "with", "without"] = "both"


@app.post("/api/runs")
def start_run(req: RunReq, ctx: dict = Depends(current)):
    run = room.start(req.scenario_id, chaos=req.chaos, paths={"both": ("without", "with"), "with": ("with",), "without": ("without",)}[req.paths])
    return {"run_id": run.id, "alarm": run.alarm, "chaos": run.chaos}


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
def log_visit(job_id: str, body: VisitLog, ctx: dict = Depends(current)):
    out = _log_visit(store.job(job_id), body)
    dispatch.on_visit_logged(job_id, body.outcome == "resolved")
    return out


@app.get("/api/jobs/open")
def open_jobs(technician: str | None = None):
    out = []
    def _live(j):          # a dispatched job stays in the list only while its request is still open
        try:
            return dispatch.get(j["report_id"])["status"] in ("en_route", "on_site", "working")
        except Exception:
            return False
    jobs = list(store.open_jobs) + ([j for j in store.dyn_jobs if j.get("technician_id") == technician and _live(j)] if technician else [])
    for j in jobs:
        m = store.machine(j["machine_id"])
        sc = next((s["id"] for s in store.scenarios + store.dyn_scenarios if s.get("job_id") == j["job_id"]), None)
        out.append({**j, "machine": m, "site": store.site(m["site_id"]), "technician": store.tech(j["technician_id"]), "scenario_id": sc})
    return out


@app.post("/api/runs/{run_id}/sample-log")
def sample_log(run_id: str, fail: bool = False, ctx: dict = Depends(current)):
    """The technician follows the WITH-memory plan; what happened (per the simulation) is logged and retained. Demonstrates retain."""
    run = room.get(run_id)
    if not run or "with" not in run.plans:
        raise HTTPException(404, "Run not finished")
    plan, truth = run.plans["with"], run.scenario["truth"]
    fix, ok = plan["diagnosis"]["causes"][0], plan["consequence"]["outcome"] != "return visit needed" and not fail   # fail=true: the drill where the recommended fix does not hold
    body = VisitLog(actions=[Action(action=fix["fix"], result="worked" if ok else "failed",
                                    detail="Followed the briefing." if ok else "The plan did not match what was found on site.")],
                    outcome="resolved" if ok else "revisit_needed", root_cause=truth["cause"] if ok else "", suspected_cause=fix["cause"],
                    parts_used=[p["part"] for p in plan["parts"]["carry"]][:3] if ok else [],
                    notes="Logged from the live demo (simulated outcome)." + (" The recommended fix did not hold on site." if fail else ""), machine_id=run.alarm["machine_id"], symptom=run.scenario["description"])
    job = next((j for j in store.open_jobs if j["job_id"] == run.scenario.get("job_id")),
               {"job_id": f"AL-{run.alarm['id']}", "machine_id": run.alarm["machine_id"], "symptom": run.scenario["description"], "technician_id": "T-06"})
    return _log_visit(job, body)


# ------------------------------------------------------------------ the company's knowledge: ask it, and add to it
class AskReq(BaseModel):
    question: str = Field(min_length=3, max_length=400)


def _ask(mem, q: str, deep: bool = False) -> dict:
    """A new hire asks what the company already knows. Hindsight's reflect writes the answer from the stored visits and notes, and the
    records it drew on are returned so the answer can be checked. Nothing here needs a language model of ours."""
    q = q.strip()
    try:
        hits = mem.recall(q, [], 8)
    except Exception as exc:
        raise HTTPException(502, f"The memory could not be searched: {exc}") from exc
    answer = None
    try:
        answer = mem.reflect(q, [], budget="high" if deep else "low")       # deep: Hindsight's larger reflect budget
    except Exception:
        log.exception("reflect failed for ask")
    sources = [{"ref": m.ref(), "date": m.date, "text": m.text[:280], "tags": m.tags[:6], **provenance.classify(m.tags)} for m in hits]
    if not hits and not answer:
        return {"answer": "Nothing in the company memory covers that yet. If you know the answer, tell me and I will keep it for the next person.", "sources": [], "found": False,
                "basis": provenance.basis([]), "backend": mem.name}
    if answer and hits and _NEGATIVE.search(answer[:240]):          # Hindsight is still ingesting and says "nothing", yet records were retrieved: answer from those records instead
        answer = None
    if not answer and hits and llm.available:
        ctx_txt = "\n".join(f"[{i + 1}] {m.text[:420]}" for i, m in enumerate(hits[:6]))
        answer = llm.text_chat(GROUND_SYS, f"Question: {q}\n\nRecords:\n{ctx_txt}", max_tokens=420)
        if answer and answer.strip().upper().startswith("NO_MATCH"):      # the records are not about this question: treat as nothing found
            answer, hits, sources = None, [], []
            return {"answer": "Nothing in the company memory covers that yet. If you know the answer, tell me and I will keep it for the next person.", "sources": [], "found": False,
                    "basis": provenance.basis([]), "backend": mem.name}
    if not answer:
        answer = "Here is what the records say: " + " ".join("(" + str(i + 1) + ") " + m.text[:200] for i, m in enumerate(hits[:3]))
    fixes = [s for s in sources if s["tier"] == "correction"]
    if fixes:                              # a correction someone made is shown ahead of the answer it corrects
        answer = "Heads up, a colleague corrected this: " + fixes[0]["text"][:260] + "\n\n" + answer
    return {"answer": answer, "sources": sources, "found": True, "basis": provenance.basis(sources), "backend": mem.name}


@app.post("/api/ask")
def ask_the_memory(req: AskReq, ctx: dict = Depends(current)):
    return _ask(ctx["memory"], req.question)


class Note(BaseModel):
    author: str = Field(min_length=2, max_length=60)
    role: str = Field("", max_length=60)
    years: int | None = Field(None, ge=0, le=60)
    machine_id: str | None = None
    site_id: str | None = None
    text: str = Field(min_length=15, max_length=2000)


def _save_note(ctx: dict, n: Note) -> dict:
    """Someone who knows (a retiring technician, a senior) writes down what they know. It is retained with their name and the machine or site it is about."""
    mem, demo = ctx["memory"], bool(ctx["ws"].get("demo"))
    m = store.machine(n.machine_id) if (n.machine_id and demo) else None          # the machine list belongs to the demo company only
    sid = (m or {}).get("site_id") or (n.site_id if demo else None)
    site = store.site(sid) if sid else None
    doc_id = f"note-{int(time.time() * 1000)}"
    rec = records.validate(records.knowledge_record(n.author.strip(), n.role.strip(), n.years, n.text.strip(), m, site, doc_id, ev.NOW), store)
    try:
        mem.retain(rec["text"], rec["tags"], rec["date"], rec["doc_id"], rec["meta"])
    except Exception as exc:
        log.exception("retain of a note failed")
        raise HTTPException(502, f"Could not save to memory: {exc}") from exc
    if demo:
        store.add_note({"id": doc_id, "author": n.author.strip(), "role": n.role.strip(), "years": n.years, "machine_id": n.machine_id, "family": (m or {}).get("model_family"),
                        "site_id": sid, "text": n.text.strip(), "date": ev.NOW})
    return {"saved": True, "memory_text": rec["text"], "tags": rec["tags"], "memory_backend": mem.name}


@app.post("/api/knowledge")
def share_knowledge(n: Note, ctx: dict = Depends(current)):
    return _save_note(ctx, n)


class ChatReq(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    author: str = Field("", max_length=60)
    context: str | None = Field(None, max_length=400)      # the person's previous question, so a short follow-up makes sense
    deep: bool = False                                    # the "Thinking" option: a larger reflect for a more detailed answer
    machine_id: str | None = Field(None, max_length=12)   # the unit the technician is working on right now, so "what do I check first?" means that unit
    history: list[dict] = Field(default_factory=list, max_length=14)   # the turns so far ({"role": "user"|"assistant", "content", "kind"}), so the chat can follow a conversation


@app.post("/api/chat")
def chat(req: ChatReq, ctx: dict = Depends(current)):
    """One conversation box that talks like a colleague. Greetings, thanks, a vague "I have a problem", a correction and something worth remembering are each
    handled the way a person would; only a real question goes to the company memory (Hindsight reflect, with the records it used)."""
    msg = req.message.strip()
    author = req.author.strip() if len(req.author.strip()) >= 2 else ctx["name"]
    history = req.history or ([{"role": "user", "content": req.context, "kind": "answer"}] if req.context else [])
    if req.machine_id and store.has_machine(req.machine_id) and not converse.machine_in(msg) and not converse.history_machine(history):
        history = [{"role": "user", "content": f"I am working on {req.machine_id} right now.", "kind": "answer"}] + list(history)
    turn = converse.plan(msg, history)
    act, demo = turn["act"], bool(ctx["ws"].get("demo"))
    if act in ("greet", "thanks", "bye", "smalltalk", "about"):
        return {"kind": "chat", "answer": turn["reply"], "sources": [], "found": False, "backend": ctx["memory"].name}
    if act == "clarify":
        return {"kind": "clarify", "answer": turn["reply"], "chips": turn["chips"], "backend": ctx["memory"].name}
    if act == "correct_ask":
        return {"kind": "correct_ask", "answer": turn["reply"]}
    if act == "correct":
        mid = turn.get("machine") if (turn.get("machine") and demo and store.has_machine(turn["machine"])) else None
        about_q = turn.get("about") or "the previous answer"
        body = _retain_correction(ctx, about_q, turn["correction"], machine=mid)
        workspaces.add_feedback(ctx["ws"]["id"], {"date": ev.NOW, "who": ctx["email"], "question": about_q[:200], "rating": "down", "corrected": True, "refs": []})
        where = f" for {mid}" if mid else ""
        return {"kind": "corrected", "answer": f"Got it, thank you. I've saved that as a correction{where}, so the next answer on this will show it first.",
                "memory_text": body, "machine_id": mid, "backend": ctx["memory"].name}
    if act == "share" or chatintent.intent(msg) == "share":
        text = chatintent.strip_cue(msg)
        if len(text) < 15:
            return {"kind": "clarify", "answer": "Tell me a bit more so the next person can use it: what happened, on which machine, and what fixed it?", "chips": []}
        mid = chatintent.machine_in(text)
        if mid and not (demo and store.has_machine(mid)):
            mid = None
        saved = _save_note(ctx, Note(author=author, machine_id=mid, text=text))
        about = f" about {mid}" if mid else ""
        return {"kind": "saved", "answer": f"Thanks {author.split()[0]}. I've saved that{about} under your name, so the next person who asks will find it.", "memory_text": saved["memory_text"],
                "machine_id": mid, "backend": saved["memory_backend"]}
    if _GREET.match(msg) and len(msg.split()) <= 5:
        return {"kind": "chat", "answer": "Hello. Tell me what's happening with your equipment, or ask what your team has learned before.", "sources": [], "found": False, "backend": ctx["memory"].name}
    q = turn["query"]
    out = _ask(ctx["memory"], q[:400] if len(q) >= 3 else msg + "  ", req.deep)
    if not out["found"]:
        # Nothing in the memory. Say so, then give a clearly labelled general answer from the model rather than a dead end.
        g = llm.text_chat(GENERAL_SYS, msg)
        if g:
            out = {**out, "answer": "I found nothing about this in your company memory, so this is general guidance, not your organization's experience.\n\n" + g, "general": True}
    out = {**out, "answer": converse.humanize(out["answer"], llm)}
    mid = turn.get("machine") if (turn.get("machine") and demo and store.has_machine(turn["machine"])) else None
    out["answer"] += converse.follow_up(mid, bool(turn.get("ask_unit")), bool(out.get("found")))
    offer = None
    if mid and out.get("found"):
        sc = next((x["id"] for x in store.scenarios if x["machine_id"] == mid), None)
        offer = {"machine_id": mid, "scenario_id": sc}
    return {"kind": "answer", **out, "offer": offer}


_GREET = re.compile(r"^\s*(hi+|hello|hey|yo|howdy|thanks|thank you|thx|ok(ay)?|cool|bye|goodbye|good (morning|afternoon|evening|night)|how are you|how r u|how'?s it going|how do you do|what'?s up|sup|who are you|what are you|what can you do)\b", re.I)
_NEGATIVE = re.compile(r"(do(es)? not contain|no (relevant )?(information|record|data|history)|not possible to determine|could not find|nothing (in|about))", re.I)
GROUND_SYS = ("You answer a field-service question using ONLY the numbered company records given. Cite records as [1], [2]. "
              "Say what was tried and failed, and what worked, if the records say so. Reply with exactly NO_MATCH only if NONE of the records relates to the equipment or symptom asked about (or the message is just a greeting); if some relate, answer from them and say what is not known. "
              "Plain text only: no markdown, no tables. Under 140 words. Never add facts that are not in the records.")
GENERAL_SYS = ("You are a helpful assistant for a field-service company. Answer concisely and practically in plain text: no markdown, no tables, under 150 words. "
               "You have NO access to this company's records, so never claim to remember a past incident, and never invent machine ids, dates or people.")


class CompareReq(BaseModel):
    question: str = Field(min_length=3, max_length=400)


@app.post("/api/compare")
def compare(req: CompareReq, ctx: dict = Depends(current)):
    """The same question twice, from two real execution paths. OFF: the language model alone. ON: Hindsight recall + reflect over this company's memory,
    with the records it used. Nothing here is scripted; if a path fails the response says so instead of filling it in."""
    q = req.question.strip()
    t0 = time.time()
    off_txt = llm.text_chat(GENERAL_SYS, q)
    off = {"answer": off_txt, "label": "Normal AI response (no company memory)", "ms": int((time.time() - t0) * 1000),
           "error": None if off_txt else "No language model answered (key missing or rate limited)."}
    t1 = time.time()
    try:
        on = {**_ask(ctx["memory"], q), "label": "Answer with company memory", "error": None}
    except HTTPException as exc:
        on = {"answer": None, "sources": [], "found": False, "label": "Answer with company memory", "error": str(exc.detail)}
    on["ms"] = int((time.time() - t1) * 1000)
    on["operations"] = [{"op": "recall", "detail": f"{len(on.get('sources') or [])} records"}, {"op": "reflect", "detail": "answer written from those records" if on.get("found") else "nothing to reflect on"}]
    return {"question": q, "off": off, "on": on, "backend": ctx["memory"].name}


class Join(BaseModel):
    code: str = Field(min_length=3, max_length=60)
    email: str = Field(min_length=5, max_length=120)


class NewCompany(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    email: str = Field(min_length=5, max_length=120)


def _session(ws: dict, email: str) -> dict:
    return {"token": workspaces.token(ws["id"], email), "workspace": {"id": ws["id"], "name": ws["name"], "demo": bool(ws.get("demo")), "domain": ws.get("domain")}, "email": email,
            "admin": workspaces.is_admin(ws, email)}


@app.post("/api/workspace/join")
def workspace_join(j: Join):
    try:
        ws = workspaces.join(j.code, j.email)
    except workspaces.AuthError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return _session(ws, workspaces.clean_email(j.email))


@app.post("/api/workspace/create")
def workspace_create(c: NewCompany):
    try:
        ws, code = workspaces.create(c.name, c.email, _BASE_BANK)
    except workspaces.AuthError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return {**_session(ws, workspaces.clean_email(c.email)), "code": code,
            "note": "Share this code with your team. It is shown once. " + (f"Only @{ws['domain']} emails can join." if ws.get("domain") else "Anyone with the code can join, because a personal email domain was used.")}


@app.get("/api/workspace/me")
def workspace_me(ctx: dict = Depends(current)):
    w = ctx["ws"]
    return {"workspace": {"id": w["id"], "name": w["name"], "demo": bool(w.get("demo")), "domain": w.get("domain")}, "email": ctx["email"], "admin": ctx["admin"],
            "documents": len(workspaces.library(w["id"]))}


@app.post("/api/docs")
async def add_document(file: UploadFile = File(...), author: str = Form(""), caption: str = Form(""), ctx: dict = Depends(current)):
    """A document, case study, photo or sketch dropped into the chat. Text is read and cut into sections. A picture cannot be read without a vision model,
    so the person says what it shows and that caption is what the memory learns; the picture itself is kept in the library."""
    data = await file.read(documents.MAX_BYTES + 1)
    name = (file.filename or "document").strip()
    image = name.lower().endswith(documents.IMAGES)
    kept = None
    try:
        if image:
            text = documents.image_caption(name, data, caption)
            parts = [text]
        else:
            text = documents.extract(name, data)
            parts = documents.chunks(text)
    except documents.DocError as exc:
        raise HTTPException(422, str(exc)) from exc
    who = author.strip() if len(author.strip()) >= 2 else ctx["name"]
    stamp = int(time.time() * 1000)
    ds = workspaces.slug(name)
    if image:
        kept = f"{stamp}-{ds}{Path(name).suffix.lower()}"
        (workspaces.files_dir(ctx["ws"]["id"]) / kept).write_bytes(data)
    recs = [records.document_record(name, who, i + 1, len(parts), p, ds, f"doc-{ds}-{stamp}-{i + 1}", ev.NOW, "photo" if image else "document") for i, p in enumerate(parts)]
    try:
        ctx["memory"].retain_many(recs)
    except Exception as exc:
        log.exception("retain of a document failed")
        raise HTTPException(502, f"Could not save to memory: {exc}") from exc
    item = {"id": f"{ds}-{stamp}", "name": name, "author": who, "email": ctx["email"], "sections": len(parts), "chars": len(text), "date": ev.NOW,
            "kind": "image" if image else "document", "file": kept}
    workspaces.add_to_library(ctx["ws"]["id"], item)
    return {"saved": True, **{k: v for k, v in item.items() if k != "file"}, "memory_backend": ctx["memory"].name}


@app.get("/api/docs/{item_id}/file")
def document_file(item_id: str, ctx: dict = Depends(current)):
    item = next((x for x in workspaces.library(ctx["ws"]["id"]) if x["id"] == item_id and x.get("file")), None)
    if not item:
        raise HTTPException(404, "No such file in this company's library.")
    return FileResponse(workspaces.files_dir(ctx["ws"]["id"]) / item["file"])


class SkillIn(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    prompt: str = Field(min_length=10, max_length=1500)
    shared: bool = False


@app.get("/api/skills")
def list_skills(ctx: dict = Depends(current)):
    """Reusable templates: the person's own, plus any the company has shared with everyone."""
    return [{**{k: v for k, v in s.items() if k != "owner"}, "mine": s["owner"] == ctx["email"]} for s in workspaces.skills(ctx["ws"]["id"]) if s["owner"] == ctx["email"] or s.get("shared")]


@app.post("/api/skills")
def add_skill(s: SkillIn, ctx: dict = Depends(current)):
    items = workspaces.skills(ctx["ws"]["id"])
    if len(items) >= 80:
        raise HTTPException(422, "That is a lot of templates. Delete some first.")
    item = {"id": f"sk{int(time.time() * 1000)}", "name": s.name.strip(), "prompt": s.prompt.strip(), "shared": s.shared, "owner": ctx["email"], "date": ev.NOW}
    workspaces.save_skills(ctx["ws"]["id"], items + [item])
    return {"saved": True, "id": item["id"]}


@app.delete("/api/skills/{skill_id}")
def delete_skill(skill_id: str, ctx: dict = Depends(current)):
    items = workspaces.skills(ctx["ws"]["id"])
    s = next((x for x in items if x["id"] == skill_id), None)
    if not s:
        raise HTTPException(404, "No such template.")
    if s["owner"] != ctx["email"] and not ctx["admin"]:
        raise HTTPException(403, "Only the person who made it, or the admin, can delete a template.")
    workspaces.save_skills(ctx["ws"]["id"], [x for x in items if x["id"] != skill_id])
    return {"deleted": True}


@app.get("/api/records")
def sample_records(limit: int = 36, ctx: dict = Depends(current)):
    """The demo company's sample incident history, newest first, for the Library. Only the demo company has it; other companies see their own uploads."""
    if not ctx["ws"].get("demo"):
        return []
    out = []
    for v in reversed(store.all_visits()[-max(1, min(limit, 80)):]):
        m = store.machine(v["machine_id"]) or {}
        out.append({"id": v["job_id"], "date": v["date"], "machine": v["machine_id"], "model": m.get("model_family", ""), "site": (store.site(v["site_id"]) or {}).get("name", ""),
                    "symptom": v.get("symptom", ""), "root_cause": v.get("root_cause", ""), "fix": v.get("fix", ""),
                    "failed": [a["action"] for a in v.get("actions", []) if a.get("result") == "failed"][:3], "outcome": v.get("outcome", "")})
    return out


@app.get("/api/docs")
def list_documents(ctx: dict = Depends(current)):
    return workspaces.library(ctx["ws"]["id"])


class Feedback(BaseModel):
    question: str = Field(min_length=3, max_length=400)
    answer: str = Field("", max_length=4000)
    rating: Literal["up", "down"]
    correction: str = Field("", max_length=2000)
    refs: list[str] = Field(default_factory=list, max_length=12)       # the records the answer was drawn from


def _retain_correction(ctx: dict, question: str, text: str, refs: list[str] | None = None, machine: str | None = None) -> str:
    """Someone says the answer was wrong and what is right. It is retained as a correction record, and the next answer shows it first."""
    stamp = int(time.time() * 1000)
    about = f" about {machine}" if machine else ""
    body = (f"Correction by {ctx['name']} on {ev.NOW}{about}: the earlier answer to “{question.strip()}” was wrong or incomplete. "
            f"What is correct: {text.strip()}")
    tags = ["kind:correction", f"author:{workspaces.slug(ctx['name'])}"] + [f"corrects:{workspaces.slug(r)}" for r in (refs or [])[:6]]
    if machine:
        tags.append(f"machine:{machine}")
    try:
        ctx["memory"].retain(body, tags, ev.NOW, f"correction-{stamp}", {"author": ctx["name"], "kind": "correction", "question": question[:200]})
    except Exception as exc:
        log.exception("retain of a correction failed")
        raise HTTPException(502, f"Could not save to memory: {exc}") from exc
    return body


@app.post("/api/feedback")
def feedback(f: Feedback, ctx: dict = Depends(current)):
    """Thumbs on an answer. A thumbs-down with a correction is retained as a correction record, so the next answer carries it."""
    saved = False
    text = f.correction.strip()
    if f.rating == "down" and len(text) >= 15:
        stamp = int(time.time() * 1000)
        body = (f"Correction by {ctx['name']} on {ev.NOW}: the earlier answer to \u201c{f.question.strip()}\u201d was wrong or incomplete. "
                f"What is correct: {text}")
        try:
            ctx["memory"].retain(body, ["kind:correction", f"author:{workspaces.slug(ctx['name'])}"] + [f"corrects:{workspaces.slug(r)}" for r in f.refs[:6]],
                                 ev.NOW, f"correction-{stamp}", {"author": ctx["name"], "kind": "correction", "question": f.question[:200]})
        except Exception as exc:
            log.exception("retain of a correction failed")
            raise HTTPException(502, f"Could not save to memory: {exc}") from exc
        saved = True
    workspaces.add_feedback(ctx["ws"]["id"], {"date": ev.NOW, "who": ctx["email"], "question": f.question[:200], "rating": f.rating, "corrected": saved, "refs": f.refs[:6]})
    return {"saved": True, "correction_retained": saved}


@app.post("/api/workspace/guest")
def workspace_guest():
    ws, tok = workspaces.guest()
    return {"token": tok, "workspace": {"id": ws["id"], "name": ws["name"], "demo": True, "domain": None}, "email": workspaces.GUEST_EMAIL, "admin": False}


@app.get("/api/company")
def company_overview():
    """The company dashboard: who holds which fixes, where knowledge is thin, what has been written down."""
    return knowledge.overview(store, store.notes)


# ------------------------------------------------------------------ voice
@app.post("/api/voice/report")
async def voice_report(job_id: str = Form(...), audio: UploadFile = File(...), ctx: dict = Depends(current)):
    job = store.job(job_id)
    data = await audio.read(voice.MAX_BYTES + 1)
    try:
        tr = await run_in_threadpool(voice.transcribe, llm.client, data, audio.filename or "report.webm")
    except voice.VoiceError as exc:
        raise HTTPException(422, {"code": exc.code, "message": exc.message})
    structured, warnings = await run_in_threadpool(voice.extract_visit, llm, tr["text"], job)
    return {"transcript": tr["text"], "duration": tr["duration"], "structured": structured, "warnings": warnings}


@app.post("/api/voice/extract")
async def voice_extract(body: dict, ctx: dict = Depends(current)):
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
def eval_run(limit: int | None = None, ctx: dict = Depends(admin_only)):
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
def reset_demo(ctx: dict = Depends(admin_only)):
    """Back to the original history. Hindsight cannot delete memories, so this moves the agents to a fresh bank and re-seeds it
    in the background (Hindsight takes a minute or two to finish ingesting); the local copy is rebuilt straight away."""
    import threading
    import time as _t
    global memory
    store.clear_logged()
    recs = records.build_all(store, visits=store.history)
    local = LocalMemory(DATA / "local_memory_shared.json")
    local.items = []
    local.retain_many(recs)
    new = local
    if _primary.name == "hindsight":
        bank = f"{_BASE_BANK}-{int(_t.time())}"
        prim = build_memory("shared", bank_id=bank, mission=records.MISSION)
        new = FallbackMemory(prim, local)
        threading.Thread(target=lambda: prim.retain_many(recs), daemon=True, name="reseed").start()
        _set_state(bank_id=bank, beliefs_retained={}, **{f"seeded_{bank}": len(recs)})
    memory = new
    room.memory = new
    beliefs_engine.memory = new
    try:
        beliefs_engine.sync()
    except Exception:
        log.exception("belief sync after reset failed")
    return {"reset": True, "bank": getattr(new, "bank_id", "local"), "note": "Fresh memory bank created and re-seeded with the original history. Hindsight needs a minute or two to finish ingesting it."}


# ------------------------------------------------------------------ frontend
_DEMO = ROOT.parent / "docs" / "demo"
_DEMO.mkdir(parents=True, exist_ok=True)
app.mount("/demo", StaticFiles(directory=str(_DEMO)), name="demo")        # the recorded walkthrough video


@app.get("/")
def landing():
    return FileResponse(FRONTEND / "landing.html")


@app.get("/chat")
def chat_page():
    return FileResponse(FRONTEND / "index.html")


@app.get("/architecture")
def architecture_page():
    return FileResponse(FRONTEND / "architecture.html")


# ------------------------------------------------------------------ dispatch: report a problem, rank the issues, offer the job to the best technician
class RegisterReq(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    role: Literal["reporter", "technician"]
    site_id: str | None = None
    speciality: str = Field("", max_length=80)
    area: str = Field("", max_length=60)
    company_code: str = Field("", max_length=60)      # a technician needs the company's code to join


class PushReq(BaseModel):
    token: str = Field(min_length=20, max_length=4096)


class LoginReq(BaseModel):
    tech_id: str = Field(min_length=2, max_length=12)
    company_code: str = Field("", max_length=60)


class PresenterReq(BaseModel):
    key: str = Field("", max_length=80)


class ReportReq(BaseModel):
    user_id: str
    site_id: str
    machine_id: str | None = None
    symptom: str = Field(min_length=6, max_length=400)
    severity: Literal["urgent", "high", "normal"] = "normal"
    manual: bool = False          # Manual mode: nobody answers by themselves; the presenter or a real phone decides
    source: Literal["app", "web", "demo"] = "web"
    photo: str | None = Field(None, max_length=700_000)       # optional picture of the unit, as a data: URL
    accept_after: int | None = Field(None, ge=-1, le=40)     # Demo mode: how many technicians decline before one accepts (0 = the first, -1 = nobody)


class FleetReq(BaseModel):
    big: bool


class DutyReq(BaseModel):
    on: bool


class ModeReq(BaseModel):
    mode: Literal["demo", "manual"]


class OtpReq(BaseModel):
    tech_id: str
    otp: str = Field(min_length=3, max_length=8)
    demo: bool = False


class RespondReq(BaseModel):
    tech_id: str
    action: Literal["accept", "decline"]
    demo: bool = False


class StatusReq(BaseModel):
    tech_id: str
    status: Literal["on_site", "resolved"]
    done: bool = True            # when closing: was the work done (true) or not (false, a revisit is needed)


def _dispatch_call(fn, *a, **k):
    try:
        return fn(*a, **k)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (KeyError, NotFound, UnknownMachine) as exc:
        raise HTTPException(404, str(exc).strip("'\"")) from exc


_limiter = session_mod.Limiter()


def actor(x_cognify_session: str | None = Header(None)) -> dict:
    """Who is calling: the signed-in reporter, technician or presenter. 401 when there is no valid session."""
    try:
        return session_mod.verify(x_cognify_session)
    except session_mod.SessionError as exc:
        raise HTTPException(exc.status, exc.message) from exc


def _guard(request: Request, limit: int = 12) -> None:
    """Slow down anyone guessing codes or flooding sign-in."""
    try:
        _limiter.check(request.client.host if request.client else "?", limit)
    except session_mod.SessionError as exc:
        raise HTTPException(exc.status, exc.message) from exc


def _presenter(who: dict) -> None:
    if who["role"] != "presenter":
        raise HTTPException(403, "Only the presenter can do that.")


def _as_tech(who: dict, tid: str, demo: bool = False) -> None:
    """A technician acts only as themselves. The presenter may answer for a technician only through the demo controls."""
    if who["role"] == "technician" and who["tid"] == tid and not demo:
        return
    if demo and who["role"] == "presenter":
        return
    raise HTTPException(403, "That is not your account.")


def _may_see(who: dict, rid: str) -> None:
    """Reporters see their own requests; technicians see the ones offered to or assigned to them; the presenter sees all."""
    if who["role"] == "presenter":
        return
    rep = _dispatch_call(dispatch.get, rid)
    if who["role"] == "reporter" and rep["reporter"]["id"] == who["uid"]:
        return
    if who["role"] == "technician" and (rep["assigned"] == who["tid"] or any(o["tech_id"] == who["tid"] for o in rep["offers"])):
        return
    raise HTTPException(403, "That request is not yours.")


@app.post("/api/dispatch/register")
def dispatch_register(r: RegisterReq, request: Request):
    _guard(request)
    if r.role == "technician" and not session_mod.code_ok(r.company_code):
        raise HTTPException(403, "Wrong company code. Only the company's own technicians can join.")
    user = _dispatch_call(dispatch.register, r.name, r.role, r.site_id, r.speciality, r.area)
    return {**user, "session": session_mod.issue(r.role, user["id"], user.get("tech_id"))}


@app.post("/api/dispatch/login")
def dispatch_login(r: LoginReq, request: Request):
    """An existing technician signs in with the company code."""
    _guard(request)
    if not session_mod.code_ok(r.company_code):
        raise HTTPException(403, "Wrong company code. Only the company's own technicians can sign in.")
    try:
        tech = dispatch.store.tech(r.tech_id)
    except Exception as exc:
        raise HTTPException(404, "Unknown technician.") from exc
    if tech.get("extra"):
        raise HTTPException(403, "That technician is part of the simulated city fleet.")
    return {"id": r.tech_id, "name": tech["name"], "role": "technician", "tech_id": r.tech_id, "session": session_mod.issue("technician", r.tech_id, r.tech_id)}


@app.post("/api/dispatch/presenter-login")
def dispatch_presenter_login(r: PresenterReq, request: Request):
    """The person running the dispatch screen. Needs DISPATCH_PRESENTER_KEY, or (with none set) must be on the laptop itself, not behind a tunnel."""
    _guard(request, 10)
    forwarded = bool(request.headers.get("x-forwarded-for") or request.headers.get("cf-connecting-ip") or request.headers.get("forwarded"))
    if not session_mod.presenter_ok(r.key, request.client.host if request.client else None, forwarded):
        raise HTTPException(403, "The presenter key is needed.")
    return {"role": "presenter", "session": session_mod.issue("presenter", "presenter")}


@app.get("/api/dispatch/meta")
def dispatch_meta():
    return dispatch.meta()


@app.get("/api/dispatch/board")
def dispatch_board(viewer: str | None = None, who: dict = Depends(actor)):
    _presenter(who)
    return dispatch.board(viewer)


@app.get("/api/dispatch/map")
def dispatch_map(who: dict = Depends(actor)):
    return dispatch.positions()


@app.get("/api/dispatch/explain")
def dispatch_explain(site_id: str, machine_id: str | None = None, severity: str = "high"):
    return _dispatch_call(dispatch.explain, site_id, machine_id or None, severity)


@app.post("/api/dispatch/demo-report")
def dispatch_demo_report(manual: bool = False, accept_after: int | None = None, who: dict = Depends(actor)):
    _presenter(who)
    return dispatch.view(_dispatch_call(dispatch.demo_report, manual, "demo", accept_after))


@app.post("/api/dispatch/fleet")
def dispatch_fleet(r: FleetReq, who: dict = Depends(actor)):
    _presenter(who)
    return dispatch.set_fleet(r.big)


@app.post("/api/reports")
def create_report(r: ReportReq, who: dict = Depends(actor)):
    if who["role"] == "reporter":
        if r.user_id != who["uid"]:
            raise HTTPException(403, "You can only report as yourself.")
    elif who["role"] != "presenter":
        raise HTTPException(403, "Only a reporter can raise a problem.")
    return dispatch.view(_dispatch_call(dispatch.create_report, r.user_id, r.site_id, r.machine_id, r.symptom, r.severity, r.manual, r.source, r.accept_after, r.photo))


@app.get("/api/reports")
def list_reports(user_id: str | None = None, who: dict = Depends(actor)):
    if who["role"] == "reporter":
        user_id = who["uid"]                        # a reporter only ever sees their own requests
    elif who["role"] != "presenter":
        raise HTTPException(403, "Not available for this account.")
    rows = dispatch.board()
    return [r for r in rows if r["reporter"]["id"] == user_id] if user_id else rows


@app.get("/api/reports/{rid}")
def get_report(rid: str, viewer: str | None = None, who: dict = Depends(actor)):
    _may_see(who, rid)
    seen_as = "demo" if who["role"] == "presenter" else who["uid"]       # the OTP is shown only to its reporter (and the presenter)
    return dispatch.view(_dispatch_call(dispatch.get, rid), seen_as)


@app.get("/api/tech/{tid}/inbox")
def tech_inbox(tid: str, who: dict = Depends(actor)):
    _as_tech(who, tid)
    return _dispatch_call(dispatch.inbox, tid)


@app.post("/api/reports/{rid}/respond")
def respond_to_report(rid: str, r: RespondReq, who: dict = Depends(actor)):
    _as_tech(who, r.tech_id, r.demo)
    return dispatch.view(_dispatch_call(dispatch.respond, rid, r.tech_id, r.action, r.demo))


@app.post("/api/reports/{rid}/start")
def start_report_work(rid: str, r: OtpReq, who: dict = Depends(actor)):
    _as_tech(who, r.tech_id, r.demo)
    return dispatch.view(_dispatch_call(dispatch.start_work, rid, r.tech_id, r.otp, r.demo))


@app.post("/api/tech/{tid}/mode")
def tech_mode(tid: str, r: ModeReq, who: dict = Depends(actor)):
    _as_tech(who, tid)
    return _dispatch_call(dispatch.set_mode, tid, r.mode)


@app.post("/api/tech/{tid}/duty")
def tech_duty(tid: str, r: DutyReq, who: dict = Depends(actor)):
    _as_tech(who, tid)
    return _dispatch_call(dispatch.set_duty, tid, r.on)


@app.post("/api/reports/{rid}/status")
def report_status(rid: str, r: StatusReq, who: dict = Depends(actor)):
    _as_tech(who, r.tech_id)
    return dispatch.view(_dispatch_call(dispatch.set_status, rid, r.tech_id, r.status, r.done))


def _push_key(who: dict) -> str:
    """Notifications go to a technician by technician id and to a reporter by user id. The presenter has no phone."""
    key = who["tid"] if who["role"] == "technician" else who["uid"] if who["role"] == "reporter" else None
    if not key:
        raise HTTPException(403, "Not available for this account.")
    return key


@app.post("/api/push/register")
def push_register(r: PushReq, who: dict = Depends(actor)):
    dispatch.register_push(_push_key(who), r.token)
    return {"ok": True, "push_enabled": pusher.enabled}


@app.post("/api/push/unregister")
def push_unregister(r: PushReq, who: dict = Depends(actor)):
    dispatch.unregister_push(_push_key(who), r.token)
    return {"ok": True}


@app.get("/dispatch")
def dispatch_page():
    return FileResponse(FRONTEND / "dispatch.html")


@app.get("/how-matching-works")
def matching_page():
    return FileResponse(FRONTEND / "matching.html")


@app.get("/phone")
@app.get("/evaluation")
@app.get("/learning")
def legacy_views():
    """The technician phone (voice logging) and the evaluation dashboard live in the original single-page app."""
    return FileResponse(FRONTEND / "index.html")


@app.get("/memory")
def memory_page():
    return FileResponse(FRONTEND / "memory.html")


@app.get("/how-it-works")
def how_page():
    return FileResponse(FRONTEND / "how.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))   # HOST=0.0.0.0 lets a phone on the same Wi-Fi reach it
