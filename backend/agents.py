"""Dispatcher, Diagnostician, Parts agent and Verifier.

Division of labour:
  * Dispatcher  decides remote fix vs technician. Remote fixes are limited to reset, setpoint and reading logs, and a remote fix that already
                failed on this machine is never repeated. The decision is rule-based over the alarm log; the LLM only phrases the reason.
  * Diagnostician  recalls and reflects, then proposes causes. n, verified successes, success rate and interval are computed from the raw
                visit records and shown; n < 5 is labelled a weak signal; confidence is earned by verified outcomes, not by how it reads.
  * Parts agent  proposes parts from past visits and checks stock. It does not judge whether the evidence is good enough.
  * Verifier  sees ONLY raw visit and alarm records (never the other agents' reasoning), runs deterministic checks, and can veto.
              A vetoed agent revises and the Verifier checks again.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import beliefs
import evidence as ev
from memory import slug

log = logging.getLogger("sitememory.agents")
ALLOWED_REMOTE = ("reset", "setpoint", "read_log")
JOB_ID = re.compile(r"\bJ-\d{3,5}\b")
CODE = re.compile(r"\(([A-Z0-9][A-Z0-9-]{4,})\)")


@dataclass
class Case:
    """One alarm to work, as of a date. visits/alarms are the raw records known at that date (nothing from the future)."""
    alarm: dict
    machine: dict
    site: dict
    job: dict
    store: Any
    llm: Any
    memory: Any                      # TracedMemory or NullMemory
    use_memory: bool
    as_of: str | None = None
    visits: list = field(default_factory=list)
    alarms: list = field(default_factory=list)

    @property
    def family(self) -> str:
        return self.machine["model_family"]


def part_code(name: str) -> str | None:
    m = CODE.search(name or "")
    return m.group(1) if m else None


def _facts(case: Case) -> str:
    m, a = case.machine, case.alarm
    return (f"Machine {m['id']}: {m['model']} ({m['type']}), installed {m['installed']}, at {case.site['name']}, {m['location']}.\n"
            f"Alarm {a.get('code', '')}: {a.get('description', '')}. Readings: {a.get('readings', {})}. Ticket: {case.job['symptom']}")


def _cited(mems) -> str:
    return "\n---\n".join(m.cited() for m in mems) or "(no memories)"


def scoped(case: Case, fk: str):
    """Attempts of one fix on units comparable to this one. When the record splits by hardware generation (a belief exists for the fix),
    stats are computed only on this unit's generation, so a fix that fails on newer units does not drag down its record on older ones."""
    att_all = ev.attempts(case.visits, case.store.machine, case.as_of).get(case.family, {}).get(fk, [])
    bl = next((b for b in beliefs.analyse(case.visits, case.store.machine, case.as_of) if b["family"] == case.family and b["fix_key"] == fk), None)
    if bl and bl["cohort_from"]:
        y = bl["cohort_from"]
        newer = case.machine["installed"] >= y
        return [a for a in att_all if (a["installed"] >= y) == newer], f"{case.family} units installed {'from' if newer else 'before'} {y}", bl, newer
    return att_all, f"{case.family}, all units", bl, False


# ===================================================================== Dispatcher
def ledger(alarms: list[dict], code: str, units: int | None = None) -> dict:
    rows = [a for a in alarms if a["code"] == code and a.get("remote_type") in ALLOWED_REMOTE]
    if code == "U4" and units is not None:      # one unit offline is usually a glitch; several is a wiring fault
        rows = [a for a in rows if (a["readings"].get("units_offline", 1) >= 3) == (units >= 3)]
    ok = sum(1 for a in rows if a["remote_result"] == "cleared")
    return {"code": code, "attempts": len(rows), "cleared": ok, "failed": len(rows) - ok, "rate": round(ok / len(rows), 2) if rows else None}


def remote_type_for(alarms: list[dict], code: str) -> str | None:
    from collections import Counter
    c = Counter(a["remote_type"] for a in alarms if a["code"] == code and a.get("remote_type") in ALLOWED_REMOTE)
    return c.most_common(1)[0][0] if c else None


