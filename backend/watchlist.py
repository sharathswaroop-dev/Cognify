"""Risk watchlist: which machines are most likely to cost a repeat visit next, scored from the raw records only.

Each point has a stated reason, so a manager can see why a machine is on the list. Nothing here is predicted by an LLM."""
from __future__ import annotations

from datetime import date, timedelta

import beliefs
import evidence as ev


def watchlist(store, as_of: str | None = None, limit: int = 8) -> list[dict]:
    as_of = as_of or ev.NOW
    end = date.fromisoformat(as_of)
    visits = store.visits_before(as_of)
    lv = ev.visit_levels(visits, as_of)
    bl = beliefs.analyse(visits, store.machine, as_of)
    rows = []
    for m in store.machines:
        mv = [v for v in visits if v["machine_id"] == m["id"]]
        reasons, score = [], 0
        recent = {v["incident_id"] for v in mv if end - timedelta(days=90) <= date.fromisoformat(v["date"]) < end}
        if len(recent) >= 2:
            score += 3 * len(recent)
            reasons.append(f"{len(recent)} incidents in the last 90 days")
        came_back = [v for v in mv if lv.get(v["job_id"], {}).get("recurred")]
        if came_back:
            score += 3 * len(came_back)
            reasons.append(f"a fix came back within 30 days ({', '.join(v['job_id'] for v in came_back[:2])})")
        wrong = [v for v in mv if v.get("wrong_diagnosis")]
        if wrong:
            score += 1 * len(wrong)
            reasons.append(f"{len(wrong)} wrong diagnosis on record")
        short = [v for v in mv if v.get("parts_missing")]
        if short:
            score += 1 * len(short)
            reasons.append(f"a part was missing from the van on {len(short)} visit(s)")
        for b in bl:
            if b["family"] == m["model_family"] and (b["cohort_from"] is None or m["installed"] >= b["cohort_from"]):
                score += 4
                reasons.append(f"its usual fix is unreliable on this generation (installed {m['installed']})")
        fails = [a for a in store.alarms_before(as_of) if a["machine_id"] == m["id"] and a["remote_result"] == "failed"
                 and end - timedelta(days=30) <= date.fromisoformat(a["ts"][:10]) < end]
        if fails:
            score += 2
            reasons.append("a remote fix failed in the last 30 days")
        if score:
            rows.append({"machine_id": m["id"], "model": m["model"], "site": store.site(m["site_id"])["name"], "installed": m["installed"],
                         "score": score, "reasons": reasons, "holdout": bool(m.get("holdout"))})
    return sorted(rows, key=lambda r: -r["score"])[:limit]
