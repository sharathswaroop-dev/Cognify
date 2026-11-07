"""The Agent Control Room: one input, two paths side by side.

WITHOUT  the same four agents with no memory and no records (so the Verifier has nothing to check against).
WITH     the same four agents on the one shared Hindsight bank; handoffs go through a Band room (in-process if Band is down).
Every agent message, every memory operation (recall / reflect / retain), every Verifier veto and revision, and the simulated consequence
is emitted as an event and streamed to the UI."""
from __future__ import annotations

import copy
import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Any

from agents import Case, Diagnostician, Dispatcher, PartsAgent, Verifier, feedback_text
from plan import drop_vetoed
from simulate import simulate
from memory import FallbackMemory, LocalMemory
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


CHAOS = ("none", "band", "memory", "llm")


class _BrokenHindsight:
    """Stands in for Hindsight during a drill: every call fails the way a real outage does."""
    name, bank_id = "hindsight (simulated outage)", "simulated"

    def _boom(self, *a, **k):
        raise RuntimeError("503 Service Unavailable: simulated Hindsight outage")

    recall = reflect = retain = retain_many = _boom

    def count(self) -> int:
        return 0


class Run:
    def __init__(self, scenario: dict, alarm: dict):
        self.id = uuid.uuid4().hex[:10]
        self.scenario, self.alarm = scenario, alarm
        self.events: list[dict] = []
        self.status, self.plans, self.band_room = "running", {}, None
        self.cond = threading.Condition()
        self.started = datetime.now().isoformat(timespec="seconds")
        self.transport = {"with": "in-process", "without": "in-process"}
        self.chaos = "none"
        self.paths = ("without", "with")

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
                "transport": self.transport, "chaos": self.chaos, "started": self.started, "events": self.events,
                "plans": {p: _clean(plan) for p, plan in self.plans.items()}}