def recent_remote_failure(alarms: list[dict], machine_id: str, rtype: str, as_of: str | None) -> dict | None:
    """A remote fix of this type that already failed on this machine in the last 30 days: never repeat it."""
    from datetime import date, timedelta
    end = date.fromisoformat((as_of or ev.NOW)[:10])
    for a in sorted(alarms, key=lambda x: x["ts"], reverse=True):
        if a["machine_id"] == machine_id and a.get("remote_type") == rtype and a["remote_result"] == "failed":
            if end - timedelta(days=30) <= date.fromisoformat(a["ts"][:10]) < end:
                return a
    return None


class Dispatcher:
    name = "dispatcher"

    def decide(self, case: Case) -> dict:
        a = case.alarm
        rtype = remote_type_for(case.alarms or case.store.alarms, a["code"]) or remote_type_for(case.store.alarms, a["code"])
        if not case.use_memory:   # no history: the cheapest generic step first, because nothing says it will not work
            if rtype:
                return {"decision": "REMOTE_FIX", "remote_type": "reset", "remote_action": "Remote reset via controller", "blocked": None, "ledger": None,
                        "rationale": "No alarm history is available, so the generic first step is a remote reset.", "citations": []}
            return {"decision": "SEND_TECHNICIAN", "remote_type": None, "remote_action": None, "blocked": None, "ledger": None,
                    "rationale": "No remote option known for this alarm, and no history to say otherwise.", "citations": []}
        tags = [f"code:{a['code']}"]
        mems = case.memory.recall(f"alarm {a['code']} {a.get('description', '')} remote action result on {case.machine['model']}", tags, limit=5)
        mine = case.memory.recall(f"alarms and remote actions on machine {case.machine['id']}", [f"machine:{case.machine['id']}", "kind:alarm"], limit=3)
        led = ledger(case.alarms, a["code"], a["readings"].get("units_offline"))
        blocked = recent_remote_failure(case.alarms, case.machine["id"], rtype, case.as_of) if rtype else None
        usable = bool(rtype) and led["attempts"] >= 3 and (led["rate"] or 0) >= 0.5 and not blocked
        decision = "REMOTE_FIX" if usable else "SEND_TECHNICIAN"
        why = self._reason(case, decision, rtype, led, blocked, mems + mine)
        return {"decision": decision, "remote_type": rtype if usable else None,
                "remote_action": {"reset": "Remote reset via controller", "setpoint": "Remote setpoint / fan-speed adjustment", "read_log": "Read the controller log"}.get(rtype) if usable else None,
                "blocked": ({"alarm": blocked["id"], "date": blocked["ts"][:10], "type": rtype} if blocked else None), "ledger": led, "rationale": why,
                "citations": [m.ref() for m in (mems + mine) if m.ref()][:6]}

    def _reason(self, case, decision, rtype, led, blocked, mems) -> str:
        if blocked:
            base = f"A remote {rtype} already failed on this machine on {blocked['ts'][:10]}, so it is not repeated. Sending a technician."
        elif decision == "REMOTE_FIX":
            base = f"Remote {rtype} cleared {led['cleared']} of {led['attempts']} similar {case.alarm['code']} alarms, so it is worth trying first."
        elif rtype and led["attempts"] >= 3:
            base = f"Remote {rtype} cleared only {led['cleared']} of {led['attempts']} similar {case.alarm['code']} alarms. Sending a technician."
        elif rtype:
            base = f"Only {led['attempts']} similar alarms on record: not enough to trust a remote {rtype}. Sending a technician."
        else:
            base = "No remote reset, setpoint or log reading applies to this alarm. Sending a technician."
        return base


# ===================================================================== Diagnostician
DIAG_PROMPT = """You are the Diagnostician agent for an HVAC service company. Propose up to 3 likely root causes for this fault, each with the repair that fixes it.
Use ONLY the memories given. Each memory starts with [source JOB-ID, date]; cite those ids in "evidence_jobs". Prefer repairs that memory shows as
FIXED IT and later stable. A repair that DID NOT FIX IT is not a fix. If memory shows a fix stopped working on newer units, say so and do not propose it for a newer unit.
If there is no memory, say the cause is unknown and give generic checks.
Return ONLY JSON: {"causes":[{"cause":string,"fix":string (the repair, as a short past-tense action),"evidence_jobs":[string],"why":string (<=25 words)}]}"""


