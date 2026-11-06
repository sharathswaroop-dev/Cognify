"""Simulated consequence of a plan: does the technician fix it first time, or come back?

The scenario carries a hidden 'truth' (what was really wrong). The plan is compared with it deterministically, and the outcome is priced with
parameters that are each labelled: Benchmark (cited), Simulated (our assumption) or Your inputs (set by the user on the dashboard).
Nothing here is a measured result."""
from __future__ import annotations

import re

STOP = set("the a an of on at for to in and or is was it this that with by from after before unit units replaced checked using then also".split())

PARAMS = {
    "cost_per_visit_usd": {"value": 250, "label": "Benchmark", "note": "Operating cost of one truck dispatch, $200-300 (Aberdeen Group, via AEX)"},
    "hours_per_visit": {"value": 3.0, "label": "Simulated", "note": "Technician hours per visit incl. travel (assumption)"},
    "remote_attempt_hours": {"value": 0.25, "label": "Simulated", "note": "Operator time for a remote attempt (assumption)"},
    "downtime_days_per_extra_visit": {"value": 2.0, "label": "Simulated", "note": "Machine down while waiting for the return visit (assumption)"},
}


def _tok(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2 and w not in STOP}


def plan_hits(plan: dict, truth: dict) -> dict:
    """Does the plan name the repair that really fixes it, and carry every part it really needs?"""
    top = plan["diagnosis"]["causes"][0] if plan.get("diagnosis") else {"fix": ""}
    text = " ".join([top["fix"]] + plan.get("briefing", {}).get("do_first", [])[:2])
    want = _tok(truth["fix_key"])
    fix_hit = bool(want) and len(want & _tok(text)) / len(want) >= 0.6
    carry = " ".join(p["part"].lower() for p in plan.get("parts", {}).get("carry", []))
    missing = [p for p in truth["parts"] if p.lower() not in carry and not (_tok(p) and len(_tok(p) & _tok(carry)) / len(_tok(p)) >= 0.5)]
    return {"fix_hit": fix_hit, "parts_hit": not missing, "missing_parts": missing}


def simulate(plan: dict, truth: dict, params: dict | None = None) -> dict:
    p = {k: v["value"] for k, v in (params or PARAMS).items()}
    steps, visits, hours = [], 0, 0.0
    d = plan["dispatch"]
    if d["decision"] == "REMOTE_FIX":
        hours += p["remote_attempt_hours"]
        if truth["remote_works"]:
            steps.append(f"{d['remote_action']} cleared the alarm. No visit needed.")
            return {"outcome": "fixed remotely", "visits": 0, "hours": round(hours, 2), "cost_usd": 0, "downtime_days": 0.0, "steps": steps,
                    "hits": None, "label": "Simulated"}
        steps.append(f"{d['remote_action']} did not hold; the alarm came back and a technician was sent.")
    hits = plan_hits(plan, truth)
    visits = 1
    hours += p["hours_per_visit"]
    if hits["fix_hit"] and hits["parts_hit"]:
        steps.append("The technician arrived with the right repair and the right part, and fixed it on the first visit.")
        outcome, extra = "fixed first time", 0
    else:
        why = []
        if not hits["fix_hit"]:
            why.append("the plan did not point at the real cause")
        if not hits["parts_hit"]:
            why.append("the van was missing " + ", ".join(hits["missing_parts"]))
        steps.append("First visit did not finish the job: " + " and ".join(why) + ".")
        steps.append("A second visit was needed to fix it.")
        visits, hours, outcome, extra = 2, hours + p["hours_per_visit"], "return visit needed", 1
    return {"outcome": outcome, "visits": visits, "hours": round(hours, 2), "cost_usd": round(visits * p["cost_per_visit_usd"]),
            "downtime_days": round(extra * p["downtime_days_per_extra_visit"], 1), "steps": steps, "hits": hits, "label": "Simulated"}
