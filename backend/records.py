"""What goes into the one shared memory bank, and how it is validated.

Everything the company knows lives in a single Hindsight bank, tagged by kind:
  kind:visit     one per technician visit: suspected cause, what was done, the verified outcome and its evidence level at the time
  kind:followup  what happened afterwards: 'stable 30 days', 'stable 90 days', or 'it came back, the fix did not hold'
  kind:alarm     a machine alarm, the remote action tried and whether it cleared
  kind:site      access rules and contacts
Records are appended in date order and never edited, so the memory as of any past date can be rebuilt exactly."""
from __future__ import annotations

from datetime import date, timedelta

from evidence import LEVEL_LABEL, is_fix, visit_levels
from memory import slug
from store import Store, UnknownMachine


def _family_tag(m): return f"family:{slug(m['model_family'])}"


def visit_record(v: dict, m: dict, s: dict, t: dict, level: str | None = None) -> dict:
    level = level or ("fixed_at_visit" if is_fix(v) else "suspected")
    lines = [f"Job {v['job_id']}: on {v['date']}, technician {t['name']} visited {s['name']} ({s['area']}) for machine {m['id']}, "
             f"a {m['model']} {m['type']} at {m['location']} (installed {m['installed']}).",
             f"Reported symptom: {v['symptom']}."]
    if v.get("suspected_cause"):
        lines.append(f"Suspected cause: {v['suspected_cause']}.")
    for a in v.get("actions", []):
        verdict = {"failed": "DID NOT FIX IT", "worked": "FIXED IT", "partial": "only partly helped"}[a["result"]]
        lines.append(f"Tried: {a['action']} -> {verdict}. {a.get('detail', '')}".strip())
    if v.get("parts_used"):
        lines.append(f"Parts used: {', '.join(v['parts_used'])}.")
    if v.get("parts_missing"):
        lines.append(f"Parts needed but NOT carried (forced a second trip): {', '.join(v['parts_missing'])}.")
    if v.get("evidence"):
        lines.append(f"Evidence found: {v['evidence']}")
    if v.get("root_cause"):
        lines.append(f"Confirmed root cause: {v['root_cause']}")
    lines.append(f"Verified outcome at the time: {LEVEL_LABEL[level]}." + ("" if is_fix(v) else " Not resolved on this visit; a second visit was needed."))
    if v.get("recommendation"):
        lines.append(f"Recommendation: {v['recommendation']}")
    if v.get("notes"):
        lines.append(f"Technician note: {v['notes']}")
    return {"doc_id": f"visit-{v['job_id']}", "text": "\n".join(lines), "date": v["date"],
            "tags": [f"machine:{m['id']}", f"site:{s['id']}", _family_tag(m), "kind:visit", f"evidence:{level}"],
            "meta": {"job_id": v["job_id"], "machine_id": m["id"], "date": v["date"]}}


def followup_records(visits: list[dict], store: Store, as_of: str | None = None) -> list[dict]:
    """Stable-30d / stable-90d / recurrence events, each dated when it became known."""
    out = []
    lv = visit_levels(visits, "9999-12-31")
    for v in visits:
        if not is_fix(v):
            continue
        info, m = lv[v["job_id"]], store.machine(v["machine_id"])
        d0, fix = date.fromisoformat(v["date"]), next(a["action"] for a in v["actions"] if a["result"] == "worked").rstrip(". ")
        events = []
        if info["recurred"]:
            rec = next(w for w in visits if w["job_id"] == info["recurrence_job"])
            events.append((rec["date"], "failed", f"Recurrence: the same fault came back on machine {m['id']} {info['recurred_after_days']} days after job {v['job_id']}. "
                           f"The fix '{fix}' did NOT hold (see job {rec['job_id']}). Evidence level of {v['job_id']}: failed within 30 days."))
        else:
            for days, level in ((30, "stable_30d"), (90, "stable_90d")):
                at = (d0 + timedelta(days=days)).isoformat()
                later = [w for w in visits if w["machine_id"] == v["machine_id"] and w.get("fault_class") == v.get("fault_class")
                         and w["incident_id"] != v["incident_id"] and v["date"] < w["date"] <= at]
                if not later:
                    events.append((at, level, f"Follow-up on job {v['job_id']} (machine {m['id']}, fix '{fix}'): {days} days passed with no recurrence. "
                                   f"Evidence level of {v['job_id']}: {LEVEL_LABEL[level]}."))
        for at, level, text in events:
            if as_of is None or at < as_of:
                out.append({"doc_id": f"followup-{level}-{v['job_id']}", "text": text, "date": at,
                            "tags": [f"machine:{m['id']}", _family_tag(m), "kind:followup", f"evidence:{level}"],
                            "meta": {"job_id": v["job_id"], "machine_id": m["id"], "date": at}})
    return out