class Diagnostician:
    name = "diagnostician"

    def diagnose(self, case: Case, feedback: str = "", prior: dict | None = None) -> dict:
        m, fam = case.machine, f"family:{slug(case.machine['model_family'])}"
        recalled, reflection = [], None
        if case.use_memory and not feedback:
            q = f"{m['model']} {m['type']}: {case.job['symptom']}; alarm {case.alarm.get('code', '')} {case.alarm.get('description', '')}"
            with ThreadPoolExecutor(max_workers=3) as pool:
                f1 = pool.submit(case.memory.recall, q, [f"machine:{m['id']}"], 5)
                f2 = pool.submit(case.memory.recall, q, [fam], 8)
                f3 = pool.submit(case.memory.recall, f"access rules, contacts and quirks at {case.site['name']}", [f"site:{case.site['id']}"], 2)
                mine, family, site = f1.result(), [x for x in f2.result() if f"machine:{m['id']}" not in x.tags][:5], f3.result()
            recalled = mine + family
            try:
                reflection = case.memory.reflect(f"For a {m['model']} showing '{case.job['symptom']}': what is the most likely root cause, what has failed before, "
                                                 f"and does it depend on how old the unit is?", [f"machine:{m['id']}", fam])
            except Exception as exc:
                log.warning("reflect failed: %s", str(exc)[:100])
            site_notes = [x.text for x in site]
        elif prior:
            recalled, reflection, site_notes = prior.get("_recalled", []), prior.get("reflection"), prior.get("site_notes", [])
        else:
            site_notes = []
        user = (_facts(case) + "\n\nMEMORIES:\n" + _cited(recalled) + (f"\n\nLESSONS (Hindsight reflect):\n{reflection}" if reflection else "")
                + (f"\n\nVERIFIER FEEDBACK (address every point; propose causes whose fixes the raw records support):\n{feedback}" if feedback else ""))
        d = case.llm.json_chat(DIAG_PROMPT, user, required=("causes",)) if case.llm else None
        causes = []
        for c in ((d or {}).get("causes") or [])[:3]:
            if isinstance(c, dict) and c.get("fix"):
                causes.append({"cause": str(c.get("cause", ""))[:200], "fix": str(c["fix"])[:200], "why": str(c.get("why", ""))[:200],
                               "evidence_jobs": [j for j in (c.get("evidence_jobs") or []) if isinstance(j, str)][:6]})
        if not causes:
            causes = [{"cause": "Unknown: no usable history", "fix": "Run the standard checks and log everything you try", "why": "", "evidence_jobs": []}]
        out = {"causes": causes, "reflection": reflection, "site_notes": site_notes, "_recalled": recalled}
        self.enrich(case, out)
        return out

    @staticmethod
    def enrich(case: Case, out: dict) -> None:
        """n, verified successes, rate and interval for each proposed fix: computed from the raw visit records, never by the LLM."""
        for c in out["causes"]:
            if not case.use_memory:
                c["stats"], c["confidence"], c["stats_scope"] = {**ev.fix_stats([]), "rate": None}, "none", "no records"
                continue
            att, scope, _, _ = scoped(case, ev.fix_key(c["fix"]))
            c["stats"] = ev.fix_stats(att) if att else {**ev.fix_stats([]), "rate": None}
            c["confidence"], c["stats_scope"] = ev.confidence(c["stats"]), scope


# ===================================================================== Parts
PARTS_PROMPT = """You are the Parts agent. List the parts the technician should carry for this fault.
Include every part that past visits (memories below) used or named in connection with this kind of fault: you do not judge whether the evidence is good
enough, the Verifier does that. Use part names exactly as written in the stock list when one fits. Cite the job ids (shown as [source JOB-ID]) each part came from.
If there is no memory, list generic tools only.
Return ONLY JSON: {"carry":[{"part":string,"qty":number,"reason":string (<=15 words),"evidence_jobs":[string]}]} (max 5)"""


