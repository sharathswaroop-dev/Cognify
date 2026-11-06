"""The SiteMemory agent: recall -> reflect -> brief, and retain after every visit."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from llm import LLM
from memory import Memory, site_to_text, slug, visit_tags, visit_to_text

log = logging.getLogger("sitememory.agent")

BRIEFING_KEYS = ("headline", "likely_cause", "confidence", "do_first", "avoid", "bring", "site_notes")

SYSTEM_PROMPT = """You are SiteMemory, an assistant that briefs HVAC field technicians before a service visit.
You receive the job ticket and, when available, memories recalled from the company's service history.
Rules:
- Only state history-based facts that appear in the memories. Never invent dates, parts, codes or people.
- If memories show an attempt that did NOT fix the problem before, put it in "avoid" and say when it failed.
- If memories show what fixed it, put that first in "do_first" and list the needed parts in "bring".
- Include site access rules and contact preferences from memories in "site_notes".
- If there are no memories, give sensible generic troubleshooting for this equipment type, set confidence to "low",
  and leave "site_notes" empty.
- Be short and concrete: a technician reads this on a phone in the van.
Return ONLY a JSON object with keys:
headline (string, <= 18 words), likely_cause (string), confidence ("low"|"medium"|"high"),
do_first (array of strings, max 4), avoid (array of strings, max 3), bring (array of strings, max 4),
site_notes (array of strings, max 4)."""

GENERIC = {
    "VRV outdoor unit": {
        "likely_cause": "Could be a power supply issue, refrigerant problem, sensor fault or compressor protection trip.",
        "do_first": ["Check the error code on the outdoor PCB", "Measure supply voltage on all three phases",
                     "Check refrigerant pressures", "Reset and observe the unit"],
        "bring": ["Multimeter and clamp meter", "Manifold gauge set"],
    },
    "Water-cooled chiller": {
        "likely_cause": "Possible condenser issue, cooling tower problem or refrigerant charge issue.",
        "do_first": ["Read the alarm history on the chiller controller", "Check condenser water flow and temperatures",
                     "Reset alarm and observe"],
        "bring": ["Gauge set", "Thermometer"],
    },
    "Split AC": {
        "likely_cause": "Commonly a dirty filter, blocked drain or low refrigerant.",
        "do_first": ["Clean the air filters", "Check the drain tray", "Check refrigerant pressure"],
        "bring": ["Filter cleaning kit", "Gauge set"],
    },
    "Precision AC": {
        "likely_cause": "Could be airflow, filter, fan or refrigerant related.",
        "do_first": ["Check alarm log on the controller", "Inspect filters", "Restart the unit"],
        "bring": ["Laptop with service tool", "Filters"],
    },
    "Cassette indoor unit": {
        "likely_cause": "Communication errors are often caused by a remote or PCB fault.",
        "do_first": ["Power reset the indoor and outdoor units", "Check the remote controller", "Inspect the PCB"],
        "bring": ["Spare remote controller", "Multimeter"],
    },
    "Air handling unit": {
        "likely_cause": "Noise and vibration are usually belt, pulley or bearing related.",
        "do_first": ["Check belt tension and alignment", "Grease bearings", "Check mounting bolts"],
        "bring": ["Belt set", "Grease gun"],
    },
    "Ductable AC": {
        "likely_cause": "Low cooling is often low refrigerant or a dirty coil.",
        "do_first": ["Check refrigerant pressure and top up if low", "Clean the indoor coil", "Check filters"],
        "bring": ["Refrigerant cylinder", "Coil cleaner"],
    },
}


class Agent:
    def __init__(self, memory, store) -> None:
        self.memory = memory
        self.store = store  # data access (machines, sites, technicians, logged visits)
        self.llm = LLM()

    # ------------------------------------------------------------ retain
    def visit_record(self, visit: dict) -> dict:
        m = self.store.machine(visit["machine_id"])
        s = self.store.site(m["site_id"])
        t = self.store.tech(visit["technician_id"])
        return {
            "doc_id": f"visit-{visit['job_id']}",
            "text": visit_to_text(visit, m, s, t),
            "tags": visit_tags(visit, m),
            "date": visit["date"],
            "meta": {"job_id": visit["job_id"], "date": visit["date"], "technician": t["name"],
                     "machine_id": m["id"], "site_id": s["id"], "actions": visit.get("actions", []),
                     "root_cause": visit.get("root_cause", ""), "parts_used": visit.get("parts_used", []),
                     "outcome": visit.get("outcome", "")},
        }

    def site_record(self, site: dict) -> dict:
        return {"doc_id": f"site-{site['id']}", "text": site_to_text(site),
                "tags": [f"site:{site['id']}", "kind:site"], "date": None,
                "meta": {"site_id": site["id"], "notes": site.get("notes", [])}}

    def seed(self) -> int:
        records = [self.site_record(s) for s in self.store.sites]
        records += [self.visit_record(v) for v in self.store.history]
        self.memory.retain_many(records)
        return len(records)

    def retain_visit(self, visit: dict) -> dict:
        rec = self.visit_record(visit)
        self.memory.retain(rec["text"], rec["tags"], rec["date"], rec["doc_id"], rec["meta"])
        return rec

    # ------------------------------------------------------------ recall + reflect
    def recall_context(self, job: dict) -> dict[str, Any]:
        m = self.store.machine(job["machine_id"])
        q = f"{m['model']} {m['type']}: {job['symptom']}"
        family = f"family:{slug(m['model_family'])}"
        machine_mem = self.memory.recall(q, [f"machine:{m['id']}"], limit=5)
        family_mem = [x for x in self.memory.recall(q, [family], limit=8) if f"machine:{m['id']}" not in x.tags][:4]
        site_mem = self.memory.recall(f"access rules, contact person and preferences at {self.store.site(m['site_id'])['name']}",
                                      [f"site:{m['site_id']}"], limit=3)
        site_mem = [x for x in site_mem if "kind:site" in x.tags or "Site profile" in x.text][:1] or site_mem[:1]
        reflection = None
        try:
            reflection = self.memory.reflect(
                f"For a {m['model']} ({m['type']}) with symptom '{job['symptom']}': what has been tried before, "
                f"what did NOT fix it, what fixed it, the most likely root cause, and which parts to carry?",
                [f"machine:{m['id']}", family])
        except Exception as exc:
            log.warning("reflect failed: %s", exc)
        return {"machine": machine_mem, "family": family_mem, "site": site_mem, "reflection": reflection}

    # ------------------------------------------------------------ briefing
    def briefing(self, job: dict, use_memory: bool) -> dict[str, Any]:
        t0 = time.time()
        m = self.store.machine(job["machine_id"])
        s = self.store.site(m["site_id"])
        ctx = {"machine": [], "family": [], "site": [], "reflection": None}
        if use_memory:
            try:
                ctx = self.recall_context(job)
            except Exception as exc:
                log.error("recall failed, continuing without memory: %s", exc)
        recall_ms = int((time.time() - t0) * 1000)

        mem_block = self._memory_prompt(ctx)
        user = (f"JOB TICKET\nJob: {job['job_id']} on {job['date']}\nSite: {s['name']}, {s['area']}\n"
                f"Machine: {m['id']} - {m['model']} ({m['type']}) at {m['location']}, installed {m['installed']}\n"
                f"Reported symptom: {job['symptom']}\n\n"
                f"{mem_block if mem_block else 'MEMORY: none available for this job.'}")

        data = self.llm.json_chat(SYSTEM_PROMPT, user, required=BRIEFING_KEYS)
        source = "llm"
        if data is None:
            data = self._fallback(job, m, ctx)
            source = "rules-fallback"
        data = self._clean(data)

        used = ([{"level": "This machine", **x.to_dict()} for x in ctx["machine"]] +
                [{"level": "Same model, other sites", **x.to_dict()} for x in ctx["family"]] +
                [{"level": "Site", **x.to_dict()} for x in ctx["site"]])
        return {"job_id": job["job_id"], "use_memory": use_memory, "briefing": data, "memories_used": used,
                "reflection": ctx["reflection"], "generated_by": source, "memory_backend": self.memory.name,
                "timing_ms": {"recall": recall_ms, "total": int((time.time() - t0) * 1000)}}

    @staticmethod
    def _memory_prompt(ctx: dict) -> str:
        parts = []
        if ctx["machine"]:
            parts.append("MEMORIES - THIS EXACT MACHINE:\n" + "\n---\n".join(x.text for x in ctx["machine"]))
        if ctx["family"]:
            parts.append("MEMORIES - SAME MODEL AT OTHER SITES:\n" + "\n---\n".join(x.text for x in ctx["family"]))
        if ctx["site"]:
            parts.append("MEMORIES - SITE:\n" + "\n".join(x.text for x in ctx["site"]))
        if ctx["reflection"]:
            parts.append("LESSONS SYNTHESISED FROM MEMORY (Hindsight reflect):\n" + ctx["reflection"])
        return "\n\n".join(parts)

    @staticmethod
    def _clean(d: dict) -> dict:
        out = {k: d.get(k) for k in BRIEFING_KEYS}
        for k in ("do_first", "avoid", "bring", "site_notes"):
            v = out.get(k) or []
            out[k] = [str(x) for x in (v if isinstance(v, list) else [v])][:4]
        out["confidence"] = str(out.get("confidence") or "low").lower()
        if out["confidence"] not in ("low", "medium", "high"):
            out["confidence"] = "low"
        out["headline"] = str(out.get("headline") or "")
        out["likely_cause"] = str(out.get("likely_cause") or "")
        return out

    def _fallback(self, job: dict, m: dict, ctx: dict) -> dict:
        """Deterministic briefing used when the LLM is unavailable. Still memory-driven."""
        g = GENERIC.get(m["type"], GENERIC["Split AC"])
        visits = ctx["machine"] + ctx["family"]
        if not visits and not ctx["site"]:
            return {"headline": f"{m['type']} fault: run standard checks", "likely_cause": g["likely_cause"],
                    "confidence": "low", "do_first": g["do_first"], "avoid": [], "bring": g["bring"], "site_notes": []}

        avoid, do_first, bring, cause = [], [], [], ""
        for v in ctx["machine"] + ctx["family"]:
            meta = v.meta or {}
            for a in meta.get("actions", []) if isinstance(meta.get("actions"), list) else []:
                where = "on this unit" if v in ctx["machine"] else "on the same model elsewhere"
                line = f"{a['action']} (failed {where} on {meta.get('date', '?')})"
                if a["result"] == "failed" and len(avoid) < 3 and not any(a["action"] in x for x in avoid):
                    avoid.append(line)
                if a["result"] == "worked" and not any(a["action"][:22] == x[:22] for x in do_first):
                    do_first.append(a["action"])
            for p in meta.get("parts_used", []) if isinstance(meta.get("parts_used"), list) else []:
                if p not in bring:
                    bring.append(p)
            if not cause and meta.get("root_cause"):
                cause = meta["root_cause"]
        site_notes = []
        for sm in ctx["site"]:
            notes = (sm.meta or {}).get("notes")
            site_notes += notes if isinstance(notes, list) else [sm.text]
        n_machine = len({(x.meta or {}).get("job_id") for x in ctx["machine"]} - {None}) or len(ctx["machine"])
        headline = (f"Seen before: {n_machine} past visit{'s' if n_machine != 1 else ''} on this unit" if n_machine
                    else "No history on this unit, but the same model has a known pattern")
        return {"headline": headline,
                "likely_cause": cause or ctx.get("reflection") or g["likely_cause"],
                "confidence": "high" if n_machine >= 2 else "medium" if visits else "low",
                "do_first": (do_first or g["do_first"])[:4], "avoid": avoid,
                "bring": (bring or g["bring"])[:4], "site_notes": site_notes[:4]}
