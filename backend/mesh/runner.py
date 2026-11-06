"""Runs an alarm through the four agents, handing work over in a Band room (or in-process if Band
is not configured or unreachable). Every step is emitted as an event the UI streams live."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Callable

from .band import BandError, BandRoom, load_clients
from .records import MISSIONS, outcome_record, parts_record, seed_records, visit_record
from .roles import Diagnostician, Dispatcher, FieldAssistant, PartsAgent

log = logging.getLogger("sitememory.mesh")

LABELS = {"feed": "Alarm feed", "dispatcher": "Dispatcher", "diagnostician": "Diagnostician",
          "parts": "Parts agent", "field": "Field assistant", "system": "System"}


class Run:
    def __init__(self, alarm: dict):
        self.id = uuid.uuid4().hex[:10]
        self.alarm = alarm
        self.events: list[dict] = []
        self.status = "running"
        self.result: dict = {}
        self.transport = "local"
        self.band_room: BandRoom | None = None
        self.cond = threading.Condition()
        self.started = datetime.now().isoformat(timespec="seconds")

    def emit(self, sender: str, to: str | None, kind: str, text: str, payload: dict | None = None,
             memories: list | None = None, transport: str | None = None) -> dict:
        ev = {"n": len(self.events), "t": time.time(), "from": sender, "from_label": LABELS.get(sender, sender),
              "to": to, "to_label": LABELS.get(to or "", ""), "kind": kind, "text": text, "payload": payload or {},
              "memories": memories or [], "transport": transport or self.transport}
        with self.cond:
            self.events.append(ev)
            self.cond.notify_all()
        return ev

    def finish(self, status: str, result: dict | None = None) -> None:
        with self.cond:
            self.status = status
            if result is not None:
                self.result = result
            self.cond.notify_all()

    def public(self) -> dict:
        return {"id": self.id, "alarm": self.alarm, "status": self.status, "transport": self.transport,
                "started": self.started, "events": self.events, "result": self.result}


class Mesh:
    def __init__(self, store, agent, memories: dict, llm, belief_provider: Callable | None = None,
                 band_clients: dict | None = None):
        self.store, self.agent, self.memories = store, agent, memories
        self.roles = {"dispatcher": Dispatcher(memories["dispatcher"], llm, store),
                      "diagnostician": Diagnostician(memories["diagnostician"], llm, store),
                      "parts": PartsAgent(memories["parts"], llm, store),
                      "field": FieldAssistant(memories["field"], llm, store, agent)}
        self.beliefs = belief_provider or (lambda machine, as_of=None: ("", []))
        self.band = band_clients if band_clients is not None else load_clients()
        self.runs: dict[str, Run] = {}
        self.job_alarm: dict[str, dict] = {}  # job id -> alarm that produced it (to teach the dispatcher the outcome)

    # ----------------------------------------------------------------------- info
    def status(self) -> dict:
        return {"band": "configured" if self.band else "not configured (in-process fallback)",
                "banks": {r: getattr(m, "bank_id", f"local:{r}") for r, m in self.memories.items()},
                "backend": self.memories["field"].name}

    # ----------------------------------------------------------------------- seeding
    def seed_banks(self, state_get, state_set) -> dict:
        recs = seed_records(self.store)
        done = {}
        for role, records in recs.items():
            mem = self.memories[role]
            key = f"mesh_seeded_{getattr(mem, 'bank_id', 'local')}_{role}_{len(records)}"
            if state_get().get(key):
                continue
            if mem.name == "local" and mem.count() >= len(records):
                continue
            mem.retain_many(records)
            state_set(**{key: len(records)})
            done[role] = len(records)
        return done

    # ----------------------------------------------------------------------- run
    def start(self, alarm: dict) -> Run:
        run = Run(alarm)
        self.runs[run.id] = run
        for old in list(self.runs)[:-30]:
            self.runs.pop(old, None)
        threading.Thread(target=self._safe_flow, args=(run,), daemon=True, name=f"mesh-{run.id}").start()
        return run

    def get(self, run_id: str) -> Run | None:
        return self.runs.get(run_id)

    def _safe_flow(self, run: Run) -> None:
        try:
            self._flow(run)
        except Exception as exc:
            log.exception("mesh run failed")
            run.emit("system", None, "error", f"The run stopped: {exc}")
            run.finish("error")

    def _job_for(self, alarm: dict, machine: dict) -> dict:
        if alarm.get("job_id"):
            try:
                return self.store.job(alarm["job_id"])
            except Exception:
                pass
        return {"job_id": f"AL-{alarm['id']}", "date": alarm["ts"][:10], "machine_id": machine["id"],
                "site_id": machine["site_id"], "technician_id": "T-06",
                "symptom": f"Alarm {alarm['code']}: {alarm['description']}. Readings {alarm['readings']}.",
                "priority": "High" if alarm["severity"] != "minor" else "Medium", "reported_by": "BMS alarm feed"}

    def _hand(self, run: Run, sender: str, to: str, text: str, payload: dict, memories: list | None = None) -> dict:
        """Hand work to the next agent. In Band mode the handoff is a real Band message the receiver reads back."""
        transport = run.transport
        if run.band_room:
            try:
                got = run.band_room.deliver(sender, to, text, payload)
                payload = got["payload"]
                transport = "band"
                run.emit(sender, to, "handoff", text, payload, memories, "band")
                return payload
            except BandError as exc:
                run.band_room = None
                run.transport = "local"
                run.emit("system", None, "system", f"Band unreachable ({str(exc)[:140]}). Continuing in-process so the demo keeps running.")
        run.emit(sender, to, "handoff", text, payload, memories, "local")
        return payload

    def _flow(self, run: Run) -> None:
        a = run.alarm
        m = self.store.machine(a["machine_id"])
        s = self.store.site(m["site_id"])
        job = self._job_for(a, m)
        self.job_alarm[job["job_id"]] = a
        run.emit("feed", "dispatcher", "alarm",
                 f"{a['code']} on {m['id']} ({m['model']}) at {s['name']}: {a['description']}. Readings: "
                 + ", ".join(f"{k}={v}" for k, v in a["readings"].items()) + ".", {"alarm": a})

        if self.band:
            try:
                run.band_room = BandRoom(self.band, f"SiteMemory {a['id']} {m['id']} {a['code']}")
                run.transport = "band"
                run.emit("system", None, "system", f"Band room created ({run.band_room.room_id[:8]}). All four agents joined.", transport="band")
            except Exception as exc:
                run.band_room = None
                run.emit("system", None, "system", f"Band unreachable ({str(exc)[:140]}). Running the same agents in-process.")
        else:
            run.emit("system", None, "system", "Band is not configured: running the same four agents in-process.")

        # 1 - Dispatcher
        run.emit("dispatcher", None, "status", "Recalling past alarms and remote-fix outcomes from its own memory bank…")
        d = self.roles["dispatcher"].decide(a, m, s)
        led = d["ledger"]
        if d["decision"] == "REMOTE_FIX":
            msg = (f"REMOTE FIX. {d['rationale']} Action: {d['remote_action']}. "
                   f"Ledger: this remote action cleared {led['cleared']} of {led['attempts']} similar alarms.")
            run.emit("dispatcher", None, "decision", msg, d, d["memories"])
            self._hand(run, "dispatcher", "field",
                       f"Remote fix queued for {m['id']} ({a['code']}): {d['remote_action']}. Re-escalate if it returns within 30 minutes.",
                       {"alarm_id": a["id"], "action": d["remote_action"]})
            run.emit("field", None, "result", f"Logged: remote action queued for {m['id']}, no technician dispatched. "
                     "If the alarm returns within 30 minutes it escalates to a visit.", {"decision": d})
            run.finish("done", {"decision": "REMOTE_FIX", "dispatcher": d, "alarm": a})
            return
        msg = (f"SEND TECHNICIAN. {d['rationale']} Ledger: remote action cleared {led['cleared']} of {led['attempts']} similar alarms.")
        run.emit("dispatcher", None, "decision", msg, d, d["memories"])
        self._hand(run, "dispatcher", "diagnostician", f"Technician needed for {m['id']} ({a['code']}). Please diagnose.", {"alarm": a, "job": job})

        # 2 - Diagnostician
        beliefs_text, belief_list = self.beliefs(m)
        run.emit("diagnostician", None, "status", "Recalling this machine, the same model elsewhere and the site from its own memory bank…")
        dg = self.roles["diagnostician"].diagnose(a, job, m, s, beliefs_text)
        dg["beliefs"] = belief_list
        cite = "; ".join(f"{e['job_id']} ({e['date']}): {e['fact']}" for e in dg["evidence"]) or "no past visits to cite"
        run.emit("diagnostician", None, "decision",
                 f"Root cause ({dg['confidence']} confidence): {dg['root_cause']} Evidence: {cite}."
                 + (f" Already failed: {'; '.join(dg['already_failed'])}." if dg["already_failed"] else "")
                 + "".join(f" BELIEF UPDATED: {b['text']}" for b in belief_list), dg, dg["memories"])
        self._hand(run, "diagnostician", "parts", f"Diagnosis: {dg['root_cause']} Which parts should go in the van?",
                   {"root_cause": dg["root_cause"], "confidence": dg["confidence"], "already_failed": dg["already_failed"]})

        # 3 - Parts agent
        run.emit("parts", None, "status", "Recalling which parts fixed this model before, and checking van and warehouse stock…")
        pt = self.roles["parts"].plan(a, dg, m)
        carry = "; ".join(f"{c['qty']}× {c['part']} ({c['stock']})" for c in pt["carry"]) or "no specific parts"
        run.emit("parts", None, "decision", f"Carry: {carry}." + (f" Flags: {' '.join(pt['flags'])}" if pt["flags"] else ""), pt, pt["memories"])
        self._hand(run, "parts", "field", f"Parts plan ready: {carry}. Please brief the technician.",
                   {"carry": pt["carry"], "flags": pt["flags"]})

        # 4 - Field assistant
        run.emit("field", None, "status", "Writing the technician briefing from its own memory plus the team's hand-off…")
        br = self.roles["field"].brief(job, dg, pt, beliefs_text)
        b = br["briefing"]
        run.emit("field", None, "result", f"Briefing for {self.store.tech(job['technician_id'])['name']}: {b['headline']} "
                 f"Do first: {'; '.join(b['do_first'][:2])}. Bring: {', '.join(b['bring'][:3])}.", {"briefing": b}, br["memories"])
        run.finish("done", {"decision": "SEND_TECHNICIAN", "job": job, "dispatcher": d, "diagnosis": dg, "parts": pt,
                            "briefing": b, "alarm": a, "beliefs": belief_list})

    # ----------------------------------------------------------------------- learning after the visit
    def record_visit(self, visit: dict) -> dict:
        """Field assistant records the visit; the other agents learn their slice of it."""
        m = self.store.machine(visit["machine_id"])
        s = self.store.site(m["site_id"])
        t = self.store.tech(visit["technician_id"])
        done = {}
        try:
            r = visit_record(visit, m, s, t)
            self.memories["diagnostician"].retain(r["text"], r["tags"], r["date"], r["doc_id"], r["meta"])
            done["diagnostician"] = True
            p = parts_record(visit, m, self.store.all_visits())
            if p:
                self.memories["parts"].retain(p["text"], p["tags"], p["date"], p["doc_id"], p["meta"])
                done["parts"] = True
            alarm = self.job_alarm.get(visit.get("job_id", "").split("-V")[0]) or self.job_alarm.get(visit.get("job_id"))
            if alarm:
                o = outcome_record(alarm, m, s, visit)
                self.memories["dispatcher"].retain(o["text"], o["tags"], o["date"], o["doc_id"], o["meta"])
                done["dispatcher"] = True
        except Exception as exc:
            log.warning("fan-out of visit failed: %s", str(exc)[:160])
        return done


class AlarmFeed:
    """Replays live alarm scenarios on a timer; each one starts a mesh run automatically."""

    def __init__(self, mesh: Mesh, scenarios: list[dict]):
        self.mesh, self.scenarios = mesh, scenarios
        self.fired: list[dict] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def fire(self, alarm_id: str) -> Run:
        sc = next((x for x in self.scenarios if x["id"] == alarm_id), None)
        if sc is None:
            raise KeyError(alarm_id)
        alarm = {**sc, "id": f"{sc['id']}-{len(self.fired) + 1}", "remote_action": None, "remote_result": "none",
                 "dispatched": False, "ts": datetime.now().isoformat(timespec="seconds")}
        run = self.mesh.start(alarm)
        self.fired.append({"alarm": alarm, "run_id": run.id, "headline": sc.get("headline", alarm["description"])})
        return run

    def start(self, interval: float = 45.0) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            for sc in self.scenarios:
                if self._stop.is_set():
                    return
                self.fire(sc["id"])
                if self._stop.wait(interval):
                    return

        self._thread = threading.Thread(target=loop, daemon=True, name="alarm-feed")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def state(self) -> dict:
        return {"running": bool(self._thread and self._thread.is_alive() and not self._stop.is_set()), "fired": self.fired[-20:]}