class PartsAgent:
    name = "parts"

    def plan(self, case: Case, diag: dict, feedback: str = "") -> dict:
        top = diag["causes"][0]
        mems = []
        if case.use_memory:
            q = f"parts used to fix {top['fix']} on {case.machine['model']}; parts replaced for {case.job['symptom']}"
            with ThreadPoolExecutor(max_workers=2) as pool:
                f1 = pool.submit(case.memory.recall, q, [f"family:{slug(case.family)}", "kind:visit"], 10)
                f2 = pool.submit(case.memory.recall, q, [f"machine:{case.machine['id']}", "kind:visit"], 4)
                mems = f2.result() + [x for x in f1.result() if x.ref() not in {y.ref() for y in f2.result()}]
        user = (_facts(case) + f"\nDiagnosis to prepare for: {top['cause']} (fix: {top['fix']}).\n\nMEMORIES:\n" + _cited(mems)
                + "\n\nSTOCK LIST:\n" + "\n".join(f"- {s['part']} (van {s['van']}, warehouse {s['warehouse']})" for s in case.store.stock)
                + (f"\n\nVERIFIER FEEDBACK (address every point):\n{feedback}" if feedback else ""))
        d = case.llm.json_chat(PARTS_PROMPT, user, required=("carry",)) if case.llm else None
        carry, flags = [], []
        for c in ((d or {}).get("carry") or [])[:5]:
            if not isinstance(c, dict) or not c.get("part"):
                continue
            s, qty = self._find(case.store, str(c["part"])), max(1, int(c.get("qty") or 1))
            item = {"part": s["part"] if s else str(c["part"])[:120], "qty": qty, "reason": str(c.get("reason", ""))[:140],
                    "evidence_jobs": [j for j in (c.get("evidence_jobs") or []) if isinstance(j, str)][:6], "stock": "not tracked (tool or consumable)"}
            if s:
                if s["van"] >= qty:
                    item["stock"] = f"on the van ({s['van']})"
                    if s["van"] <= 1:
                        flags.append(f"Only {s['van']} {s['part']} on the van: restock after this job.")
                elif s["warehouse"] >= qty:
                    item["stock"] = f"NOT on the van: collect {qty} from the warehouse ({s['warehouse']} in stock)"
                    flags.append(f"Collect {s['part']} from the warehouse before leaving.")
                else:
                    item["stock"] = f"OUT OF STOCK: order now, lead time {s['lead_time_days']} days"
                    flags.append(f"{s['part']} is out of stock (lead time {s['lead_time_days']} days).")
            carry.append(item)
        return {"carry": carry, "flags": flags, "_recalled": mems}

    @staticmethod
    def _find(store, name: str):
        n, code = name.lower(), part_code(name)
        for s in store.stock:
            sc = part_code(s["part"])
            if s["part"].lower() == n or (code and sc and code.lower() == sc.lower()) or n in s["part"].lower() or s["part"].lower() in n:
                return s
        return None


