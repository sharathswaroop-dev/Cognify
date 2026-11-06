"""The four agents. Each owns a Hindsight bank, recalls from it, asks the LLM for a structured decision,
and validates that decision against what it actually recalled (no invented evidence)."""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor

from memory import Memory, slug

log = logging.getLogger("sitememory.roles")
JOB_ID = re.compile(r"\bJ-\d{3,5}\b")


def mem_view(role: str, label: str, mems: list[Memory], limit: int = 4) -> list[dict]:
    """What the UI shows for 'which memories did this agent use'."""
    return [{"agent": role, "level": label, "text": m.text[:260], "date": m.date, "tags": m.tags[:4]}
            for m in mems[:limit]]


class Role:
    role = ""
    title = ""

    def __init__(self, memory, llm, store):
        self.memory, self.llm, self.store = memory, llm, store

    def recall_many(self, jobs: list[tuple[str, str, list[str], int]]) -> dict[str, list[Memory]]:
        """Run several recalls in parallel. jobs = [(label, query, tags, limit)]."""
        def one(j):
            label, q, tags, limit = j
            try:
                return label, self.memory.recall(q, tags, limit=limit)
            except Exception as exc:
                log.warning("%s recall '%s' failed: %s", self.role, label, str(exc)[:120])
                return label, []
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            return dict(pool.map(one, jobs))


# ------------------------------------------------------------------------------------ dispatcher
DISPATCH_PROMPT = """You are the Dispatcher agent at a field-service company. A machine alarm just arrived.
Decide REMOTE_FIX (an operator can clear it remotely) or SEND_TECHNICIAN.
Use ONLY the memories and the ledger below. Prefer REMOTE_FIX only when memory shows the same remote action cleared
this kind of alarm in comparable conditions. If the remote fix usually failed, or readings point at hardware, send a technician.
Return ONLY JSON: {"decision":"REMOTE_FIX"|"SEND_TECHNICIAN","remote_action":string|null,"confidence":"low"|"medium"|"high",
"rationale":string (<=40 words),"evidence":[string,...] (max 3, each quoting something from memory or the ledger)}"""

REMOTE_ACTIONS = {"U4": "Remote power-cycle of the indoor group via BMS", "HT": "Remote setpoint and fan-speed adjustment via BMS",
                  "HP": "Remote chiller restart via BMS", "LC": "Remote setpoint reset via BMS",
                  "E3": "Remote fault reset via controller", "L8": "Remote fault reset via controller"}


def ledger(alarms: list[dict], code: str, units: int | None = None) -> dict:
    """Exact tally of remote-fix outcomes for this alarm code (the LLM must not count)."""
    rows = [a for a in alarms if a["code"] == code and a.get("remote_action")]
    if code == "U4" and units is not None:
        multi = units >= 3
        rows = [a for a in rows if (a["readings"].get("units_offline", 1) >= 3) == multi]
    ok = sum(1 for a in rows if a["remote_result"] == "cleared")
    return {"code": code, "attempts": len(rows), "cleared": ok, "failed": len(rows) - ok,
            "rate": round(ok / len(rows), 2) if rows else None}


class Dispatcher(Role):
    role, title = "dispatcher", "Dispatcher"

    def decide(self, alarm: dict, machine: dict, site: dict) -> dict:
        fam = f"family:{slug(machine['model_family'])}"
        q = f"alarm {alarm['code']} {alarm['description']} on {machine['model']} {machine['type']}"
        got = self.recall_many([("This machine's alarms", q, [f"machine:{machine['id']}"], 4),
                                (f"Code {alarm['code']} elsewhere", q, [f"code:{alarm['code']}"], 6)])
        mems = got["This machine's alarms"] + [m for m in got[f"Code {alarm['code']} elsewhere"]
                                              if f"machine:{machine['id']}" not in m.tags]
        led = ledger(self.store.alarm_log(), alarm["code"], alarm["readings"].get("units_offline"))
        user = (f"ALARM {alarm['id']}: machine {machine['id']} ({machine['model']}, {machine['type']}, installed "
                f"{machine['installed']}) at {site['name']}. Code {alarm['code']}: {alarm['description']}. "
                f"Severity {alarm['severity']}. Readings: {alarm['readings']}.\n\n"
                f"LEDGER (exact tally of remote attempts for code {alarm['code']}"
                f"{' in the same comm-fault pattern' if alarm['code'] == 'U4' else ''}): {led}\n\n"
                "MEMORIES:\n" + "\n---\n".join(m.cited() for m in mems))
        d = self.llm.json_chat(DISPATCH_PROMPT, user, required=("decision", "rationale")) or {}
        decision = str(d.get("decision", "")).upper()
        notes = []
        # Safety rails that do not depend on the LLM: never promise a remote fix that memory says does not work.
        usable = bool(REMOTE_ACTIONS.get(alarm["code"])) and led["attempts"] >= 3 and (led["rate"] or 0) >= 0.5
        if decision not in ("REMOTE_FIX", "SEND_TECHNICIAN"):
            decision = "REMOTE_FIX" if usable else "SEND_TECHNICIAN"
            notes.append("LLM unavailable: decided from the ledger alone.")
        if decision == "REMOTE_FIX" and not usable:
            decision = "SEND_TECHNICIAN"
            notes.append(f"Guard: remote fix cleared only {led['cleared']}/{led['attempts']} times, so a technician goes.")
        if decision == "SEND_TECHNICIAN" and usable and not d:
            decision = "REMOTE_FIX"
        action = (d.get("remote_action") or REMOTE_ACTIONS.get(alarm["code"])) if decision == "REMOTE_FIX" else None
        evidence = [str(e) for e in (d.get("evidence") or [])][:3] or [
            f"Ledger: remote action cleared code {alarm['code']} {led['cleared']} of {led['attempts']} times."]
        return {"decision": decision, "remote_action": action, "confidence": str(d.get("confidence") or "medium").lower(),
                "rationale": " ".join([str(d.get("rationale") or "")] + notes).strip(), "evidence": evidence,
                "ledger": led, "memories": mem_view(self.role, "Alarm history", mems, 5)}