class Ctx:
    """Everything one path needs while it runs."""

    def __init__(self, run: Run, path: str, case: Case, room: BandRoom | None):
        self.run, self.path, self.case, self.room = run, path, case, room
        self.ops: list[dict] = []
        self.lock = threading.Lock()
        self.watch, self.announced = None, False
        self.current = "system"             # the agent whose turn it is: searches are attributed to it

    def on_op(self, e: dict) -> None:
        if not e.get("who"):
            e["who"] = self.current
        with self.lock:
            self.ops.append(e)
        self.run.emit(self.path, e.get("who") or "system", "memory", f"{e['op']} {len(e['hits'])} hit(s)" if not e.get("skipped") else f"{e['op']} skipped (memory off)", e)
        if self.watch is not None and getattr(self.watch, "degraded", False) and not self.announced:
            self.announced = True
            self.run.emit(self.path, "system", "system", "Hindsight did not answer (" + str(getattr(self.watch, "reason", ""))[:110] + "). The agents switched to the local keyword memory and carried on; nothing was lost.",
                          {"fallback": "memory"})

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
                self.run.emit(self.path, "system", "system", f"Band unreachable ({str(exc)[:120]}). Continuing in-process so the run keeps going.", {"fallback": "band"})
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
    def case_for(self, scenario: dict, use_memory: bool, run: Run, ctx_holder: dict, as_of: str | None = None, memory=None, llm=None) -> Case:
        m = self.store.machine(scenario["machine_id"])             # raises UnknownMachine for an invented id
        site = self.store.site(m["site_id"])
        job = next((j for j in self.store.open_jobs if j["job_id"] == scenario.get("job_id")), None) or {
            "job_id": f"AL-{run.alarm['id']}", "date": run.alarm["ts"][:10], "machine_id": m["id"], "symptom": f"{scenario['description']}. Readings {scenario['readings']}."}
        emit = lambda e: ctx_holder["ctx"].on_op(e)
        mem = TracedMemory(memory or self.memory, emit, self.store) if use_memory else NullMemory(emit)
        return Case(alarm=run.alarm, machine=m, site=site, job=job, store=self.store, llm=llm or self.llm, memory=mem, use_memory=use_memory, as_of=as_of,
                    visits=self.store.visits_before(as_of) if use_memory else [], alarms=self.store.alarms_before(as_of) if use_memory else [])

    def start(self, scenario_id: str, as_of: str | None = None, chaos: str = "none", paths: tuple = ("without", "with")) -> Run:
        sc = self.store.scenario(scenario_id)
        self.store.machine(sc["machine_id"])
        alarm = {**{k: sc[k] for k in ("machine_id", "code", "description", "readings", "severity")}, "id": f"{sc['id']}-{len(self.runs) + 1}",
                 "ts": datetime.now().isoformat(timespec="seconds"), "site_id": sc["site_id"]}
        run = Run(sc, alarm)
        run.chaos = chaos if chaos in CHAOS else "none"
        run.paths = tuple(paths)
        self.runs[run.id] = run
        for old in list(self.runs)[:-20]:
            self.runs.pop(old, None)
        threading.Thread(target=self._both, args=(run, sc, as_of), daemon=True, name=f"run-{run.id}").start()
        return run

    def get(self, rid: str) -> Run | None:
        return self.runs.get(rid)

    def _both(self, run: Run, sc: dict, as_of: str | None) -> None:
        for pth in run.paths:
            run.emit(pth, "feed", "alarm", f"{sc['code']} on {sc['machine_id']}: {sc['description']}. {sc['headline']}.", {"alarm": run.alarm})
        threads = []
        for path, use_memory in (("without", False), ("with", True)):
            if path not in run.paths:
                continue
            t = threading.Thread(target=self._safe_path, args=(run, sc, path, use_memory, as_of), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        run.finish("done")

    def _safe_path(self, run: Run, sc: dict, path: str, use_memory: bool, as_of: str | None) -> None:
        try:
            holder: dict = {}
            mem_override, llm_override, chaos = None, None, run.chaos if use_memory else "none"
            if chaos == "memory":
                local = getattr(self.memory, "secondary", None) or self.memory
                mem_override = FallbackMemory(_BrokenHindsight(), local)
                run.emit(path, "system", "system", "Drill: Hindsight is switched off for this run. Watch the agents carry on.", {"chaos": "memory"})
            if chaos == "llm":
                chain = list(getattr(self.llm, "models", []) or [])
                if chain:
                    llm_override = copy.copy(self.llm)
                    llm_override.models = ["simulated/model-outage"] + chain
                run.emit(path, "system", "system", f"Drill: the primary model ({chain[0] if chain else 'the LLM'}) is switched off for this run. The chain moves to the next model.", {"chaos": "llm", "fallback": "llm"})
            case = self.case_for(sc, use_memory, run, holder, as_of, mem_override, llm_override)
            room = None
            if chaos == "band":
                run.emit(path, "system", "system", "Drill: Band is unreachable (simulated outage). The same four agents run in-process; the hand-offs are identical.", {"chaos": "band", "fallback": "band"})
            elif use_memory and self.band:
                try:
                    room = BandRoom(self.band, f"SiteMemory {run.alarm['id']} {sc['machine_id']} {sc['code']}")
                    run.transport[path] = "band"
                    run.emit(path, "system", "system", f"Band room created ({room.room_id[:8]}): Dispatcher, Diagnostician, Parts and Verifier joined.")
                except Exception as exc:
                    run.emit(path, "system", "system", f"Band unreachable ({str(exc)[:120]}). Running the same four agents in-process.")
            elif use_memory:
                run.emit(path, "system", "system", "Band is not configured: the same four agents run in-process.")
            ctx = Ctx(run, path, case, room)
            ctx.watch = mem_override
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
        ctx.current = "dispatcher"
        d = self.dispatcher.decide(case)
        led = d.get("ledger")
        text = f"{'REMOTE FIX' if d['decision'] == 'REMOTE_FIX' else 'SEND A TECHNICIAN'}. {d['rationale']}" + (f" Action: {d['remote_action']}." if d["remote_action"] else "")
        ctx.say("dispatcher", text, "msg", d, i)
        ctx.hand("dispatcher", "diagnostician", "Alarm needs a diagnosis" + (" (remote step queued first)" if d["decision"] == "REMOTE_FIX" else ""), {"alarm": case.alarm})

        i = ctx.mark()
        ctx.current = "diagnostician"
        diag = self.diagnostician.diagnose(case)
        ctx.say("diagnostician", self._diag_text(diag), "msg", diag, i)
        ctx.hand("diagnostician", "parts", f"Diagnosis: {diag['causes'][0]['fix']}", {"top": diag["causes"][0]})

        i = ctx.mark()
        ctx.current = "parts"
        parts = self.parts.plan(case, diag)
        ctx.say("parts", self._parts_text(parts), "msg", parts, i)
        ctx.hand("parts", "verifier", "Plan ready for verification", {"carry": [p["part"] for p in parts["carry"]]})

        rounds = []
        for rnd in range(3):
            i = ctx.mark()
            ctx.current = "verifier"
            ctx.run.emit(ctx.path, "verifier", "scan", f"Round {rnd + 1}: reading {len(case.visits)} raw visit records and {len(case.alarms)} alarm records dated before this alarm. No model, no summaries.",
                         {"visits": len(case.visits), "alarms": len(case.alarms), "round": rnd + 1, "as_of": case.as_of or "today"})
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
                ctx.current = "diagnostician"
                hint = next((x.get("alternative") for x in v["vetoes"] if x.get("alternative")), None)
                diag = self.diagnostician.diagnose(case, feedback_text(v["vetoes"], "diagnostician"), prior=diag, hint=hint)
                ctx.say("diagnostician", "Revised. " + self._diag_text(diag), "revise", diag, i)
                i = ctx.mark()
                ctx.current = "parts"
                parts = self.parts.plan(case, diag, feedback_text(v["vetoes"], "parts"))
                ctx.say("parts", "Re-planned for the revised diagnosis. " + self._parts_text(parts), "revise", parts, i)
            elif any(x["target"] == "parts" for x in v["vetoes"]):
                ctx.hand("verifier", "parts", "Vetoed: please revise", {"vetoes": v["vetoes"]})
                i = ctx.mark()
                ctx.current = "parts"
                parts = self.parts.plan(case, diag, feedback_text(v["vetoes"], "parts"))
                ctx.say("parts", "Revised. " + self._parts_text(parts), "revise", parts, i)
            else:
                break
        plan = {"dispatch": d, "diagnosis": diag, "parts": parts, "verifier": {"rounds": [{"vetoes": r["vetoes"], "approvals": r["approvals"]} for r in rounds],
                "vetoes": [x for r in rounds for x in r["vetoes"]], "revised": len(rounds) > 1}}
        i = ctx.mark()
        ctx.current = "technician"
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
        drop_vetoed(diag, parts, vetoes)

    def _brief(self, case: Case, plan: dict) -> dict:
        diag, parts, top = plan["diagnosis"], plan["parts"], plan["diagnosis"]["causes"][0]
        avoid = []
        if case.use_memory:
            for c in diag["causes"][1:]:
                pass
            for vt in plan["verifier"]["vetoes"]:
                real = [r for r in vt["reasons"] if "contain no attempt" not in r and "No visit on comparable" not in r]
                if real and vt["item"] not in " ".join(avoid):   # a vetoed generic placeholder is not advice worth showing a technician
                    avoid.append(f"{vt['item']}: " + real[0])
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
