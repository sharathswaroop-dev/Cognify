"""Generate a realistic synthetic dataset for SiteMemory.

Company: CoolCare Facility Services, Bengaluru (fictional HVAC service contractor).
Everything here is synthetic. Output: backend/data/*.json

Run:  python scripts/generate_data.py
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)
OUT = Path(__file__).resolve().parent.parent / "backend" / "data"
OUT.mkdir(parents=True, exist_ok=True)

COMPANY = {
    "name": "CoolCare Facility Services",
    "city": "Bengaluru",
    "description": "HVAC installation and maintenance contractor serving 9 commercial sites.",
}

TECHNICIANS = [
    {"id": "T-01", "name": "Arjun Rao", "years": 9, "joined": "2017-06-01", "speciality": "VRV / VRF systems"},
    {"id": "T-02", "name": "Suresh Kumar", "years": 6, "joined": "2020-02-10", "speciality": "Chillers and AHUs"},
    {"id": "T-03", "name": "Meena Iyer", "years": 5, "joined": "2021-07-19", "speciality": "Precision cooling"},
    {"id": "T-04", "name": "Farhan Sheikh", "years": 3, "joined": "2023-04-03", "speciality": "Split and cassette units"},
    {"id": "T-05", "name": "Deepak Gowda", "years": 4, "joined": "2022-09-12", "speciality": "Ductable units"},
    {"id": "T-06", "name": "Ravi Shankar", "years": 1, "joined": "2026-10-06", "speciality": "General HVAC (new joiner)"},
]

SITES = [
    {"id": "S-01", "name": "Orion Tech Park, Tower B", "area": "Whitefield",
     "contact": "Priya Nair (Facility Manager)", "notes": [
         "Roof access key is kept at the B-wing security desk; sign the register.",
         "Gate code changed to 4471 in Sep 2026.",
         "Priya prefers a phone call before 10am; she does not reply to WhatsApp during the day.",
         "Roof work after 6pm needs a hot-work / height permit from building security.",
         "Grid voltage dips to ~190V during afternoon peak; noted on multiple visits."]},
    {"id": "S-02", "name": "Sunrise Multispeciality Hospital", "area": "Indiranagar",
     "contact": "Dr. Kavitha Rao (Admin) / Manjunath (Biomedical)", "notes": [
         "OT and ICU units are critical: inform Manjunath before switching anything off.",
         "Use the service lift behind the pharmacy; main lifts are for patients.",
         "Visitor parking is full after 9am; park at the rear gate on 12th Main."]},
    {"id": "S-03", "name": "Green Leaf Mall", "area": "Koramangala",
     "contact": "Imran Pasha (Mall Engineering)", "notes": [
         "Plant room is on B2; collect the key from the engineering office on B1.",
         "No noisy work inside the mall between 11am and 9pm; plan plant-room work early.",
         "Mall security asks for the job card copy at entry."]},
    {"id": "S-04", "name": "Nexa Data Center, Hall 2", "area": "Electronic City",
     "contact": "Sanjay Menon (DC Operations)", "notes": [
         "Strict access: carry company ID and get pre-approved 24 hours ahead.",
         "No food or liquids on the data hall floor.",
         "Any unit shutdown needs a change ticket from Sanjay's team."]},
    {"id": "S-05", "name": "Hotel Silver Palm", "area": "MG Road",
     "contact": "Rahul D'Souza (Chief Engineer)", "notes": [
         "Guest room work only between 11am and 4pm (checkout to check-in).",
         "Use the staff entrance on Church Street side."]},
    {"id": "S-06", "name": "Vega Pharma Plant", "area": "Peenya Industrial Area",
     "contact": "Lakshmi Prasad (Utilities)", "notes": [
         "Clean-room AHUs: gowning required; allow 20 minutes for entry procedure.",
         "Safety induction video must be watched once per year at the gate."]},
    {"id": "S-07", "name": "Kaveri Corporate Office", "area": "HSR Layout",
     "contact": "Nikhil Jain (Admin)", "notes": [
         "Office is empty on Saturdays; best day for planned maintenance.",
         "Ceiling cassettes are 3.6m high; carry the tall ladder."]},
    {"id": "S-08", "name": "Lakeview Apartments, Block C", "area": "Hebbal",
     "contact": "Association office (Mr. Venkatesh)", "notes": [
         "Terrace door is locked; key with the association office (open 10am-1pm)."]},
    {"id": "S-09", "name": "Brookfield Business Centre", "area": "ITPL Main Road",
     "contact": "Anita George (Operations)", "notes": [
         "New customer from Nov 2026. No visit history yet."]},
]

# Fault profiles: what the symptom looks like, what people usually try first (and whether it works),
# the real root cause, the fix that sticks, parts, and a follow-up recommendation.
PROFILES = {
    "vrv_contactor": {
        "symptoms": ["Not cooling; outdoor unit tripping", "Outdoor unit trips within minutes of start",
                     "Indoor units blowing warm air, outdoor unit shows E3/trip"],
        "failed": [("Reset outdoor unit breaker", "Unit restarted but tripped again within ~30 minutes."),
                   ("Topped up refrigerant (R410A)", "Pressures were already normal; no improvement. Unit tripped again.")],
        "root_cause": "Compressor contactor (magnetic relay) coil burnt; contacts pitted. Linked to supply voltage dips (~190V).",
        "fix": "Replaced compressor contactor and checked phase voltages.",
        "parts": ["Compressor contactor 24V coil (DK-CTR-24V)"],
        "recommend": "Install a servo voltage stabilizer for the outdoor unit; customer approval pending.",
    },
    "chiller_head_pressure": {
        "symptoms": ["Chiller high head pressure alarm", "Chiller tripping on HP during afternoon",
                     "Chilled water temperature rising above setpoint"],
        "failed": [("Reset HP alarm and restarted chiller", "Ran for ~2 hours then tripped again on HP."),
                   ("Cleaned condenser strainer", "Slight improvement only; alarm returned next afternoon.")],
        "root_cause": "Condenser tubes scaled due to hard cooling-tower water; approach temperature 6.5C (normal <2C).",
        "fix": "Chemical descaling of condenser tubes and cooling-tower water treatment dosing corrected.",
        "parts": ["Descaling chemical (40L)", "Condenser end-cover gasket set"],
        "recommend": "Quarterly water-quality check on the cooling tower.",
    },
    "split_leak": {
        "symptoms": ["Water dripping from indoor unit", "Indoor unit leaking water onto false ceiling",
                     "Water leakage from wall-mounted split"],
        "failed": [("Cleaned air filters", "Leak continued the same evening."),
                   ("Cleaned drain tray only", "Leak stopped for 2 days, then returned.")],
        "root_cause": "Drain pipe clogged with algae and laid with reverse slope after an interior renovation.",
        "fix": "Flushed drain line with nitrogen, re-laid drain pipe with proper slope and added a trap.",
        "parts": ["PVC drain pipe 20mm (3m)", "Drain trap"],
        "recommend": "Add drain line to the quarterly PM checklist for this site.",
    },
    "precision_fan": {
        "symptoms": ["High return-air temperature alarm on precision AC", "Precision AC airflow low; hall temperature rising",
                     "PAC unit showing 'Fan Fail' intermittently"],
        "failed": [("Restarted the unit from controller", "Alarm cleared, came back within the hour."),
                   ("Replaced air filters", "No change in airflow.")],
        "root_cause": "EC fan motor drive fault on fan 2; fan running at ~40% speed.",
        "fix": "Replaced EC fan module on fan 2 and recalibrated airflow sensor.",
        "parts": ["EC fan module 500mm (EBM-R3G500)"],
        "recommend": "Keep one spare EC fan module on site; these units are 7 years old.",
    },
    "cassette_u4": {
        "symptoms": ["Cassette unit showing U4 error", "Indoor unit not responding, error U4 on remote",
                     "Several cassettes in one zone stopped with communication error"],
        "failed": [("Power reset of indoor and outdoor units", "Worked for a few hours; U4 returned next morning."),
                   ("Replaced remote controller", "Error persisted.")],
        "root_cause": "Corroded and loose transmission wiring at F1-F2 terminals near the ceiling, likely from condensation.",
        "fix": "Re-terminated F1-F2 transmission wiring with new lugs and sealed the junction box.",
        "parts": ["Ring lugs and heat-shrink set", "IP65 junction box"],
        "recommend": "Inspect the other junction boxes in the same ceiling zone.",
    },
    "ahu_bearing": {
        "symptoms": ["AHU making loud grinding noise", "Excessive vibration on AHU blower",
                     "AHU noise complaint from tenants"],
        "failed": [("Tightened and aligned V-belts", "Noise reduced briefly, returned in a day."),
                   ("Greased blower bearings", "No lasting improvement.")],
        "root_cause": "Blower shaft bearing (drive end) worn out; shaft play measured.",
        "fix": "Replaced both blower bearings and realigned pulley.",
        "parts": ["Bearing 6206-2RS (x2)", "V-belt B-48"],
        "recommend": "Vibration check every 6 months.",
    },
    "ductable_leak": {
        "symptoms": ["Ductable AC low cooling", "Conference room not cooling below 27C",
                     "Ductable unit running continuously, poor cooling"],
        "failed": [("Topped up refrigerant (R22/R410A)", "Cooling recovered but dropped again within 3 weeks."),
                   ("Cleaned indoor coil", "Marginal improvement only.")],
        "root_cause": "Refrigerant leak at the flare joint on the liquid line near the indoor unit.",
        "fix": "Nitrogen pressure test, brazed the joint instead of flare, vacuumed and recharged.",
        "parts": ["Copper coupler 3/8\"", "Brazing rods", "Refrigerant R410A (3kg)"],
        "recommend": "Avoid flare joints on this line; use brazed joints.",
    },
}

MACHINES = [
    # id, site, brand/model, type, location, install year, profile
    ("M-07", "S-01", "Daikin VRV IV RXYQ10", "VRV outdoor unit", "Roof, Bay 3", 2019, "vrv_contactor"),
    ("M-08", "S-01", "Daikin VRV IV RXYQ12", "VRV outdoor unit", "Roof, Bay 4", 2019, "vrv_contactor"),
    ("M-09", "S-01", "Daikin FXFQ cassette", "Cassette indoor unit", "Floor 6, cafeteria", 2019, "cassette_u4"),
    ("M-11", "S-02", "Carrier 30XW screw chiller", "Water-cooled chiller", "Plant room, Chiller 1", 2016, "chiller_head_pressure"),
    ("M-12", "S-02", "Blue Star split 2T", "Split AC", "ICU nurse station", 2021, "split_leak"),
    ("M-13", "S-02", "Zeco AHU 15000 CFM", "Air handling unit", "OT block AHU-2", 2017, "ahu_bearing"),
    ("M-21", "S-03", "Voltas ductable 11T", "Ductable AC", "Food court", 2018, "ductable_leak"),
    ("M-22", "S-03", "Carrier 30XW screw chiller", "Water-cooled chiller", "B2 plant room, Chiller 2", 2015, "chiller_head_pressure"),
    ("M-23", "S-03", "Zeco AHU 20000 CFM", "Air handling unit", "Level 1 AHU-4", 2015, "ahu_bearing"),
    ("M-31", "S-04", "Vertiv Liebert PEX 4", "Precision AC", "Hall 2, PAC-03", 2019, "precision_fan"),
    ("M-32", "S-04", "Vertiv Liebert PEX 4", "Precision AC", "Hall 2, PAC-05", 2019, "precision_fan"),
    ("M-41", "S-05", "Daikin VRV IV RXYQ14", "VRV outdoor unit", "Terrace, east", 2018, "vrv_contactor"),
    ("M-42", "S-05", "Mitsubishi Electric cassette", "Cassette indoor unit", "Banquet hall", 2020, "cassette_u4"),
    ("M-51", "S-06", "Zeco AHU clean-room", "Air handling unit", "Clean room AHU-1", 2020, "ahu_bearing"),
    ("M-52", "S-06", "Blue Star ductable 8.5T", "Ductable AC", "QC lab", 2019, "ductable_leak"),
    ("M-61", "S-07", "Daikin VRV IV RXYQ10", "VRV outdoor unit", "Terrace", 2020, "vrv_contactor"),
    ("M-62", "S-07", "LG cassette 2T", "Cassette indoor unit", "Board room", 2020, "cassette_u4"),
    ("M-63", "S-07", "Voltas split 1.5T", "Split AC", "Server room", 2022, "split_leak"),
    ("M-71", "S-08", "Daikin VRV IV RXYQ8", "VRV outdoor unit", "Terrace, Block C", 2021, "vrv_contactor"),
    ("M-72", "S-08", "Blue Star split 1.5T", "Split AC", "Clubhouse gym", 2022, "split_leak"),
    ("M-91", "S-09", "Daikin VRV IV RXYQ12", "VRV outdoor unit", "Roof", 2024, "vrv_contactor"),
]

START = date(2025, 11, 1)
END = date(2026, 10, 31)
SENIOR = ["T-01", "T-02", "T-03", "T-04", "T-05"]


def rand_date(lo, hi):
    return lo + timedelta(days=random.randint(0, (hi - lo).days))


def visit_record(job_id, incident_id, visit_no, d, tech, machine, symptom, actions, outcome, prof, found_cause, extra_note=""):
    return {
        "job_id": job_id,
        "incident_id": incident_id,
        "visit_no": visit_no,
        "date": d.isoformat(),
        "technician_id": tech,
        "machine_id": machine[0],
        "site_id": machine[1],
        "symptom": symptom,
        "actions": actions,
        "root_cause": prof["root_cause"] if found_cause else "",
        "fix": prof["fix"] if found_cause else "",
        "parts_used": prof["parts"] if found_cause else [],
        "outcome": outcome,  # resolved | revisit_needed
        "recommendation": prof["recommend"] if found_cause else "",
        "notes": extra_note,
    }


def build_jobs():
    jobs = []
    jn = 1001
    inc = 1
    for m in MACHINES:
        mid, sid, model, mtype, loc, year, pkey = m
        prof = PROFILES[pkey]
        if mid == "M-07" or sid == "S-09":
            continue  # handled by hand below / no history
        n_incidents = random.choice([1, 2, 2, 3])
        dates = sorted(rand_date(START, END - timedelta(days=10)) for _ in range(n_incidents))
        for d in dates:
            tech = random.choice(SENIOR)
            symptom = random.choice(prof["symptoms"])
            if random.random() < 0.55:
                # First visit tries the common quick fix and fails -> second visit fixes it.
                act, res = random.choice(prof["failed"])
                jobs.append(visit_record(f"J-{jn}", f"I-{inc:03d}", 1, d, tech, m, symptom,
                                         [{"action": act, "result": "failed", "detail": res}],
                                         "revisit_needed", prof, False,
                                         "Root cause not confirmed on first visit."))
                jn += 1
                d2 = d + timedelta(days=random.randint(1, 4))
                tech2 = random.choice(SENIOR)
                jobs.append(visit_record(f"J-{jn}", f"I-{inc:03d}", 2, d2, tech2, m, symptom,
                                         [{"action": prof["fix"], "result": "worked", "detail": "Unit stable after 2 hours of monitoring."}],
                                         "resolved", prof, True))
                jn += 1
            else:
                jobs.append(visit_record(f"J-{jn}", f"I-{inc:03d}", 1, d, tech, m, symptom,
                                         [{"action": prof["fix"], "result": "worked", "detail": "Diagnosed on first visit; unit stable after monitoring."}],
                                         "resolved", prof, True))
                jn += 1
            inc += 1

    # Hand-written history for the demo machine M-07 (Orion Tech Park, Bay 3).
    p = PROFILES["vrv_contactor"]
    m07 = next(x for x in MACHINES if x[0] == "M-07")
    hand = [
        visit_record("J-0901", "I-901", 1, date(2026, 3, 12), "T-01", m07, "Not cooling; outdoor unit tripping",
                     [{"action": "Reset outdoor unit breaker", "result": "failed",
                       "detail": "Unit restarted but tripped again within 30 minutes."}],
                     "revisit_needed", p, False,
                     "Measured supply at 192V around 3pm. Suspect contactor; part not in van."),
        visit_record("J-0902", "I-901", 2, date(2026, 3, 14), "T-01", m07, "Not cooling; outdoor unit tripping",
                     [{"action": "Replaced compressor contactor (DK-CTR-24V)", "result": "worked",
                       "detail": "Old contactor coil burnt, contacts pitted. Unit stable for 3 hours."}],
                     "resolved", p, True, "Told Priya the voltage dips will keep killing contactors."),
        visit_record("J-0947", "I-947", 1, date(2026, 8, 19), "T-02", m07, "Outdoor unit trips within minutes of start",
                     [{"action": "Reset outdoor unit breaker", "result": "failed", "detail": "Tripped again in 20 minutes."},
                      {"action": "Topped up refrigerant (R410A)", "result": "failed",
                       "detail": "Pressures were already normal; no improvement."}],
                     "revisit_needed", p, False, "Did not have the contactor spare. 2 hours lost on gas top-up."),
        visit_record("J-0949", "I-947", 2, date(2026, 8, 21), "T-02", m07, "Outdoor unit trips within minutes of start",
                     [{"action": "Replaced compressor contactor (DK-CTR-24V)", "result": "worked",
                       "detail": "Same failure as March: coil burnt."}],
                     "resolved", p, True, "Quoted servo stabilizer (Rs 68,000); Priya to get approval."),
    ]
    jobs.extend(hand)
    jobs.sort(key=lambda j: j["date"])
    return jobs


def build_open_jobs():
    return [
        {"job_id": "J-1201", "date": "2026-11-07", "machine_id": "M-07", "site_id": "S-01", "technician_id": "T-06",
         "symptom": "Bay 3 not cooling. Outdoor unit tripped twice this morning.", "priority": "High",
         "reported_by": "Priya Nair", "demo_role": "Hero: same machine, rich history. Memory turns a 2-visit job into 1."},
        {"job_id": "J-1202", "date": "2026-11-07", "machine_id": "M-91", "site_id": "S-09", "technician_id": "T-06",
         "symptom": "Outdoor unit tripping, offices warm since lunch.", "priority": "Medium",
         "reported_by": "Anita George", "demo_role": "New site, no machine history: memory still helps via the model-wide pattern."},
        {"job_id": "J-1203", "date": "2026-11-08", "machine_id": "M-12", "site_id": "S-02", "technician_id": "T-04",
         "symptom": "Split AC at ICU nurse station dripping water onto the counter.", "priority": "High",
         "reported_by": "Manjunath", "demo_role": "Shows site rules being recalled (ICU, service lift)."},
        {"job_id": "J-1204", "date": "2026-11-08", "machine_id": "M-31", "site_id": "S-04", "technician_id": "T-06",
         "symptom": "Hall 2 PAC-03 high return-air temperature alarm.", "priority": "Critical",
         "reported_by": "Sanjay Menon", "demo_role": "Data center access rules plus known EC fan pattern."},
    ]


def main():
    machines = [{"id": m[0], "site_id": m[1], "model": m[2], "type": m[3], "location": m[4],
                 "installed": m[5], "model_family": m[2].rsplit(" ", 1)[0] if "RXYQ" in m[2] else m[2]}
                for m in MACHINES]
    jobs = build_jobs()
    files = {
        "company.json": COMPANY,
        "technicians.json": TECHNICIANS,
        "sites.json": SITES,
        "machines.json": machines,
        "job_history.json": jobs,
        "open_jobs.json": build_open_jobs(),
    }
    for name, data in files.items():
        (OUT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Wrote {len(jobs)} past visits, {len(machines)} machines, {len(SITES)} sites to {OUT}")


if __name__ == "__main__":
    main()