# ===================================================================== Verifier
class Verifier:
    """Sees only raw records. No LLM: every check is deterministic, so the same inputs always give the same verdict."""
    name = "verifier"

    def review(self, case: Case, dispatch: dict, diag: dict, parts: dict) -> dict:
        lv = ev.visit_levels(case.visits, case.as_of)
        by_job = {v["job_id"]: v for v in case.visits}
        vetoes, approvals = [], []
        # ---- dispatcher
        if dispatch["decision"] == "REMOTE_FIX":
            if dispatch["remote_type"] not in ALLOWED_REMOTE:
                vetoes.append({"target": "dispatcher", "item": dispatch["remote_action"], "reasons": [f"Remote action type {dispatch['remote_type']!r} is not allowed. Only reset, setpoint and reading logs."], "jobs": []})
            else:
                bad = recent_remote_failure(case.alarms, case.machine["id"], dispatch["remote_type"], case.as_of)
                if bad:
                    vetoes.append({"target": "dispatcher", "item": dispatch["remote_action"], "reasons": [f"A remote {dispatch['remote_type']} already failed on {case.machine['id']} on {bad['ts'][:10]} ({bad['id']})."], "jobs": [bad["id"]]})
                else:
                    approvals.append({"target": "dispatcher", "item": dispatch["remote_action"], "note": "Allowed action type; no recent failure of it on this machine."})
        # ---- diagnosis (the top cause must stand up; the others are shown but not relied on)
        top = diag["causes"][0]
        att, _scope, bl, newer = scoped(case, ev.fix_key(top["fix"]))
        if not case.visits:
            approvals.append({"target": "diagnostician", "item": top["fix"], "note": "No records to verify against."})
        else:
            reasons, jobs = [], []
            cited = top.get("evidence_jobs", [])
            supporting = []
            for j in cited:
                v = by_job.get(j)
                if v is None:
                    reasons.append(f"{j} is not in the visit records (or is dated after this alarm).")
                elif case.store.machine(v["machine_id"])["model_family"] != case.family:
                    reasons.append(f"{j} is on a different model family.")
                elif not any(a["result"] == "worked" and ev.fix_key(a["action"]) == ev.fix_key(top["fix"]) for a in v["actions"]):
                    reasons.append(f"{j} does not show '{top['fix']}' as a fix that worked.")
                elif lv.get(j, {}).get("level") == "suspected":
                    reasons.append(f"{j} is only a suspected outcome.")
                else:
                    supporting.append(j)
            if not att:
                reasons.append(f"The records contain no attempt of '{top['fix']}' on comparable {case.family} units.")
            else:
                st = ev.fix_stats(att)
                if bl and (bl["cohort_from"] is None or newer):
                    reasons.append(bl["text"].replace("Belief updated: ", "Recent evidence contradicts this lesson: "))
                    jobs += bl["recent"]["jobs"][-4:]
                elif bl is None and st["recent_n"] >= 3 and (st["recent_rate"] or 0) <= 0.25 and (st["rate"] or 0) >= 0.5:
                    reasons.append(f"Only {st['recent_verified']} of the last {st['recent_n']} attempts of this fix held, against {st['verified']} of {st['n']} overall.")
                if not supporting and cited:
                    reasons.append("None of the cited visits supports the claim.")
            if reasons:
                vetoes.append({"target": "diagnostician", "item": top["fix"], "reasons": reasons, "jobs": list(dict.fromkeys(jobs + [j for j in cited if j in by_job]))[:6]})
            else:
                st = ev.fix_stats(att)
                tag = "weak signal" if st["weak"] else f"{st['verified']} of {st['n']} verified"
                approvals.append({"target": "diagnostician", "item": top["fix"], "note": f"Every cited visit supports it ({tag})."})
        # ---- parts
        for p in parts["carry"]:
            code = part_code(p["part"])
            if not (code or self._tracked(case, p["part"])):
                approvals.append({"target": "parts", "item": p["part"], "note": "A tool or consumable: nothing to verify."})
                continue
            used = [v for v in case.visits if any(p["part"].lower() in x.lower() or (code and code.lower() in x.lower()) for x in v.get("parts_used", []))
                    and case.store.machine(v["machine_id"])["model_family"] == case.family]
            wins = [v for v in used if any(a["result"] == "worked" for a in v["actions"]) and lv.get(v["job_id"], {}).get("level") != "suspected"
                    and not lv.get(v["job_id"], {}).get("recurred")]
            losses = [v for v in used if v not in wins]
            if len(wins) >= 2 or (len(wins) == 1 and not losses):
                approvals.append({"target": "parts", "item": p["part"], "note": f"Fixed the fault in {len(wins)} visit(s) on this family."})
            else:
                why = [f"Used in {len(used)} visit(s) on {case.family}, but it fixed the fault in {len(wins)}."]
                if losses:
                    why.append("It was replaced without fixing the fault in " + ", ".join(v["job_id"] for v in losses[:4]) + ".")
                if not used:
                    why = [f"No visit on {case.family} in the records used this part."]
                vetoes.append({"target": "parts", "item": p["part"], "reasons": why, "jobs": [v["job_id"] for v in used][:6]})
        return {"vetoes": vetoes, "approvals": approvals, "ok": not vetoes}

    @staticmethod
    def _tracked(case: Case, name: str) -> bool:
        return any(s["part"].lower() == name.lower() for s in case.store.stock)


def feedback_text(vetoes: list[dict], target: str) -> str:
    lines = []
    for v in vetoes:
        if v["target"] == target:
            lines.append(f"- You proposed '{v['item']}'. The Verifier vetoed it: " + " ".join(v["reasons"]) + (f" (records: {', '.join(v['jobs'])})" if v["jobs"] else ""))
    return "\n".join(lines)