def alarm_record(a: dict, m: dict, s: dict) -> dict:
    readings = ", ".join(f"{k}={v}" for k, v in a.get("readings", {}).items())
    if a.get("remote_action") is None:
        outcome = "No remote action exists for this alarm."
    elif a["remote_result"] == "cleared":
        outcome = f"Remote action tried ({a['remote_type']}): {a['remote_action']}. It cleared the alarm and no visit was needed."
    else:
        outcome = f"Remote action tried ({a['remote_type']}): {a['remote_action']}. It did NOT clear the alarm (it returned within 30 minutes)."
    text = (f"Alarm {a['id']} on {a['ts'][:16].replace('T', ' ')}: machine {m['id']} ({m['model']}, {m['type']}) at {s['name']} raised code {a['code']} "
            f"({a['description']}); readings: {readings or 'none'}. {outcome} {'A technician was dispatched.' if a['dispatched'] else 'Handled remotely.'}")
    return {"doc_id": f"alarm-{a['id']}", "text": text, "date": a["ts"][:10],
            "tags": [f"machine:{m['id']}", f"site:{s['id']}", _family_tag(m), f"code:{a['code']}", "kind:alarm"],
            "meta": {"alarm_id": a["id"], "machine_id": m["id"], "date": a["ts"][:10]}}


def site_record(s: dict) -> dict:
    notes = " ".join(f"- {n}" for n in s.get("notes", []))
    return {"doc_id": f"site-{s['id']}", "text": f"Site profile for {s['name']} ({s['area']}). Contact: {s['contact']}. Access rules and preferences: {notes}",
            "tags": [f"site:{s['id']}", "kind:site"], "date": None, "meta": {"site_id": s["id"]}}


def knowledge_record(author: str, role: str, years: int | None, text: str, machine: dict | None, site: dict | None, doc_id: str, date: str) -> dict:
    """What an experienced person knows, in their own words, kept with who said it and about what. This is the knowledge that otherwise leaves with them."""
    who = f"{author}" + (f" ({role}{', ' + str(years) + ' years in the job' if years else ''})" if role or years else "")
    about = f" about {machine['model']} {machine['id']} at {site['name']}" if machine and site else (f" about {site['name']}" if site else "")
    tags = ["kind:note", f"author:{slug(author)}"] + ([f"machine:{machine['id']}", f"family:{slug(machine['model_family'])}"] if machine else []) + ([f"site:{site['id']}"] if site else [])
    return {"doc_id": doc_id, "text": f"Knowledge shared by {who}{about}: {text}", "tags": tags, "date": date, "meta": {"author": author, "kind": "note"}}


def validate(rec: dict, store: Store) -> dict:
    """Refuse a record that names a machine we do not have. Memory with invented machine ids is worse than no memory."""
    for t in rec["tags"]:
        if t.startswith("machine:") and not store.has_machine(t.split(":", 1)[1]):
            raise UnknownMachine(f"Refusing to retain a record for unknown machine {t.split(':', 1)[1]!r}")
    return rec


def build_all(store: Store, as_of: str | None = None, visits: list[dict] | None = None) -> list[dict]:
    """Every record that exists as of a date (None = now), in date order, ready to retain."""
    visits = [v for v in (visits if visits is not None else store.all_visits()) if as_of is None or v["date"] < as_of]
    lv = visit_levels(visits, as_of)  # level of each visit AS OF the cut-off is what the memory knew at retain time of the visit itself
    recs = [site_record(s) for s in store.sites]
    for v in visits:
        m = store.machine(v["machine_id"])
        recs.append(visit_record(v, m, store.site(m["site_id"]), store.tech(v["technician_id"])))  # level at the visit = fixed_at_visit / suspected
    recs += followup_records(visits, store, as_of)
    for a in store.alarms_before(as_of):
        m = store.machine(a["machine_id"])
        recs.append(alarm_record(a, m, store.site(m["site_id"])))
    return [validate(r, store) for r in sorted(recs, key=lambda r: (r["date"] or "0000", r["doc_id"]))]


MISSION = ("Remember everything a field-service company learns: for every visit the suspected cause, what was done, and the verified outcome with "
           "its evidence level (suspected, fixed at visit, stable 30 days, stable 90 days); what happened afterwards; which remote fixes cleared which alarms; "
           "and each site's access rules. Failures matter as much as fixes.")