# ------------------------------------------------------------------------------------ diagnostician
DIAG_PROMPT = """You are the Diagnostician agent for an HVAC service company. Give the most likely root cause for the fault.
Use ONLY the memories below (past visits). Every item in "evidence" must cite a job id that appears in the memories
(format J-1234) with the date and the fact it shows. If a lesson below is marked CORRECTED, follow the correction.
Return ONLY JSON: {"root_cause":string,"confidence":"low"|"medium"|"high","evidence":[{"job_id":string,"date":string,"fact":string}] (max 4),
"already_failed":[string] (fixes memory says did NOT work for this fault, max 3),"next_checks":[string] (max 3)}"""


class Diagnostician(Role):
    role, title = "diagnostician", "Diagnostician"

    def diagnose(self, alarm: dict, job: dict, machine: dict, site: dict, beliefs_text: str = "") -> dict:
        fam = f"family:{slug(machine['model_family'])}"
        q = f"{machine['model']} {machine['type']}: {job['symptom']}; alarm {alarm['code']} {alarm['description']}"
        got = self.recall_many([("This machine", q, [f"machine:{machine['id']}"], 5),
                                ("Same model, other sites", q, [fam], 8),
                                ("This site", f"known issues and quirks at {site['name']}", [f"site:{site['id']}"], 3)])
        family = [m for m in got["Same model, other sites"] if f"machine:{machine['id']}" not in m.tags][:5]
        mems = got["This machine"] + family + got["This site"]
        reflection = None
        try:
            reflection = self.memory.reflect(
                f"For a {machine['model']} showing '{job['symptom']}' (alarm {alarm['code']}): what is the most likely root cause, "
                f"what has failed before, and does it depend on how old the unit is?", [f"machine:{machine['id']}", fam])
        except Exception as exc:
            log.warning("diagnostician reflect failed: %s", str(exc)[:120])
        user = (f"FAULT: machine {machine['id']} {machine['model']} ({machine['type']}, installed {machine['installed']}) at "
                f"{site['name']}. Ticket: {job['symptom']}. Alarm {alarm['code']}: {alarm['description']}, readings {alarm['readings']}.\n\n"
                + (f"{beliefs_text}\n\n" if beliefs_text else "")
                + "MEMORIES - THIS MACHINE:\n" + "\n---\n".join(m.cited() for m in got["This machine"])
                + "\n\nMEMORIES - SAME MODEL ELSEWHERE:\n" + "\n---\n".join(m.cited() for m in family)
                + ("\n\nLESSONS (Hindsight reflect):\n" + reflection if reflection else ""))
        d = self.llm.json_chat(DIAG_PROMPT, user, required=("root_cause", "evidence")) or {}
        seen = set(JOB_ID.findall(user))
        ev = []
        for e in d.get("evidence") or []:
            if isinstance(e, dict) and e.get("job_id") in seen:  # drop citations the memories do not support
                ev.append({"job_id": e["job_id"], "date": str(e.get("date", "")), "fact": str(e.get("fact", ""))[:200]})
        out = {"root_cause": str(d.get("root_cause") or "No history to diagnose from: run standard checks."),
               "confidence": str(d.get("confidence") or "low").lower(), "evidence": ev[:4],
               "already_failed": [str(x) for x in (d.get("already_failed") or [])][:3],
               "next_checks": [str(x) for x in (d.get("next_checks") or [])][:3],
               "reflection": reflection,
               "memories": (mem_view(self.role, "This machine", got["This machine"], 3)
                            + mem_view(self.role, "Same model", family, 3) + mem_view(self.role, "Site", got["This site"], 1))}
        if not d:
            out["confidence"] = "low"
        return out


