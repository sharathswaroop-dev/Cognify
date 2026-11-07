"""Who holds the company's knowledge, and where it is thin. Computed from the raw visit records and the notes people have shared.

"Verified fix" means a repair that worked and was not followed by the same fault within 30 days (the same rule the agents use), so a person
only gets credit for knowledge that held. A family where one person holds most of the verified fixes is knowledge at risk if they leave."""
from __future__ import annotations

from collections import Counter, defaultdict

import evidence as ev

THIN_BELOW = 5          # fewer verified fixes than this is a weak signal, the same bar the Diagnostician uses
SOLE_SHARE = 0.5        # one person holding at least this share of a family's verified fixes is a single point of failure


def overview(store, notes: list[dict]) -> dict:
    visits = store.all_visits()
    lv = ev.visit_levels(visits)
    fam_of = lambda v: store.machine(v["machine_id"])["model_family"]
    per = {t["id"]: {"visits": 0, "verified": 0, "fam": Counter(), "machines": set()} for t in store.techs}
    fam = defaultdict(lambda: {"visits": 0, "verified": 0, "by": Counter(), "machines": set()})
    for v in visits:
        tid, f, info = v["technician_id"], fam_of(v), lv.get(v["job_id"], {})
        p = per.setdefault(tid, {"visits": 0, "verified": 0, "fam": Counter(), "machines": set()})
        p["visits"] += 1
        p["machines"].add(v["machine_id"])
        fam[f]["visits"] += 1
        fam[f]["machines"].add(v["machine_id"])
        if ev.is_fix(v) and not info.get("recurred") and info.get("level") in ("stable_30d", "stable_90d"):
            p["verified"] += 1
            p["fam"][f] += 1
            fam[f]["verified"] += 1
            fam[f]["by"][tid] += 1
    notes_by_author, notes_by_family = Counter(), Counter()
    for n in notes:
        notes_by_author[n["author"].strip().lower()] += 1
        if n.get("family"):
            notes_by_family[n["family"]] += 1
    people = []
    for t in store.techs:
        p = per.get(t["id"], {"visits": 0, "verified": 0, "fam": Counter(), "machines": set()})
        holds = [{"family": f, "fixes": c, "share": round(c / fam[f]["verified"], 2)} for f, c in p["fam"].most_common() if fam[f]["verified"]]
        holds = [h for h in holds if h["share"] >= 0.3][:5]
        people.append({"id": t["id"], "name": t["name"], "years": t["years"], "speciality": t["speciality"], "visits": p["visits"], "verified": p["verified"],
                       "machines": len(p["machines"]), "notes": notes_by_author.get(t["name"].strip().lower(), 0), "holds": holds,
                       "sole_in": [h["family"] for h in holds if h["share"] >= SOLE_SHARE]})
    families = []
    for f, d in sorted(fam.items(), key=lambda kv: -kv[1]["visits"]):
        top, topn = (d["by"].most_common(1) or [(None, 0)])[0]
        share = round(topn / d["verified"], 2) if d["verified"] else 0
        thin = d["verified"] < THIN_BELOW
        families.append({"family": f, "visits": d["visits"], "verified": d["verified"], "machines": len(d["machines"]), "people": len(d["by"]), "notes": notes_by_family.get(f, 0),
                         "top_holder": next((t["name"] for t in store.techs if t["id"] == top), None), "top_share": share,
                         "status": "thin" if thin else "single holder" if share >= SOLE_SHARE and len(d["by"]) > 1 else "ok"})
    return {"totals": {"visits": len(visits), "verified": sum(p["verified"] for p in per.values()), "notes": len(notes), "people": len(store.techs),
                       "thin_families": sum(1 for f in families if f["status"] == "thin"), "at_risk_families": sum(1 for f in families if f["status"] == "single holder")},
            "people": sorted(people, key=lambda x: -x["verified"]), "families": families,
            "rule": f"A verified fix is a repair that worked and did not come back within 30 days. Thin = fewer than {THIN_BELOW} verified fixes. Single holder = one person holds at least {int(SOLE_SHARE * 100)}% of a family's verified fixes."}
