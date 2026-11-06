"""What each agent remembers. Every role has its own Hindsight bank holding only the slice of
company knowledge that role needs, so the roles genuinely differ in what they recall."""
from __future__ import annotations

from memory import slug, visit_tags, visit_to_text


def _alarm_outcome_sentence(a: dict) -> str:
    if a["remote_action"] is None:
        return "No remote action exists for this alarm."
    r = a["remote_result"]
    verdict = ("The alarm cleared and no visit was needed." if r == "cleared"
               else "It did NOT clear the alarm (it returned within 30 minutes).")
    return f"Remote action tried: {a['remote_action']}. {verdict}"


def alarm_record(a: dict, machine: dict, site: dict) -> dict:
    """Dispatcher memory: an alarm, which remote fix was tried, and whether it worked."""
    readings = ", ".join(f"{k}={v}" for k, v in a.get("readings", {}).items())
    text = (f"Alarm {a['id']} on {a['ts'][:16].replace('T', ' ')}: machine {machine['id']} ({machine['model']}, "
            f"{machine['type']}) at {site['name']} raised code {a['code']} ({a['description']}); readings: {readings or 'none'}. "
            f"{_alarm_outcome_sentence(a)} "
            f"{'A technician was dispatched.' if a['dispatched'] else 'Handled remotely.'}")
    return {"doc_id": f"alarm-{a['id']}", "text": text, "date": a["ts"][:10],
            "tags": [f"machine:{machine['id']}", f"site:{site['id']}", f"family:{slug(machine['model_family'])}",
                     f"code:{a['code']}", f"type:{slug(machine['type'])}", "kind:alarm"],
            "meta": {"alarm_id": a["id"], "code": a["code"], "remote_result": a["remote_result"],
                     "dispatched": str(a["dispatched"])}}


def outcome_record(alarm: dict, machine: dict, site: dict, visit: dict) -> dict:
    """Dispatcher learns what finally fixed an alarm it routed."""
    fix = visit.get("fix") or "(not fixed on this visit)"
    text = (f"Follow-up on alarm {alarm['id']} ({alarm['code']} on {machine['id']}, {machine['model']}): "
            f"technician visit {visit['job_id']} on {visit['date']} ended '{visit['outcome']}'. "
            f"Root cause: {visit.get('root_cause') or 'unknown'}. Fix: {fix}. "
            f"Remote fixing was {'not enough' if alarm.get('dispatched', True) else 'enough'} for this alarm.")
    return {"doc_id": f"outcome-{alarm['id']}-{visit['job_id']}", "text": text, "date": visit["date"],
            "tags": [f"machine:{machine['id']}", f"family:{slug(machine['model_family'])}", f"code:{alarm['code']}",
                     "kind:outcome"], "meta": {"alarm_id": alarm["id"], "job_id": visit["job_id"]}}


def visit_record(visit: dict, machine: dict, site: dict, tech: dict) -> dict:
    """Diagnostician memory: the full clinical record of a visit (what was tried, what failed, root cause)."""
    return {"doc_id": f"visit-{visit['job_id']}", "text": visit_to_text(visit, machine, site, tech),
            "tags": visit_tags(visit, machine), "date": visit["date"],
            "meta": {"job_id": visit["job_id"], "date": visit["date"], "technician": tech["name"],
                     "machine_id": machine["id"], "site_id": site["id"], "actions": visit.get("actions", []),
                     "root_cause": visit.get("root_cause", ""), "parts_used": visit.get("parts_used", []),
                     "outcome": visit.get("outcome", "")}}


def parts_record(visit: dict, machine: dict, history: list[dict]) -> dict | None:
    """Parts agent memory: which parts were used for which model, and when a missing part forced a revisit."""
    parts = visit.get("parts_used") or []
    if not parts:
        return None
    first = next((v for v in history if v["incident_id"] == visit["incident_id"] and v["visit_no"] == 1), None)
    lines = [f"Job {visit['job_id']} on {visit['date']}: {machine['model']} (installed {machine['installed']}, "
             f"{machine['type']}) used parts: {', '.join(parts)}."]
    ok = any(a["result"] == "worked" for a in visit.get("actions", []))
    lines.append("These parts fixed the fault." if ok else "These parts did NOT fix the fault.")
    if visit["visit_no"] == 2 and first and not first.get("parts_used"):
        lines.append("This part was not carried on the first visit, so a second trip was needed.")
    if visit.get("root_cause"):
        lines.append(f"Fault: {visit['root_cause']}")
    return {"doc_id": f"parts-{visit['job_id']}", "text": " ".join(lines), "date": visit["date"],
            "tags": [f"machine:{machine['id']}", f"family:{slug(machine['model_family'])}", "kind:parts"]
                    + [f"part:{slug(p)[:40]}" for p in parts],
            "meta": {"job_id": visit["job_id"], "parts": list(parts), "worked": str(ok)}}


def seed_records(store) -> dict[str, list[dict]]:
    """The records each role's bank is seeded with."""
    out: dict[str, list[dict]] = {"dispatcher": [], "diagnostician": [], "parts": []}
    for a in store.alarms:
        m = store.machine(a["machine_id"])
        out["dispatcher"].append(alarm_record(a, m, store.site(m["site_id"])))
    for v in store.history:
        m = store.machine(v["machine_id"])
        out["diagnostician"].append(visit_record(v, m, store.site(m["site_id"]), store.tech(v["technician_id"])))
        p = parts_record(v, m, store.history)
        if p:
            out["parts"].append(p)
    return out  # the field assistant's bank is seeded by Agent.seed() (sites + visits)


MISSIONS = {
    "dispatcher": ("Remember every machine alarm, which remote fix was tried, and whether it cleared the alarm, "
                   "so we only send a technician when remote action will not work."),
    "diagnostician": ("Remember the root cause of every HVAC fault, with the evidence: what was tried, what failed, "
                      "what fixed it, and which units behave differently."),
    "parts": ("Remember which parts fixed which faults on which models, and when a missing part forced a second trip."),
}