# ------------------------------------------------------------------------------------ parts
PARTS_PROMPT = """You are the Parts agent. Decide which parts the technician should carry for this fault.
Use ONLY the diagnosis, the memories (parts used on past jobs) and the stock list. Choose part names exactly as written in the stock list
when a stock entry fits. Mention a part that was missing on a past first visit and forced a second trip.
Return ONLY JSON: {"carry":[{"part":string,"qty":number,"reason":string}] (max 4),"also_consider":[string] (max 2)}"""


class PartsAgent(Role):
    role, title = "parts", "Parts agent"

    def plan(self, alarm: dict, diag: dict, machine: dict) -> dict:
        fam = f"family:{slug(machine['model_family'])}"
        q = f"parts needed for {machine['model']}: {diag['root_cause']}"
        got = self.recall_many([("Parts used on this model", q, [fam], 8), ("Parts used on this machine", q, [f"machine:{machine['id']}"], 4)])
        mems = got["Parts used on this machine"] + [m for m in got["Parts used on this model"] if f"machine:{machine['id']}" not in m.tags]
        stock = self.store.stock
        user = (f"DIAGNOSIS: {diag['root_cause']} (confidence {diag['confidence']}). Already failed: {diag['already_failed']}.\n"
                f"MACHINE: {machine['model']} installed {machine['installed']}.\n\nMEMORIES:\n" + "\n---\n".join(m.cited() for m in mems[:8])
                + "\n\nSTOCK LIST:\n" + "\n".join(f"- {s['part']} (van {s['van']}, warehouse {s['warehouse']})" for s in stock))
        d = self.llm.json_chat(PARTS_PROMPT, user, required=("carry",)) or {}
        carry, flags = [], []
        for c in d.get("carry") or []:
            if not isinstance(c, dict) or not c.get("part"):
                continue
            s = self._find(str(c["part"]))
            qty = int(c.get("qty") or 1)
            status = "unknown part (not in stock list)"
            if s:
                c["part"] = s["part"]
                if s["van"] >= qty:
                    status = f"on the van ({s['van']})"
                    if s["van"] <= 1:
                        flags.append(f"Only {s['van']} {s['part']} on the van: restock after this job.")
                elif s["warehouse"] >= qty:
                    status = f"NOT on the van: collect {qty} from the warehouse ({s['warehouse']} in stock)"
                    flags.append(f"Collect {s['part']} from the warehouse before leaving.")
                else:
                    status = f"OUT OF STOCK: order now, lead time {s['lead_time_days']} days"
                    flags.append(f"{s['part']} is out of stock; lead time {s['lead_time_days']} days.")
            carry.append({"part": c["part"], "qty": qty, "reason": str(c.get("reason", ""))[:160], "stock": status})
        return {"carry": carry[:4], "also_consider": [str(x) for x in (d.get("also_consider") or [])][:2], "flags": flags,
                "memories": mem_view(self.role, "Parts history", mems, 4)}

    def _find(self, name: str) -> dict | None:
        n = name.lower()
        for s in self.store.stock:
            code = re.findall(r"\(([A-Z0-9-]{5,})\)", s["part"])
            if s["part"].lower() == n or n in s["part"].lower() or s["part"].lower() in n or any(c.lower() in n for c in code):
                return s
        return None


# ------------------------------------------------------------------------------------ field assistant
class FieldAssistant(Role):
    role, title = "field", "Field assistant"

    def __init__(self, memory, llm, store, agent):
        super().__init__(memory, llm, store)
        self.agent = agent  # the original briefing agent: recall at machine/model/site level, reflect, brief

    def brief(self, job: dict, diag: dict, parts: dict, beliefs_text: str = "") -> dict:
        extra = (f"TEAM HAND-OFF\nDiagnostician: {diag['root_cause']} (confidence {diag['confidence']}). "
                 f"Already failed: {diag['already_failed']}. Next checks: {diag['next_checks']}.\n"
                 f"Parts agent: carry {[(c['part'], c['stock']) for c in parts['carry']]}. Flags: {parts['flags']}.\n"
                 + (beliefs_text or ""))
        res = self.agent.briefing(job, True, extra=extra)
        res["memories"] = [{"agent": self.role, "level": m["level"], "text": m["text"][:260], "date": m.get("date"),
                            "tags": (m.get("tags") or [])[:4]} for m in res["memories_used"][:6]]
        return res
