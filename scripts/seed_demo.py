"""Add sample notes and documents to the demo company through the app's own endpoints (so they are retained in memory like anything a person adds).

    python backend/app.py        # in one terminal
    python scripts/seed_demo.py  # in another; safe to run twice

Everything it adds is labelled sample data and lives only in the demo company.
"""
import sys
from pathlib import Path

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
SAMPLE = Path(__file__).resolve().parent.parent / "docs" / "sample"
NOTES = [
    dict(author="Farhan Sheikh", role="Split and cassette units", years=3, machine_id="M-07",
         text="On M-07 an E3 trip at low supply voltage is almost never the compressor. Check the contactor coil first, then the supply under load. Replacing the relay board did nothing on three Daikin VRV IV units."),
    dict(author="Meena Iyer", role="Precision cooling", years=5,
         text="Condenser coils on the Carrier 30XW chillers at Green Leaf Mall foul in monsoon season. A chemical descale held for a year; a plain wash only lasted about a month."),
    dict(author="Arjun Rao", role="Ductable and VRV", years=7, machine_id="M-12",
         text="Water leaking from an indoor unit is usually a drain line laid without a trap or slope. Flush with nitrogen, re-lay with a slope and fit a trap. Do not just clear the blockage."),
    dict(author="Deepak Gowda", role="Daikin specialist", years=11,
         text="Reseat the inverter board connector before ordering a new PCB on Daikin VRV IV units. Two of the last three PCB orders were not needed. Check the board revision and firmware too."),
]


SKILLS = [
    dict(name="Brief for a technician", prompt="Write a short brief for the technician about this machine: the likely cause, what already failed so it is not repeated, what to do first, and which parts to bring. Cite the records.", shared=True),
    dict(name="Root cause analysis", prompt="Analyse this fault. List the most likely root causes in order, the evidence for each from our records, and the fixes that have failed before.", shared=True),
    dict(name="Summarize a document", prompt="Summarize this document in five bullets: what happened, what failed, what worked, and the lesson for the next person.", shared=True),
    dict(name="Handover note", prompt="Write a handover note for this site: quirks, access, recurring faults, and what to check first. Use only what our records say.", shared=True),
]


def main():
    with httpx.Client(base_url=BASE, timeout=120) as c:
        tok = c.post("/api/workspace/guest").json()["token"]
        c.headers["Authorization"] = "Bearer " + tok
        have = {d["name"] for d in c.get("/api/docs").json()}
        for f in sorted(SAMPLE.glob("*")):
            if f.name in have:
                print("skip", f.name)
                continue
            r = c.post("/api/docs", files={"file": (f.name, f.read_bytes())}, data={"author": "Sample data"})
            print("doc", f.name, r.status_code, r.json().get("sections", r.text[:100]))
        have_skills = {k["name"] for k in c.get("/api/skills").json()}
        for k in SKILLS:
            if k["name"] not in have_skills:
                print("skill", k["name"], c.post("/api/skills", json=k).status_code)
        if c.get("/api/company").json()["totals"]["notes"] >= len(NOTES):
            print("notes already added")
            return
        for n in NOTES:
            r = c.post("/api/knowledge", json=n)
            print("note", n["author"], r.status_code)


if __name__ == "__main__":
    main()
