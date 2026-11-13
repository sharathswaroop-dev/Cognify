"""The learning replay: one model family, its incidents in date order, and what the agents would have said using ONLY the records dated before each one.

No model and no Hindsight call is involved: the Diagnostician falls back to its rule-based mode, the Parts agent to its rule-based mode, and the Verifier
is deterministic anyway. So the replay is instant, repeatable and cannot be broken by a rate limit. It shows the same thing the live agents rely on:
what the raw records support at that moment, how sure that is, and when it stops being true.
"""
from __future__ import annotations

from functools import lru_cache

import beliefs
import evaluation
import evidence as ev
from agents import Case, Verifier
from plan import build_plan


class _NoRecall:
    """Stands in for memory: the rule-based agents read the raw records handed to the Case, so nothing is recalled."""
    name = "replay"
    bank_id = "(records before this date)"

    def recall(self, *a, **k):
        return []

    def reflect(self, *a, **k):
        return None


def _case(store, v: dict, use_memory: bool) -> Case:
    m = store.machine(v["machine_id"])
    a = next((x for x in store.alarms if x.get("incident_id") == v["incident_id"]), None)
    alarm = {"id": f"LR-{v['job_id']}", "code": a["code"] if a else "", "description": a["description"] if a else v["symptom"],
             "readings": a["readings"] if a else {}, "severity": "major", "machine_id": m["id"], "ts": v["date"] + "T09:00:00"}
    job = {"job_id": v["job_id"], "date": v["date"], "machine_id": m["id"], "symptom": v["symptom"]}
    before = v["date"]
    return Case(alarm, m, store.site(m["site_id"]), job, store, None, _NoRecall(), use_memory, before,
                store.visits_before(before) if use_memory else [], store.alarms_before(before) if use_memory else [])


def _belief_notes(store, before: str) -> list[dict]:
    out = []
    for b in beliefs.analyse(store.visits_before(before), store.machine, before):
        out.append({"fix": b["fix_key"], "family": b["family"], "cohort_from": b.get("cohort_from"), "text": b.get("text") or b.get("statement") or ""})
    return out


def families(store) -> list[str]:
    return sorted({m["model_family"] for m in store.machines})


@lru_cache(maxsize=8)
def _replay(family: str, store_id: int, store_ref):
    store = store_ref
    levels = ev.visit_levels(store.history, "9999-12-31")
    by_job = {v["job_id"]: v for v in store.history}
    by_inc: dict[str, list[dict]] = {}
    for v in store.history:
        by_inc.setdefault(v["incident_id"], []).append(v)
    firsts = sorted((v for v in store.history if v["visit_no"] == 1 and store.machine(v["machine_id"])["model_family"] == family),
                    key=lambda v: (v["date"], v["job_id"]))
    verifier, steps, seen_beliefs = Verifier(), [], set()
    hit_mem = hit_base = 0
    for i, v in enumerate(firsts, 1):
        m = store.machine(v["machine_id"])
        truth = evaluation.truth_for(by_inc[v["incident_id"]], levels, by_job)
        case = _case(store, v, True)
        out = build_plan(case, verifier)
        final = out["final"]
        sc = evaluation.score(final, truth)
        top = final["diagnosis"]["causes"][0]
        st = top.get("stats") or {}
        hit_mem += 1 if sc["fix"] else 0
        # the memory-off arm has nothing to go on, so it can only say "run the standard checks"
        base = build_plan(_case(store, v, False), None)["final"]["diagnosis"]["causes"][0]
        sb = evaluation.score({"diagnosis": {"causes": [base]}, "parts": {"carry": []}}, truth)
        hit_base += 1 if sb["fix"] else 0
        known = len(case.visits)
        notes = _belief_notes(store, v["date"])
        fresh = [n for n in notes if (n["family"], n["fix"]) not in seen_beliefs]
        for n in notes:
            seen_beliefs.add((n["family"], n["fix"]))
        steps.append({
            "i": i, "date": v["date"], "job_id": v["job_id"], "machine_id": m["id"], "model": m["model"], "installed": m["installed"],
            "symptom": v["symptom"], "records_known": known,
            "truth": {"fix": truth["fix_key"], "parts": truth["parts"], "failed_first": truth["failed"][:2]},
            "with_memory": {"fix": top["fix"], "cause": top.get("cause", ""), "confidence": top.get("confidence", "weak"),
                            "n": st.get("n", 0), "verified": st.get("verified", 0), "rate": st.get("rate"), "ci": st.get("ci"),
                            "abstained": top["fix"].lower().startswith(("escalate", "run the standard")), "scope": top.get("stats_scope", ""), "jobs": top.get("evidence_jobs", [])[:4], "hit": bool(sc["fix"]),
                            "parts": [p["part"] for p in final["parts"]["carry"]][:3], "vetoes": [x["item"] for x in out["vetoes"]][:3],
                            "parts_hit": sc["parts"]},
            "without_memory": {"fix": base["fix"], "hit": bool(sb["fix"])},
            "belief_event": ({"text": fresh[0]["text"], "fix": fresh[0]["fix"], "cohort_from": fresh[0]["cohort_from"]} if fresh else None),
            "score": {"memory": hit_mem, "without": hit_base, "of": i},
        })
    return {"family": family, "steps": steps, "n": len(steps),
            "final": {"memory": hit_mem, "without": hit_base, "of": len(steps)}}


def replay(store, family: str = "Daikin VRV IV") -> dict:
    return _replay(family, id(store), store)
