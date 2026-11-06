"""The Agent Control Room: one input, two paths side by side.

WITHOUT  the same four agents with no memory and no records (so the Verifier has nothing to check against).
WITH     the same four agents on the one shared Hindsight bank; handoffs go through a Band room (in-process if Band is down).
Every agent message, every memory operation (recall / reflect / retain), every Verifier veto and revision, and the simulated consequence
is emitted as an event and streamed to the UI."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Any

from agents import Case, Diagnostician, Dispatcher, PartsAgent, Verifier, feedback_text
from simulate import simulate
from traced import NullMemory, TracedMemory
from .band import BandError, BandRoom, load_clients

log = logging.getLogger("sitememory.mesh")
LABELS = {"dispatcher": "Dispatcher", "diagnostician": "Diagnostician", "parts": "Parts agent", "verifier": "Verifier", "briefing": "Technician briefing",
          "system": "System", "feed": "Alarm feed"}

BRIEF_PROMPT = """You write the short briefing a field technician reads on a phone before a job. Use ONLY the plan below. Do not add causes, parts or history.
Return ONLY JSON: {"headline":string (<=14 words),"likely_cause":string,"do_first":[string] (max 4),"avoid":[string] (max 3: fixes the plan says failed or were vetoed, with why),
"bring":[string] (max 5),"site_notes":[string] (max 4, from the site notes given)}"""


def _clean(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items() if not k.startswith("_")}
    if isinstance(o, list):
        return [_clean(x) for x in o]
    return o


class Run:
    def __init__(self, scenario: dict, alarm: dict):
        self.id = uuid.uuid4().hex[:10]
        self.scenario, self.alarm = scenario, alarm
        self.events: list[dict] = []
        self.status, self.plans, self.band_room = "running", {}, None
        self.cond = threading.Condition()
        self.started = datetime.now().isoformat(timespec="seconds")
        self.transport = {"with": "in-process", "without": "in-process"}

    def emit(self, path: str, agent: str, kind: str, text: str, data: dict | None = None, ops: list | None = None) -> dict:
        ev = {"n": len(self.events), "t": round(time.time(), 2), "path": path, "agent": agent, "label": LABELS.get(agent, agent), "kind": kind, "text": text,
              "data": _clean(data) if data else {}, "ops": ops or [], "transport": self.transport.get(path, "in-process")}
        with self.cond:
            self.events.append(ev)
            self.cond.notify_all()
        return ev

    def finish(self, status: str = "done") -> None:
        with self.cond:
            self.status = status
            self.cond.notify_all()

    def public(self) -> dict:
        return {"id": self.id, "scenario": {k: v for k, v in self.scenario.items() if k != "truth"}, "alarm": self.alarm, "status": self.status,
                "transport": self.transport, "started": self.started, "events": self.events,
                "plans": {p: _clean(plan) for p, plan in self.plans.items()}}


class Ctx:
    """Everything one path needs while it runs."""

    def __init__(self, run: Run, path: str, case: Case, room: BandRoom | None):
        self.run, self.path, self.case, self.room = run, path, case, room
        self.ops: list[dict] = []
        self.lock = threading.Lock()

    def on_op(self, e: dict) -> None:
        with self.lock:
            self.ops.append(e)
        self.run.emit(self.path, e.get("who") or "system", "memory", f"{e['op']} {len(e['hits'])} hit(s)" if not e.get("skipped") else f"{e['op']} skipped (memory off)", e)

    def mark(self) -> int:
        with self.lock:
            return len(self.ops)

    def since(self, i: int) -> list[dict]:
        with self.lock:
            return list(self.ops[i:])

    def say(self, agent: str, text: str, kind: str = "msg", data: dict | None = None, ops_from: int | None = None) -> dict:
        return self.run.emit(self.path, agent, kind, text, data, self.since(ops_from) if ops_from is not None else None)

    def hand(self, sender: str, to: str, text: str, payload: dict) -> None:
        """Hand the work to the next agent: a real Band message that the receiver reads back, or an in-process hop if Band is down."""
        if self.room:
            try:
                self.room.deliver(sender, to, text, _clean(payload))
                self.run.transport[self.path] = "band"
            except BandError as exc:
                self.room = None
                self.run.transport[self.path] = "in-process"
                self.run.emit(self.path, "system", "system", f"Band unreachable ({str(exc)[:120]}). Continuing in-process so the run keeps going.")
        self.run.emit(self.path, sender, "handoff", f"→ {LABELS.get(to, to)}: {text}", {"to": to, "via": self.run.transport[self.path]})


def stat_line(c: dict) -> str:
    s = c.get("stats")
    if not s or s.get("n") is None or c.get("confidence") == "none":
        return "no records to count"
    if s["n"] == 0:
        return "no attempts on record"
    rate = f"{round(s['rate'] * 100)}%" if s["rate"] is not None else "n/a"
    sig = "weak signal" if s["weak"] else f"{c['confidence']} confidence"
    return f"n={s['n']}: {s['verified']} verified, {s['provisional']} not yet stable, {s['failed']} failed; verified rate {rate} (95% {round(s['ci'][0] * 100)}-{round(s['ci'][1] * 100)}%); {sig}"


class ControlRoom:
    def __init__(self, store, memory, llm, band_clients: dict | None = None):
        self.store, self.memory, self.llm = store, memory, llm
        self.band = band_clients if band_clients is not None else load_clients()
        self.runs: dict[str, Run] = {}
        self.dispatcher, self.diagnostician, self.parts, self.verifier = Dispatcher(), Diagnostician(), PartsAgent(), Verifier()

    def status(self) -> dict:
        return {"band": "configured" if self.band else "not configured (in-process fallback)", "bank": getattr(self.memory, "bank_id", "local"),
                "backend": self.memory.name, "agents": ["dispatcher", "diagnostician", "parts", "verifier"]}

    # ---------------------------------------------------------------- start
    def case_for(self, scenario: dict, use_memory: bool, run: Run, ctx_holder: dict, as_of: str | None = None) -> Case:
        m = self.store.machine(scenario["machine_id"])             # raises UnknownMachine for an invented id
        site = self.store.site(m["site_id"])
        job = next((j for j in self.store.open_jobs if j["job_id"] == scenario.get("job_id")), None) or {
            "job_id": f"AL-{run.alarm['id']}", "date": run.alarm["ts"][:10], "machine_id": m["id"], "symptom": f"{scenario['description']}. Readings {scenario['readings']}."}
        emit = lambda e: ctx_holder["ctx"].on_op(e)
        mem = TracedMemory(self.memory, emit, self.store) if use_memory else NullMemory(emit)
        return Case(alarm=run.alarm, machine=m, site=site, job=job, store=self.store, llm=self.llm, memory=mem, use_memory=use_memory, as_of=as_of,
                    visits=self.store.visits_before(as_of) if use_memory else [], alarms=self.store.alarms_before(as_of) if use_memory else [])

    def start(self, scenario_id: str, as_of: str | None = None) -> Run:
        sc = self.store.scenario(scenario_id)
        self.store.machine(sc["machine_id"])
        alarm = {**{k: sc[k] for k in ("machine_id", "code", "description", "readings", "severity")}, "id": f"{sc['id']}-{len(self.runs) + 1}",
                 "ts": datetime.now().isoformat(timespec="seconds"), "site_id": sc["site_id"]}
        run = Run(sc, alarm)
        self.runs[run.id] = run
        for old in list(self.runs)[:-20]:
            self.runs.pop(old, None)
        threading.Thread(target=self._both, args=(run, sc, as_of), daemon=True, name=f"run-{run.id}").start()
        return run

    def get(self, rid: str) -> Run | None:
        return self.runs.get(rid)

    def _both(self, run: Run, sc: dict, as_of: str | None) -> None:
        run.emit("with", "feed", "alarm", f"{sc['code']} on {sc['machine_id']}: {sc['description']}. {sc['headline']}.", {"alarm": run.alarm})
        run.emit("without", "feed", "alarm", f"{sc['code']} on {sc['machine_id']}: {sc['description']}. {sc['headline']}.", {"alarm": run.alarm})
        threads = []
        for path, use_memory in (("without", False), ("with", True)):
            t = threading.Thread(target=self._safe_path, args=(run, sc, path, use_memory, as_of), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        run.finish("done")

    def _safe_path(self, run: Run, sc: dict, path: str, use_memory: bool, as_of: str | None) -> None:
        try:
            holder: dict = {}
            case = self.case_for(sc, use_memory, run, holder, as_of)
            room = None
            if use_memory and self.band:
                try:
                    room = BandRoom(self.band, f"SiteMemory {run.alarm['id']} {sc['machine_id']} {sc['code']}")
                    run.transport[path] = "band"
                    run.emit(path, "system", "system", f"Band room created ({room.room_id[:8]}): Dispatcher, Diagnostician, Parts and Verifier joined.")
                except Exception as exc:
                    run.emit(path, "system", "system", f"Band unreachable ({str(exc)[:120]}). Running the same four agents in-process.")
            elif use_memory:
                run.emit(path, "system", "system", "Band is not configured: the same four agents run in-process.")
            ctx = Ctx(run, path, case, room)
            holder["ctx"] = ctx
            if not use_memory:
                ctx.on_op({"op": "recall", "who": "system", "bank": "(memory off)", "query": "this path has no memory and no records", "tags": [], "hits": [], "ms": 0, "skipped": True})
            plan = self.execute(ctx)
            plan["consequence"] = simulate(plan, sc["truth"])
            run.plans[path] = plan
            run.emit(path, "system", "consequence", f"Simulated: {plan['consequence']['outcome']}.", plan["consequence"])
        except Exception as exc:
            log.exception("path %s failed", path)
            run.emit(path, "system", "error", f"This path stopped: {exc}")

    # ---------------------------------------------------------------- the four agents
    def execute(self, ctx: Ctx) -> dict:
        case = ctx.case
        i = ctx.mark()
        d = self.dispatcher.decide(case)
        led = d.get("ledger")
        text = f"{'REMOTE FIX' if d['decision'] == 'REMOTE_FIX' else 'SEND A TECHNICIAN'}. {d['rationale']}" + (f" Action: {d['remote_action']}." if d["remote_action"] else "")
        ctx.say("dispatcher", text, "msg", d, i)
        ctx.hand("dispatcher", "diagnostician", "Alarm needs a diagnosis" + (" (remote step queued first)" if d["decision"] == "REMOTE_FIX" else ""), {"alarm": case.alarm})

        i = ctx.mark()
        diag = self.diagnostician.diagnose(case)
        ctx.say("diagnostician", self._diag_text(diag), "msg", diag, i)
        ctx.hand("diagnostician", "parts", f"Diagnosis: {diag['causes'][0]['fix']}", {"top": diag["causes"][0]})

        i = ctx.mark()
        parts = self.parts.plan(case, diag)
        ctx.say("parts", self._parts_text(parts), "msg", parts, i)
        ctx.hand("parts", "verifier", "Plan ready for verification", {"carry": [p["part"] for p in parts["carry"]]})

        rounds = []
        for rnd in range(3):
            i = ctx.mark()
            v = self.verifier.review(case, d, diag, parts)
            rounds.append(v)
            if not case.use_memory:
                ctx.say("verifier", "There are no records to verify against, so the generic plan passes through unchecked.", "approve", v, i)
                break
            for ap in v["approvals"]:
                pass
            if v["approvals"]:
                ctx.say("verifier", "Approved: " + "; ".join(f"{a['item']} ({a['note']})" for a in v["approvals"]), "approve", {"approvals": v["approvals"]}, i)
            for vt in v["vetoes"]:
                ctx.say("verifier", f"VETO ({LABELS.get(vt['target'], vt['target'])}): {vt['item']}. " + " ".join(vt["reasons"]), "veto", vt)
            if v["ok"]:
                break
            if rnd == 2:
                self._drop_vetoed(diag, parts, v["vetoes"])
                ctx.say("verifier", "Still unverified after two revisions: the vetoed items are removed from the plan.", "veto", {"final": True})
                break
            if any(x["target"] == "diagnostician" for x in v["vetoes"]):
                ctx.hand("verifier", "diagnostician", "Vetoed: please revise", {"vetoes": v["vetoes"]})
                i = ctx.mark()
                diag = self.diagnostician.diagnose(case, feedback_text(v["vetoes"], "diagnostician"), prior=diag)
                ctx.say("diagnostician", "Revised. " + self._diag_text(diag), "revise", diag, i)
                i = ctx.mark()
                parts = self.parts.plan(case, diag, feedback_text(v["vetoes"], "parts"))
                ctx.say("parts", "Re-planned for the revised diagnosis. " + self._parts_text(parts), "revise", parts, i)
            elif any(x["target"] == "parts" for x in v["vetoes"]):
                ctx.hand("verifier", "parts", "Vetoed: please revise", {"vetoes": v["vetoes"]})
                i = ctx.mark()
                parts = self.parts.plan(case, diag, feedback_text(v["vetoes"], "parts"))
                ctx.say("parts", "Revised. " + self._parts_text(parts), "revise", parts, i)
            else:
                break
        plan = {"dispatch": d, "diagnosis": diag, "parts": parts, "verifier": {"rounds": [{"vetoes": r["vetoes"], "approvals": r["approvals"]} for r in rounds],
                "vetoes": [x for r in rounds for x in r["vetoes"]], "revised": len(rounds) > 1}}
        i = ctx.mark()
        plan["briefing"] = self._brief(case, plan)
        b = plan["briefing"]
        ctx.say("briefing", f"{b['headline']} Do first: {'; '.join(b['do_first'][:2])}. Bring: {', '.join(b['bring'][:3])}.", "plan", b, i)
        return plan

    @staticmethod
    def _diag_text(diag: dict) -> str:
        c = diag["causes"][0]
        return f"Most likely: {c['fix']} ({c['cause']}). {stat_line(c)}." + (f" Cites {', '.join(c['evidence_jobs'])}." if c["evidence_jobs"] else "")

    @staticmethod
    def _parts_text(parts: dict) -> str:
        carry = "; ".join(f"{p['qty']}x {p['part']} ({p['stock']})" for p in parts["carry"]) or "no specific parts"
        return f"Carry: {carry}." + (f" Flags: {' '.join(parts['flags'])}" if parts["flags"] else "")

    @staticmethod
    def _drop_vetoed(diag: dict, parts: dict, vetoes: list[dict]) -> None:
        gone = {v["item"] for v in vetoes if v["target"] == "parts"}
        parts["carry"] = [p for p in parts["carry"] if p["part"] not in gone]
        bad = {v["item"] for v in vetoes if v["target"] == "diagnostician"}
        diag["causes"] = [c for c in diag["causes"] if c["fix"] not in bad] or [
            {"cause": "Unverified: escalate to a senior technician", "fix": "Escalate to a senior technician", "why": "", "evidence_jobs": [],
             "stats": {"n": 0, "weak": True, "rate": None, "ci": [0, 1], "verified": 0, "provisional": 0, "failed": 0}, "confidence": "weak"}]

    def _brief(self, case: Case, plan: dict) -> dict:
        diag, parts, top = plan["diagnosis"], plan["parts"], plan["diagnosis"]["causes"][0]
        avoid = []
        if case.use_memory:
            for c in diag["causes"][1:]:
                pass
            for vt in plan["verifier"]["vetoes"]:
                avoid.append(f"{vt['item']}: " + vt["reasons"][0])
        user = (f"Plan\nAlarm: {case.alarm.get('code')} {case.alarm.get('description')}. Machine {case.machine['model']} installed {case.machine['installed']}.\n"
                f"Dispatch: {plan['dispatch']['decision']} {plan['dispatch'].get('remote_action') or ''}\nCause: {top['cause']}\nRepair: {top['fix']}\n"
                f"Evidence: {stat_line(top)}\nAlready failed or vetoed: {avoid or 'nothing recorded'}\nParts: {[(p['part'], p['stock']) for p in parts['carry']]} flags {parts['flags']}\n"
                f"Site notes: {diag.get('site_notes')}")
        d = case.llm.json_chat(BRIEF_PROMPT, user, required=("headline", "do_first")) if case.llm else None
        d = d or {"headline": f"{top['fix']}", "likely_cause": top["cause"], "do_first": [top["fix"]], "avoid": avoid[:3],
                  "bring": [p["part"] for p in parts["carry"]][:5], "site_notes": [str(n)[:160] for n in (diag.get("site_notes") or [])][:3]}
        conf = top.get("confidence") if case.use_memory else "none"
        lst = lambda k, n: [str(x) for x in (d.get(k) or [])][:n]
        return {"headline": str(d.get("headline", ""))[:140], "likely_cause": str(d.get("likely_cause", top["cause"]))[:240], "do_first": lst("do_first", 4),
                "avoid": lst("avoid", 3), "bring": lst("bring", 5), "site_notes": lst("site_notes", 4),
                "confidence": {"high": "high", "medium": "medium", "low": "low", "weak": "weak signal"}.get(conf, "no history"), "evidence": stat_line(top)}
