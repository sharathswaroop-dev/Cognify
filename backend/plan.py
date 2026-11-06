"""Propose -> verify -> revise, without the UI, Band or event streaming. Used by the evaluation; the control room does the same steps
with narration (mesh/runner.py)."""
from __future__ import annotations

from agents import Case, Diagnostician, PartsAgent, Verifier, feedback_text

STUB_DISPATCH = {"decision": "SEND_TECHNICIAN", "remote_type": None, "remote_action": None}


def drop_vetoed(diag: dict, parts: dict, vetoes: list[dict]) -> None:
    """After the revisions are used up, anything still vetoed is removed from the plan rather than shipped unverified."""
    gone = {v["item"] for v in vetoes if v["target"] == "parts"}
    parts["carry"] = [p for p in parts["carry"] if p["part"] not in gone]
    bad = {v["item"] for v in vetoes if v["target"] == "diagnostician"}
    diag["causes"] = [c for c in diag["causes"] if c["fix"] not in bad] or [
        {"cause": "Unverified: escalate to a senior technician", "fix": "Escalate to a senior technician", "why": "", "evidence_jobs": [],
         "stats": {"n": 0, "weak": True, "rate": None, "ci": [0, 1], "verified": 0, "provisional": 0, "failed": 0}, "confidence": "weak"}]


def _snap(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def build_plan(case: Case, verifier: Verifier | None = None, rounds: int = 3) -> dict:
    """Returns {"raw": the first proposals, "final": the plan after the Verifier (same as raw when there is no Verifier), "vetoes": [...]}."""
    diag = Diagnostician().diagnose(case)
    parts = PartsAgent().plan(case, diag)
    raw = {"diagnosis": _snap(diag), "parts": _snap(parts)}
    all_vetoes: list[dict] = []
    if verifier and case.use_memory:
        for rnd in range(rounds):
            v = verifier.review(case, STUB_DISPATCH, diag, parts)
            all_vetoes += v["vetoes"]
            if v["ok"]:
                break
            if rnd == rounds - 1:
                drop_vetoed(diag, parts, v["vetoes"])
                break
            if any(x["target"] == "diagnostician" for x in v["vetoes"]):
                hint = next((x.get("alternative") for x in v["vetoes"] if x.get("alternative")), None)
                diag = Diagnostician().diagnose(case, feedback_text(v["vetoes"], "diagnostician"), prior=diag, hint=hint)
                parts = PartsAgent().plan(case, diag, feedback_text(v["vetoes"], "parts"))
            else:
                parts = PartsAgent().plan(case, diag, feedback_text(v["vetoes"], "parts"))
    return {"raw": raw, "final": {"diagnosis": _snap(diag), "parts": _snap(parts)}, "vetoes": all_vetoes}
