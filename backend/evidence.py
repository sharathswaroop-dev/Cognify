"""Evidence levels and outcome statistics, computed from the raw visit records only.

A visit's outcome climbs a ladder, and only verified outcomes raise confidence:

    suspected        nothing fixed it (or only a guess was recorded)
    fixed_at_visit   the technician fixed it and left; nothing proves it holds
    stable_30d       30 days passed with no recurrence of the same fault on that machine
    stable_90d       90 days passed with no recurrence

If the same fault comes back on the same machine within 30 days, the fix is recorded as having failed, however good it looked on the day.
Everything is a function of (visits, as_of), so the replay evaluation can recompute the picture as it was on any past date and never sees the future.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date, timedelta

NOW = "2026-11-07"
LEVELS = ("suspected", "fixed_at_visit", "stable_30d", "stable_90d")
LEVEL_LABEL = {"suspected": "Suspected", "fixed_at_visit": "Fixed at visit", "stable_30d": "Stable 30 days", "stable_90d": "Stable 90 days"}
MIN_N = 5  # fewer attempts than this is a weak signal


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def fix_key(action: str) -> str:
    """Group wordings of one fix: 'Replaced compressor contactor and checked...' ~ 'Replaced compressor contactor (DK-CTR-24V)'."""
    return " ".join(re.findall(r"[a-z]+", action.lower())[:3])


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round(max(0.0, (c - m) / d), 3), round(min(1.0, (c + m) / d), 3))


def is_fix(v: dict) -> bool:
    return v.get("outcome") == "resolved" and any(a["result"] == "worked" for a in v.get("actions", []))


def visit_levels(visits: list[dict], as_of: str | None = None) -> dict[str, dict]:
    """job_id -> {level, recurred, recurred_after_days, recurrence_job}. as_of is exclusive: only records dated before it are known."""
    as_of = as_of or NOW
    known = [v for v in visits if v["date"] < as_of or v["date"] == as_of and False]
    by_mc = defaultdict(list)
    for v in known:
        by_mc[(v["machine_id"], v.get("fault_class", ""))].append(v)
    out = {}
    for v in known:
        if not is_fix(v):
            out[v["job_id"]] = {"level": "suspected", "recurred": False, "recurred_after_days": None, "recurrence_job": None}
            continue
        d0, elapsed = _d(v["date"]), (_d(as_of) - _d(v["date"])).days
        rec = next((w for w in sorted(by_mc[(v["machine_id"], v.get("fault_class", ""))], key=lambda x: x["date"])
                    if w["incident_id"] != v["incident_id"] and d0 < _d(w["date"]) <= d0 + timedelta(days=90)), None)
        gap = (_d(rec["date"]) - d0).days if rec else None
        if rec and gap <= 30:
            level = "fixed_at_visit"          # it came back within 30 days: never counts as stable
        elif elapsed >= 90 and not rec:
            level = "stable_90d"
        elif elapsed >= 30:
            level = "stable_30d"
        else:
            level = "fixed_at_visit"
        out[v["job_id"]] = {"level": level, "recurred": bool(rec and gap <= 30), "recurred_after_days": gap if rec and gap <= 30 else None,
                            "recurrence_job": rec["job_id"] if rec and gap <= 30 else None}
    return out


def is_verified(info: dict) -> bool:
    return info["level"] in ("stable_30d", "stable_90d") and not info["recurred"]


def attempts(visits: list[dict], machine_of, as_of: str | None = None) -> dict:
    """{family: {fix_key: [attempt]}} in date order. result: verified | provisional | failed (partial attempts are not outcomes)."""
    lv = visit_levels(visits, as_of)
    out: dict = defaultdict(lambda: defaultdict(list))
    for v in sorted((x for x in visits if x["job_id"] in lv), key=lambda x: (x["date"], x["job_id"])):
        m, info = machine_of(v["machine_id"]), lv[v["job_id"]]
        for a in v.get("actions", []):
            if a["result"] == "partial":
                continue
            if a["result"] == "worked":
                res = "failed" if info["recurred"] else ("verified" if is_verified(info) else "provisional")
            else:
                res = "failed"
            out[m["model_family"]][fix_key(a["action"])].append({
                "date": v["date"], "result": res, "installed": m["installed"], "machine_id": m["id"], "job_id": v["job_id"],
                "incident_id": v["incident_id"], "label": a["action"], "level": info["level"], "wrong_diagnosis": bool(v.get("wrong_diagnosis"))})
    return out


def fix_stats(att: list[dict], recent: int = 5) -> dict:
    """n, verified successes, provisional, failures, the verified success rate with its 95% interval, and the same for the latest attempts."""
    n = len(att)
    ver = sum(1 for a in att if a["result"] == "verified")
    prov = sum(1 for a in att if a["result"] == "provisional")
    lo, hi = wilson(ver, n)
    tail = att[-recent:]
    tv = sum(1 for a in tail if a["result"] == "verified")
    return {"n": n, "verified": ver, "provisional": prov, "failed": n - ver - prov, "rate": round(ver / n, 3) if n else None,
            "ci": [lo, hi], "weak": n < MIN_N, "recent_n": len(tail), "recent_verified": tv,
            "recent_rate": round(tv / len(tail), 3) if tail else None}


def confidence(stats: dict) -> str:
    """Confidence is earned by verified outcomes, never by how fluent the recommendation sounds."""
    if stats["weak"]:
        return "weak"
    if stats["verified"] >= 5 and (stats["rate"] or 0) >= 0.8:
        return "high"
    return "medium" if (stats["rate"] or 0) >= 0.5 else "low"
