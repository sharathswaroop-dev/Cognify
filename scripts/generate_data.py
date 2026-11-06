"""Generate the synthetic dataset for SiteMemory (a fictional HVAC contractor in Bengaluru).

12 sites, 50 machines, ~250 visits over Nov 2025 - Oct 2026, plus alarms with remote-fix outcomes, parts stock and
demo scenarios. The history deliberately contains the messy things real service logs contain:
  * wrong diagnoses (a part is replaced on a hunch and the fault stays)
  * failed first attempts that look sensible (reset, top-up) and waste a visit
  * parts shortages (the right cause is found but the part is not on the van)
  * fixes that look fixed and then come back (a refrigerant top-up that holds three weeks)
  * a fix that stops working on a newer generation of units (contactor swap vs inverter board, units installed 2023+)
Some machines are held out: they are the test set for the evaluation and are never used for tuning.

Run:  python scripts/generate_data.py          (deterministic; overwrites backend/data/*.json)
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

rng = random.Random(2026)
OUT = Path(__file__).resolve().parent.parent / "backend" / "data"
OUT.mkdir(parents=True, exist_ok=True)
START, END = date(2025, 11, 1), date(2026, 10, 31)

COMPANY = {"name": "CoolCare Facility Services", "city": "Bengaluru",
           "description": "HVAC installation and maintenance contractor serving 12 commercial sites."}

TECHS = [
    {"id": "T-01", "name": "Arjun Rao", "years": 9, "joined": "2017-06-01", "speciality": "VRV / VRF systems"},
    {"id": "T-02", "name": "Suresh Kumar", "years": 6, "joined": "2020-02-10", "speciality": "Chillers and AHUs"},
    {"id": "T-03", "name": "Meena Iyer", "years": 5, "joined": "2021-07-19", "speciality": "Precision cooling"},
    {"id": "T-04", "name": "Farhan Sheikh", "years": 3, "joined": "2023-04-03", "speciality": "Split and cassette units"},
    {"id": "T-05", "name": "Deepak Gowda", "years": 4, "joined": "2022-09-12", "speciality": "Ductable units"},
    {"id": "T-06", "name": "Ravi Shankar", "years": 1, "joined": "2026-10-06", "speciality": "General HVAC (new joiner)"},
]
SENIOR = ["T-01", "T-02", "T-03", "T-04", "T-05"]

SITES = [
    {"id": "S-01", "name": "Orion Tech Park, Tower B", "area": "Whitefield", "contact": "Priya Nair (Facility Manager)", "notes": [
        "Roof access key is kept at the B-wing security desk; sign the register.", "Gate code changed to 4471 in Sep 2026.",
        "Priya prefers a phone call before 10am; she does not reply to WhatsApp during the day.",
        "Roof work after 6pm needs a hot-work / height permit from building security.",
        "Grid voltage dips to ~190V during afternoon peak; noted on multiple visits."]},
    {"id": "S-02", "name": "Sunrise Multispeciality Hospital", "area": "Indiranagar", "contact": "Dr. Kavitha Rao (Admin) / Manjunath (Biomedical)", "notes": [
        "OT and ICU units are critical: inform Manjunath before switching anything off.",
        "Use the service lift behind the pharmacy; main lifts are for patients.",
        "Visitor parking is full after 9am; park at the rear gate on 12th Main."]},
    {"id": "S-03", "name": "Green Leaf Mall", "area": "Koramangala", "contact": "Imran Pasha (Mall Engineering)", "notes": [
        "Plant room is on B2; collect the key from the engineering office on B1.",
        "No noisy work inside the mall between 11am and 9pm; plan plant-room work early.", "Mall security asks for the job card copy at entry."]},
    {"id": "S-04", "name": "Nexa Data Center, Hall 2", "area": "Electronic City", "contact": "Sanjay Menon (DC Operations)", "notes": [
        "Strict access: carry company ID and get pre-approved 24 hours ahead.", "No food or liquids on the data hall floor.",
        "Any unit shutdown needs a change ticket from Sanjay's team."]},
    {"id": "S-05", "name": "Hotel Silver Palm", "area": "MG Road", "contact": "Rahul D'Souza (Chief Engineer)", "notes": [
        "Guest room work only between 11am and 4pm (checkout to check-in).", "Use the staff entrance on Church Street side."]},
    {"id": "S-06", "name": "Vega Pharma Plant", "area": "Peenya Industrial Area", "contact": "Lakshmi Prasad (Utilities)", "notes": [
        "Clean-room AHUs: gowning required; allow 20 minutes for entry procedure.", "Safety induction video must be watched once per year at the gate."]},
    {"id": "S-07", "name": "Kaveri Corporate Office", "area": "HSR Layout", "contact": "Nikhil Jain (Admin)", "notes": [
        "Office is empty on Saturdays; best day for planned maintenance.", "Ceiling cassettes are 3.6m high; carry the tall ladder."]},
    {"id": "S-08", "name": "Lakeview Apartments, Block C", "area": "Hebbal", "contact": "Association office (Mr. Venkatesh)", "notes": [
        "Terrace door is locked; key with the association office (open 10am-1pm)."]},
    {"id": "S-09", "name": "Brookfield Business Centre", "area": "ITPL Main Road", "contact": "Anita George (Operations)", "notes": [
        "New customer from Nov 2026. No visit history yet."]},
    {"id": "S-10", "name": "Infinity Software Campus", "area": "Manyata Tech Park", "contact": "Rohit Bhat (Admin)", "notes": [
        "Vehicle entry needs a gate pass from the admin desk 1 hour ahead.", "Server room units: work only after 8pm unless it is an outage."]},
    {"id": "S-11", "name": "Cauvery Diagnostics Lab", "area": "Jayanagar", "contact": "Dr. Sunita Hegde (Lab Head)", "notes": [
        "Sample storage rooms must not exceed 8C: tell Dr. Hegde before any shutdown.", "Visitors must wear shoe covers inside the lab."]},
    {"id": "S-12", "name": "Skyline Residency Clubhouse", "area": "Bellandur", "contact": "Facility desk (Mr. Anwar)", "notes": [
        "Pool-side units: bring wet-weather covers in monsoon season.", "Residents' quiet hours 1pm-3pm."]},
]

# ---- fault classes ----------------------------------------------------------------------------------------------------
# remote: the only remote actions allowed are reset, setpoint, read_log.
FAULTS = {
    "vrv_contactor": {
        "symptoms": ["Not cooling; outdoor unit tripping", "Outdoor unit trips within minutes of start", "Indoor units blowing warm air, outdoor unit shows E3/trip"],
        "failed": [("Reset outdoor unit breaker", "Unit restarted but tripped again within ~30 minutes."),
                   ("Topped up refrigerant (R410A)", "Pressures were already normal; no improvement. Unit tripped again.")],
        "wrong": [("compressor relay board fault", "Replaced compressor relay board (DK-RLY-B2)", "Unit still tripped within 20 minutes. Relay board was healthy.", "Compressor relay board (DK-RLY-B2)")],
        "evidence": "Supply measured at 188-194V in the afternoon; contactor coil burnt, contacts pitted.",
        "root_cause": "Compressor contactor (magnetic relay) coil burnt; contacts pitted. Linked to supply voltage dips (~190V).",
        "fix": "Replaced compressor contactor and checked phase voltages.", "parts": ["Compressor contactor 24V coil (DK-CTR-24V)"],
        "recommend": "Install a servo voltage stabilizer for the outdoor unit; customer approval pending.",
        "code": ("E3", "High-pressure / compressor protection trip"), "remote": ("reset", "Remote fault reset via controller", False), "volts": (186, 194)},
    "vrv_pcb": {
        "symptoms": ["Outdoor unit trips within minutes of start", "Not cooling; outdoor unit tripping"],
        "failed": [("Replaced compressor contactor and checked phase voltages.", "Contactor swapped as per the usual fix, but the unit tripped again within 20 minutes. Supply voltage was normal.")],
        "wrong": [("compressor relay board fault", "Replaced compressor relay board (DK-RLY-B2)", "Unit still tripped. Supply voltage was normal.", "Compressor relay board (DK-RLY-B2)")],
        "evidence": "Supply voltage normal (226-230V). DC bus overvoltage events in the controller log.",
        "root_cause": "Inverter PCB (A2P, revision C) causes DC bus overvoltage trips on units installed 2023 onwards; supply voltage was normal.",
        "fix": "Replaced inverter PCB (A2P) and updated its firmware.", "parts": ["Inverter PCB A2P rev D (DK-PCB-A2P-D)"],
        "recommend": "On units installed from 2023, check the inverter PCB before replacing the contactor.",
        "code": ("L8", "Compressor overcurrent"), "remote": ("reset", "Remote fault reset via controller", False), "volts": (226, 231)},
    "chiller_head_pressure": {
        "symptoms": ["Chiller high head pressure alarm", "Chiller tripping on HP during afternoon", "Chilled water temperature rising above setpoint"],
        "failed": [("Reset HP alarm and restarted chiller", "Ran for ~2 hours then tripped again on HP."),
                   ("Cleaned condenser strainer", "Slight improvement only; alarm returned next afternoon.")],
        "wrong": [("faulty high-pressure transducer", "Replaced HP pressure transducer (CAR-HPT-30)", "Reading matched the manual gauge: the transducer was fine.", "HP pressure transducer (CAR-HPT-30)")],
        "evidence": "Condenser approach temperature 6.5C (normal under 2C); tube scaling visible.",
        "root_cause": "Condenser tubes scaled due to hard cooling-tower water; approach temperature 6.5C (normal <2C).",
        "fix": "Chemical descaling of condenser tubes and cooling-tower water treatment dosing corrected.",
        "parts": ["Descaling chemical (40L)", "Condenser end-cover gasket set"], "recommend": "Quarterly water-quality check on the cooling tower.",
        "code": ("HP", "Condenser high-pressure trip"), "remote": ("reset", "Remote chiller reset via controller", True), "volts": (396, 408)},
    "split_leak": {
        "symptoms": ["Water dripping from indoor unit", "Indoor unit leaking water onto false ceiling", "Water leakage from wall-mounted split"],
        "failed": [("Cleaned air filters", "Leak continued the same evening."), ("Cleaned drain tray only", "Leak stopped for 2 days, then returned.")],
        "wrong": [("faulty condensate pump", "Replaced condensate pump (SPL-CP-12)", "Pump was working; the drain line was blocked downstream.", "Condensate pump (SPL-CP-12)")],
        "evidence": "Drain pipe full of algae; reverse slope found after an interior renovation.",
        "root_cause": "Drain pipe clogged with algae and laid with reverse slope after an interior renovation.",
        "fix": "Flushed drain line with nitrogen, re-laid drain pipe with proper slope and added a trap.",
        "parts": ["PVC drain pipe 20mm (3m)", "Drain trap"], "recommend": "Add drain line to the quarterly PM checklist for this site.",
        "code": ("WL", "Water leak / drain sensor"), "remote": (None, None, False), "volts": None},
    "precision_fan": {
        "symptoms": ["High return-air temperature alarm on precision AC", "Precision AC airflow low; hall temperature rising", "PAC unit showing 'Fan Fail' intermittently"],
        "failed": [("Restarted the unit from controller", "Alarm cleared, came back within the hour."), ("Replaced air filters", "No change in airflow.")],
        "wrong": [("airflow sensor drift", "Replaced airflow sensor (VRT-AFS-2)", "Sensor reading was correct; one fan was the problem.", "Airflow sensor (VRT-AFS-2)")],
        "evidence": "Fan 2 running at ~40% speed; drive fault logged.",
        "root_cause": "EC fan motor drive fault on fan 2; fan running at ~40% speed.",
        "fix": "Replaced EC fan module on fan 2 and recalibrated airflow sensor.", "parts": ["EC fan module 500mm (EBM-R3G500)"],
        "recommend": "Keep one spare EC fan module on site; these units are 7 years old.",
        "code": ("HT", "High return-air temperature"), "remote": ("setpoint", "Remote setpoint and fan-speed adjustment via BMS", True), "volts": None},
    "cassette_u4": {
        "symptoms": ["Cassette unit showing U4 error", "Indoor unit not responding, error U4 on remote", "Several cassettes in one zone stopped with communication error"],
        "failed": [("Power reset of indoor and outdoor units", "Worked for a few hours; U4 returned next morning."), ("Replaced remote controller", "Error persisted.")],
        "wrong": [("indoor PCB failure", "Replaced indoor unit PCB (CAS-PCB-A1)", "Error persisted: the PCB was fine.", "Indoor unit PCB (CAS-PCB-A1)")],
        "evidence": "Corroded F1-F2 terminals found above the ceiling; insulation resistance low.",
        "root_cause": "Corroded and loose transmission wiring at F1-F2 terminals near the ceiling, likely from condensation.",
        "fix": "Re-terminated F1-F2 transmission wiring with new lugs and sealed the junction box.",
        "parts": ["Ring lugs and heat-shrink set", "IP65 junction box"], "recommend": "Inspect the other junction boxes in the same ceiling zone.",
        "code": ("U4", "Indoor-outdoor communication error"), "remote": ("reset", "Remote reset of the indoor group via BMS", True), "volts": None},
    "ahu_bearing": {
        "symptoms": ["AHU making loud grinding noise", "Excessive vibration on AHU blower", "AHU noise complaint from tenants"],
        "failed": [("Tightened and aligned V-belts", "Noise reduced briefly, returned in a day."), ("Greased blower bearings", "No lasting improvement.")],
        "wrong": [("belt wear", "Replaced V-belt set (B-48)", "Noise unchanged: the bearing was the source.", "V-belt B-48")],
        "evidence": "Shaft play measured at the drive end; vibration 11 mm/s.",
        "root_cause": "Blower shaft bearing (drive end) worn out; shaft play measured.",
        "fix": "Replaced both blower bearings and realigned pulley.", "parts": ["Bearing 6206-2RS (x2)", "V-belt B-48"],
        "recommend": "Vibration check every 6 months.",
        "code": ("VB", "High vibration alarm"), "remote": ("read_log", "Read the vibration trend from the controller log", False), "volts": None},
    "ductable_leak": {
        "symptoms": ["Ductable AC low cooling", "Conference room not cooling below 27C", "Ductable unit running continuously, poor cooling"],
        "failed": [("Cleaned indoor coil", "Marginal improvement only.")],
        "temporary": ("Topped up refrigerant (R22/R410A)", "Cooling recovered at the visit."),
        "wrong": [("dirty condenser", "Chemically cleaned the condenser coil", "No change in cooling; the charge was low.", "Coil cleaner (5L)")],
        "evidence": "Pressure drop on nitrogen test at the flare joint near the indoor unit.",
        "root_cause": "Refrigerant leak at the flare joint on the liquid line near the indoor unit.",
        "fix": "Nitrogen pressure test, brazed the joint instead of flare, vacuumed and recharged.",
        "parts": ["Copper coupler 3/8\"", "Brazing rods", "Refrigerant R410A (3kg)"], "recommend": "Avoid flare joints on this line; use brazed joints.",
        "code": ("LC", "Low cooling capacity"), "remote": ("setpoint", "Remote setpoint reset via BMS", False), "volts": None},
}

# id, site, model, type, location, installed, fault class, holdout
MACHINES = [
    ("M-07", "S-01", "Daikin VRV IV RXYQ10", "VRV outdoor unit", "Roof, Bay 3", 2019, "vrv_contactor", True),
    ("M-08", "S-01", "Daikin VRV IV RXYQ12", "VRV outdoor unit", "Roof, Bay 4", 2019, "vrv_contactor", False),
    ("M-09", "S-01", "Daikin FXFQ cassette", "Cassette indoor unit", "Floor 6, cafeteria", 2019, "cassette_u4", False),
    ("M-10", "S-01", "Daikin FXFQ cassette", "Cassette indoor unit", "Floor 7, open office", 2019, "cassette_u4", False),
    ("M-11", "S-02", "Carrier 30XW screw chiller", "Water-cooled chiller", "Plant room, Chiller 1", 2016, "chiller_head_pressure", False),
    ("M-12", "S-02", "Blue Star split 2T", "Split AC", "ICU nurse station", 2021, "split_leak", True),
    ("M-13", "S-02", "Zeco AHU 15000 CFM", "Air handling unit", "OT block AHU-2", 2017, "ahu_bearing", False),
    ("M-14", "S-02", "Blue Star split 1.5T", "Split AC", "Pharmacy", 2020, "split_leak", False),
    ("M-21", "S-03", "Voltas ductable 11T", "Ductable AC", "Food court", 2018, "ductable_leak", True),
    ("M-22", "S-03", "Carrier 30XW screw chiller", "Water-cooled chiller", "B2 plant room, Chiller 2", 2015, "chiller_head_pressure", True),
    ("M-23", "S-03", "Zeco AHU 20000 CFM", "Air handling unit", "Level 1 AHU-4", 2015, "ahu_bearing", True),
    ("M-24", "S-03", "Voltas ductable 8T", "Ductable AC", "Management office", 2019, "ductable_leak", False),
    ("M-31", "S-04", "Vertiv Liebert PEX 4", "Precision AC", "Hall 2, PAC-03", 2019, "precision_fan", True),
    ("M-32", "S-04", "Vertiv Liebert PEX 4", "Precision AC", "Hall 2, PAC-05", 2019, "precision_fan", False),
    ("M-33", "S-04", "Vertiv Liebert PEX 4", "Precision AC", "Hall 2, PAC-07", 2020, "precision_fan", False),
    ("M-41", "S-05", "Daikin VRV IV RXYQ14", "VRV outdoor unit", "Terrace, east", 2018, "vrv_contactor", False),
    ("M-42", "S-05", "Mitsubishi Electric cassette", "Cassette indoor unit", "Banquet hall", 2020, "cassette_u4", False),
    ("M-43", "S-05", "Daikin VRV IV RXYQ8", "VRV outdoor unit", "Terrace, west", 2024, "vrv_pcb", False),
    ("M-51", "S-06", "Zeco AHU clean-room", "Air handling unit", "Clean room AHU-1", 2020, "ahu_bearing", False),
    ("M-52", "S-06", "Blue Star ductable 8.5T", "Ductable AC", "QC lab", 2019, "ductable_leak", False),
    ("M-53", "S-06", "Zeco AHU clean-room", "Air handling unit", "Clean room AHU-2", 2020, "ahu_bearing", False),
    ("M-61", "S-07", "Daikin VRV IV RXYQ10", "VRV outdoor unit", "Terrace", 2020, "vrv_contactor", False),
    ("M-62", "S-07", "LG cassette 2T", "Cassette indoor unit", "Board room", 2020, "cassette_u4", False),
    ("M-63", "S-07", "Voltas split 1.5T", "Split AC", "Server room", 2022, "split_leak", False),
    ("M-64", "S-07", "Daikin VRV IV RXYQ12", "VRV outdoor unit", "Rooftop", 2024, "vrv_pcb", False),
    ("M-71", "S-08", "Daikin VRV IV RXYQ8", "VRV outdoor unit", "Terrace, Block C", 2021, "vrv_contactor", False),
    ("M-72", "S-08", "Blue Star split 1.5T", "Split AC", "Clubhouse gym", 2022, "split_leak", False),
    ("M-73", "S-08", "Daikin VRV IV RXYQ14", "VRV outdoor unit", "Terrace, north", 2023, "vrv_pcb", False),
    ("M-74", "S-08", "Voltas split 2T", "Split AC", "Association office", 2021, "split_leak", False),
    ("M-91", "S-09", "Daikin VRV IV RXYQ12", "VRV outdoor unit", "Roof", 2024, "vrv_pcb", True),
    ("M-92", "S-09", "Blue Star split 2T", "Split AC", "Reception", 2024, "split_leak", False),
    ("M-101", "S-10", "Daikin VRV IV RXYQ10", "VRV outdoor unit", "Block A roof", 2020, "vrv_contactor", False),
    ("M-102", "S-10", "Daikin VRV IV RXYQ12", "VRV outdoor unit", "Block B roof", 2023, "vrv_pcb", False),
    ("M-103", "S-10", "Vertiv Liebert PEX 4", "Precision AC", "Server room 1", 2021, "precision_fan", False),
    ("M-104", "S-10", "Vertiv Liebert PEX 4", "Precision AC", "Server room 2", 2021, "precision_fan", False),
    ("M-105", "S-10", "Carrier 30XW screw chiller", "Water-cooled chiller", "Central plant", 2018, "chiller_head_pressure", False),
    ("M-106", "S-10", "Zeco AHU 20000 CFM", "Air handling unit", "Cafeteria AHU", 2019, "ahu_bearing", False),
    ("M-111", "S-11", "Blue Star split 2T", "Split AC", "Sample storage 1", 2022, "split_leak", False),
    ("M-112", "S-11", "Voltas ductable 5T", "Ductable AC", "Reception lab", 2021, "ductable_leak", False),
    ("M-113", "S-11", "Mitsubishi Electric cassette", "Cassette indoor unit", "Pathology", 2022, "cassette_u4", True),
    ("M-114", "S-11", "Daikin VRV IV RXYQ8", "VRV outdoor unit", "Terrace", 2019, "vrv_contactor", False),
    ("M-115", "S-11", "Blue Star split 1.5T", "Split AC", "Sample storage 2", 2022, "split_leak", False),
    ("M-121", "S-12", "Daikin VRV IV RXYQ10", "VRV outdoor unit", "Clubhouse roof", 2021, "vrv_contactor", False),
    ("M-122", "S-12", "Voltas ductable 8T", "Ductable AC", "Banquet room", 2020, "ductable_leak", False),
    ("M-123", "S-12", "LG cassette 2T", "Cassette indoor unit", "Gym", 2021, "cassette_u4", False),
    ("M-124", "S-12", "Zeco AHU 15000 CFM", "Air handling unit", "Pool hall AHU", 2018, "ahu_bearing", False),
    ("M-125", "S-12", "Blue Star split 1.5T", "Split AC", "Reception", 2023, "split_leak", False),
    ("M-126", "S-01", "Daikin VRV IV RXYQ14", "VRV outdoor unit", "Roof, Bay 5", 2022, "vrv_contactor", False),
    ("M-127", "S-04", "Carrier 30XW screw chiller", "Water-cooled chiller", "Plant room", 2017, "chiller_head_pressure", False),
    ("M-128", "S-06", "Voltas split 2T", "Split AC", "Admin block", 2021, "split_leak", False),
    ("M-129", "S-02", "Daikin FXFQ cassette", "Cassette indoor unit", "OPD waiting", 2020, "cassette_u4", False),
]
FAMILY = lambda model: model.rsplit(" ", 1)[0] if "RXYQ" in model else model


def day(d): return d.isoformat()


def visit(job, inc, no, d, tech, m, fc, symptom, suspected, actions, outcome, found, evidence="", missing=None, wrong=False, notes=""):
    f = FAULTS[fc]
    return {"job_id": job, "incident_id": inc, "visit_no": no, "date": day(d), "technician_id": tech, "machine_id": m[0], "site_id": m[1],
            "fault_class": fc, "symptom": symptom, "suspected_cause": suspected, "actions": actions,
            "root_cause": f["root_cause"] if found else "", "fix": f["fix"] if found else "",
            "parts_used": list(f["parts"]) if found else [], "parts_missing": list(missing or []), "outcome": outcome,
            "evidence": evidence or (f["evidence"] if found else ""), "wrong_diagnosis": wrong,
            "recommendation": f["recommend"] if found else "", "notes": notes}


def build_history():
    visits, jn, inc = [], 1001, 1
    for m in MACHINES:
        mid, sid, model, mtype, loc, year, fc, holdout = m
        if mid in ("M-07", "M-91") or sid == "S-09" and mid == "M-92":
            continue  # hand-written below / brand-new customer without history
        f = FAULTS[fc]
        if fc == "vrv_pcb":
            starts = [date(2026, 9, 1) + timedelta(days=rng.randint(0, 50))]   # the newer units start failing from September
        else:
            n = rng.choice([3, 4, 4, 5]) if holdout else rng.choice([2, 3, 3, 4])
            offs = sorted(rng.sample(range(0, (END - START).days - 14), n))
            starts, prev = [], -99
            for o in offs:                      # keep incidents on one machine at least 16 days apart
                if o - prev >= 16:
                    starts.append(START + timedelta(days=o)); prev = o
        for d in starts:
            tech, symptom = rng.choice(SENIOR), rng.choice(f["symptoms"])
            r = 0.5 if fc == "vrv_pcb" else rng.random()
            if fc == "ductable_leak" and r < 0.4 and d < END - timedelta(days=50):
                # a top-up that looks like a fix: cooling recovers, then the leak returns three weeks later
                act, det = f["temporary"]
                visits.append(visit(f"J-{jn}", f"I-{inc:03d}", 1, d, tech, m, fc, symptom, "low refrigerant charge",
                                    [{"action": act, "result": "worked", "detail": det + " Pressures normal at departure."}], "resolved", False,
                                    evidence="Suction pressure low; recovered after charging.", notes="Charged and left. No leak search done."))
                jn += 1; inc += 1
                d2 = d + timedelta(days=rng.randint(17, 26))
                visits.append(visit(f"J-{jn}", f"I-{inc:03d}", 1, d2, rng.choice(SENIOR), m, fc, symptom, "refrigerant leak",
                                    [{"action": f["fix"], "result": "worked", "detail": "Leak found at the flare joint; stable after 2 hours."}],
                                    "resolved", True, notes="Same unit as the top-up three weeks ago: it was never the charge."))
                jn += 1; inc += 1
                continue
            if r < 0.22:      # wrong diagnosis on a hunch, then the real fix
                susp, act, det, part = rng.choice(f["wrong"])
                visits.append(visit(f"J-{jn}", f"I-{inc:03d}", 1, d, tech, m, fc, symptom, susp,
                                    [{"action": act, "result": "failed", "detail": det}], "revisit_needed", False, wrong=True,
                                    evidence="", notes=f"Suspected {susp}; replaced on a hunch.").copy())
                visits[-1]["parts_used"] = [part]
                kind = "wrong"
            elif r < 0.40:    # right cause found, part not on the van
                visits.append(visit(f"J-{jn}", f"I-{inc:03d}", 1, d, tech, m, fc, symptom, f["root_cause"].split(";")[0].split(".")[0],
                                    [{"action": "Diagnosed the cause; replacement part not carried", "result": "partial", "detail": "Part ordered from the warehouse."}],
                                    "revisit_needed", False, missing=f["parts"][:1], evidence=f["evidence"], notes="Cause confirmed, no spare in the van."))
                kind = "shortage"
            elif fc == "vrv_pcb" or (r < 0.70 and f["failed"]):   # generic first attempt fails (for the newer units: the usual contactor swap)
                act, det = rng.choice(f["failed"])
                visits.append(visit(f"J-{jn}", f"I-{inc:03d}", 1, d, tech, m, fc, symptom, "", [{"action": act, "result": "failed", "detail": det}],
                                    "revisit_needed", False, notes="Root cause not confirmed on first visit."))
                kind = "generic"
                if fc == "vrv_pcb":   # the usual contactor swap really was done, with a real part, and it did not help
                    visits[-1]["parts_used"] = list(FAULTS["vrv_contactor"]["parts"])
            else:             # diagnosed and fixed first time
                visits.append(visit(f"J-{jn}", f"I-{inc:03d}", 1, d, tech, m, fc, symptom, f["root_cause"].split(".")[0],
                                    [{"action": f["fix"], "result": "worked", "detail": "Diagnosed on first visit; unit stable after monitoring."}],
                                    "resolved", True))
                kind = "first"
            jn += 1
            if kind != "first":
                d2 = d + timedelta(days=rng.randint(1, 4))
                visits.append(visit(f"J-{jn}", f"I-{inc:03d}", 2, d2, rng.choice(SENIOR), m, fc, symptom, f["root_cause"].split(".")[0],
                                    [{"action": f["fix"], "result": "worked", "detail": "Unit stable after 2 hours of monitoring."}], "resolved", True))
                jn += 1
            inc += 1

    # hand-written history for the demo machine M-07 (rich), including the "suspected relay board" note that was never verified
    p = FAULTS["vrv_contactor"]; m07 = next(x for x in MACHINES if x[0] == "M-07")
    hand = [
        visit("J-0901", "I-901", 1, date(2026, 3, 12), "T-01", m07, "vrv_contactor", "Not cooling; outdoor unit tripping", "contactor",
              [{"action": "Reset outdoor unit breaker", "result": "failed", "detail": "Unit restarted but tripped again within 30 minutes."}],
              "revisit_needed", False, evidence="Supply measured at 192V around 3pm.", missing=p["parts"], notes="Suspect contactor; part not in van."),
        visit("J-0902", "I-901", 2, date(2026, 3, 14), "T-01", m07, "vrv_contactor", "Not cooling; outdoor unit tripping", "contactor",
              [{"action": "Replaced compressor contactor (DK-CTR-24V)", "result": "worked", "detail": "Old contactor coil burnt, contacts pitted. Unit stable for 3 hours."}],
              "resolved", True, notes="Told Priya the voltage dips will keep killing contactors."),
        visit("J-0947", "I-947", 1, date(2026, 8, 19), "T-02", m07, "vrv_contactor", "Outdoor unit trips within minutes of start", "contactor or compressor relay board",
              [{"action": "Reset outdoor unit breaker", "result": "failed", "detail": "Tripped again in 20 minutes."},
               {"action": "Topped up refrigerant (R410A)", "result": "failed", "detail": "Pressures were already normal; no improvement."}],
              "revisit_needed", False, missing=p["parts"], notes="Did not have the contactor spare. Also suspected the compressor relay board but did not replace it. 2 hours lost on gas top-up."),
        visit("J-0949", "I-947", 2, date(2026, 8, 21), "T-02", m07, "vrv_contactor", "Outdoor unit trips within minutes of start", "contactor",
              [{"action": "Replaced compressor contactor (DK-CTR-24V)", "result": "worked", "detail": "Same failure as March: coil burnt."}],
              "resolved", True, notes="Quoted servo stabilizer (Rs 68,000); Priya to get approval."),
    ]
    visits.extend(hand)
    visits.sort(key=lambda v: (v["date"], v["job_id"]))
    for i, v in enumerate(visits):   # unique ids in date order, hand-written ones keep their ids
        pass
    return visits


# ---- alarms ----------------------------------------------------------------------------------------------------------
def reading(m, fc, units=None):
    f, r = FAULTS[fc], {}
    if f["volts"]:
        low = m[1] == "S-01"
        r["supply_v"] = rng.randint(186, 193) if (low and fc == "vrv_contactor") else rng.randint(*f["volts"])
    if m[3] == "VRV outdoor unit": r["compressor_a"] = round(rng.uniform(17, 24), 1)
    if m[3] == "Precision AC": r["return_air_c"] = round(rng.uniform(31, 35), 1)
    if m[3] == "Water-cooled chiller": r["discharge_bar"] = round(rng.uniform(21, 24), 1)
    if m[3] == "Split AC": r["water_sensor"] = "wet"
    if m[3] == "Air handling unit": r["vibration_mm_s"] = round(rng.uniform(7.5, 12), 1)
    if m[3] == "Cassette indoor unit": r["units_offline"] = units or rng.randint(1, 4)
    return r


def build_alarms(visits):
    M = {m[0]: m for m in MACHINES}
    alarms = []
    def add(ts, mid, fc, rtype, ract, result, dispatched, incident=None, note=""):
        m, f = M[mid], FAULTS[fc]
        alarms.append({"ts": ts.strftime("%Y-%m-%dT%H:%M:00"), "machine_id": mid, "site_id": m[1], "code": f["code"][0], "description": f["code"][1],
                       "severity": "critical" if m[1] in ("S-02", "S-04", "S-11") else "major", "readings": reading(m, fc),
                       "remote_type": rtype, "remote_action": ract, "remote_result": result, "dispatched": dispatched, "incident_id": incident, "note": note})
    for v in visits:   # the alarm that preceded each first visit, with the remote attempt that did not help
        if v["visit_no"] != 1 and not v["incident_id"].startswith("I-9"):
            continue
        if v["visit_no"] != 1:
            continue
        m = M[v["machine_id"]]; rt, ra, _ = FAULTS[v["fault_class"]]["remote"]
        ts = date.fromisoformat(v["date"])
        from datetime import datetime
        t = datetime(ts.year, ts.month, ts.day) + timedelta(hours=rng.randint(6, 11), minutes=rng.randint(0, 59))
        if rt is None:
            add(t, m[0], v["fault_class"], None, None, "none", True, v["incident_id"], "No remote action possible; technician dispatched.")
        else:
            add(t, m[0], v["fault_class"], rt, ra, "failed", True, v["incident_id"], "Remote action did not clear it; the alarm returned within 30 minutes.")
    from datetime import datetime
    def rts(): return datetime(2025, 11, 1) + timedelta(days=rng.randint(0, 340), hours=rng.randint(6, 21), minutes=rng.randint(0, 59))
    PLAN = [("cassette_u4", 9, 3), ("precision_fan", 6, 2), ("chiller_head_pressure", 4, 2), ("ductable_leak", 2, 3), ("ahu_bearing", 0, 3), ("split_leak", 0, 3),
            ("vrv_contactor", 0, 4), ("vrv_pcb", 0, 1)]
    for fc, ok, bad in PLAN:
        rt, ra, _ = FAULTS[fc]["remote"]
        ids = [m[0] for m in MACHINES if m[6] == fc]
        for _ in range(ok):
            add(rts(), rng.choice(ids), fc, rt, ra, "cleared", False, None, "Cleared by the remote action. No visit needed.")
        for _ in range(bad):
            add(rts(), rng.choice(ids), fc, rt, ra, "failed" if rt else "none", True, None, "Remote action failed; technician dispatched." if rt else "Technician dispatched.")
    # a reset that held for two days on the demo machine, then failed: the dispatcher must not try the same remote fix again
    add(datetime(2026, 10, 24, 9, 40), "M-07", "vrv_contactor", "reset", "Remote fault reset via controller", "failed", False, None,
        "The reset held for two days, then the unit tripped again. No visit was booked.")
    for a in alarms:   # single-unit comm glitches clear remotely; multi-unit wiring faults do not
        if a["code"] == "U4":
            a["readings"]["units_offline"] = 1 if a["remote_result"] == "cleared" else rng.randint(2, 5)
    alarms.sort(key=lambda a: a["ts"])
    for i, a in enumerate(alarms, 1): a["id"] = f"A-{i:04d}"
    return alarms


LIVE = [  # the inputs of the Agent Control Room. "truth" is what really was wrong: it is never shown to the agents.
    {"id": "LIVE-1", "ts": "2026-11-07T09:12:00", "machine_id": "M-07", "code": "E3", "description": "High-pressure / compressor protection trip", "severity": "major",
     "readings": {"supply_v": 189, "compressor_a": 22.4}, "job_id": "J-1201", "headline": "M-07 tripped on E3 at 189V supply",
     "truth": {"cause": "Compressor contactor burnt by supply voltage dips", "fix_key": "replaced compressor contactor", "parts": ["DK-CTR-24V"], "remote_works": False}},
    {"id": "LIVE-2", "ts": "2026-11-07T10:03:00", "machine_id": "M-113", "code": "U4", "description": "Indoor-outdoor communication error", "severity": "minor",
     "readings": {"units_offline": 1}, "job_id": None, "headline": "M-113 cassette lost communication",
     "truth": {"cause": "Communication glitch", "fix_key": "reset", "parts": [], "remote_works": True}},
    {"id": "LIVE-3", "ts": "2026-11-07T11:20:00", "machine_id": "M-31", "code": "HT", "description": "High return-air temperature", "severity": "major",
     "readings": {"return_air_c": 32.4, "supply_air_c": 18.1}, "job_id": "J-1204", "headline": "M-31 return air at 32.4C in Hall 2",
     "truth": {"cause": "EC fan drive fault on fan 2", "fix_key": "replaced ec fan module", "parts": ["EBM-R3G500"], "remote_works": False}},
    {"id": "LIVE-4", "ts": "2026-11-07T13:45:00", "machine_id": "M-91", "code": "L8", "description": "Compressor overcurrent", "severity": "major",
     "readings": {"supply_v": 228, "compressor_a": 23.1}, "job_id": "J-1202", "headline": "M-91 compressor overcurrent, supply normal",
     "truth": {"cause": "Inverter PCB revision C", "fix_key": "replaced inverter pcb", "parts": ["DK-PCB-A2P-D"], "remote_works": False}},
    {"id": "LIVE-5", "ts": "2026-11-07T14:30:00", "machine_id": "M-12", "code": "WL", "description": "Water leak / drain sensor", "severity": "critical",
     "readings": {"water_sensor": "wet", "indoor_coil_c": 4.1}, "job_id": "J-1203", "headline": "M-12 leaking in the ICU",
     "truth": {"cause": "Drain line blocked and laid with reverse slope", "fix_key": "flushed drain line", "parts": ["PVC drain pipe", "Drain trap"], "remote_works": False}},
    {"id": "LIVE-6", "ts": "2026-11-07T15:10:00", "machine_id": "M-21", "code": "LC", "description": "Low cooling capacity", "severity": "major",
     "readings": {}, "job_id": None, "headline": "M-21 food-court ductable not cooling",
     "truth": {"cause": "Leak at the flare joint (a top-up only holds weeks)", "fix_key": "nitrogen pressure test", "parts": ["Copper coupler", "Brazing rods", "Refrigerant R410A"], "remote_works": False}},
    {"id": "LIVE-7", "ts": "2026-11-07T16:05:00", "machine_id": "M-22", "code": "HP", "description": "Condenser high-pressure trip", "severity": "major",
     "readings": {"discharge_bar": 23.1, "cw_flow_pct": 82}, "job_id": None, "headline": "M-22 chiller tripping on high pressure",
     "truth": {"cause": "Scaled condenser tubes", "fix_key": "chemical descaling", "parts": ["Descaling chemical"], "remote_works": False}},
]


def main():
    machines = [{"id": m[0], "site_id": m[1], "model": m[2], "type": m[3], "location": m[4], "installed": m[5], "model_family": FAMILY(m[2]),
                 "fault_class": m[6], "holdout": m[7]} for m in MACHINES]
    visits = build_history()
    alarms = build_alarms(visits)
    live = []
    for sc in LIVE:
        sc = dict(sc); sc["site_id"] = next(m[1] for m in MACHINES if m[0] == sc["machine_id"]); live.append(sc)
    techs = {"LIVE-1": "T-06", "LIVE-2": "T-04", "LIVE-3": "T-06", "LIVE-4": "T-06", "LIVE-5": "T-04", "LIVE-6": "T-05", "LIVE-7": "T-02"}
    prio = {"minor": "Medium", "major": "High", "critical": "Critical"}
    reporters = {"S-01": "Priya Nair", "S-02": "Manjunath", "S-03": "Imran Pasha", "S-04": "Sanjay Menon", "S-05": "Rahul D'Souza", "S-09": "Anita George"}
    open_jobs = []
    for n, sc in enumerate(live, 1):
        sc["job_id"] = f"J-12{n:02d}"
        symptoms = {"LIVE-1": "Bay 3 not cooling. Outdoor unit tripped twice this morning.", "LIVE-4": "Outdoor unit tripping, offices warm since lunch.",
                    "LIVE-5": "Split AC at ICU nurse station dripping water onto the counter.", "LIVE-3": "Hall 2 PAC-03 high return-air temperature alarm."}
        open_jobs.append({"job_id": sc["job_id"], "date": "2026-11-07", "machine_id": sc["machine_id"], "site_id": sc["site_id"], "technician_id": techs[sc["id"]],
                          "symptom": symptoms.get(sc["id"], sc["description"] + "."), "priority": prio[sc["severity"]],
                          "reported_by": reporters.get(sc["site_id"], "Site facility desk")})
    parts = sorted({p for v in visits for p in v["parts_used"] + v["parts_missing"]})
    stock = []
    for p in parts:
        heavy = any(k in p.lower() for k in ("pcb", "compressor", "ec fan", "bearing", "transducer", "relay"))
        stock.append({"part": p, "van": 0 if "PCB" in p else rng.randint(0, 2), "warehouse": (1 if "PCB" in p else rng.randint(1, 3)) if heavy else rng.randint(3, 12),
                      "lead_time_days": 5 if "PCB" in p else (2 if heavy else 1)})
    for s in stock:
        if "DK-CTR-24V" in s["part"]: s.update({"van": 1, "warehouse": 4})
        if "DK-RLY-B2" in s["part"]: s.update({"van": 2, "warehouse": 3})
    files = {"company.json": COMPANY, "technicians.json": TECHS, "sites.json": SITES, "machines.json": machines, "job_history.json": visits,
             "open_jobs.json": open_jobs, "alarms_history.json": alarms, "alarms_live.json": live, "stock.json": stock}
    for name, data in files.items():
        (OUT / name).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    inc = {v["incident_id"] for v in visits}
    ho = [m for m in machines if m["holdout"]]
    ho_inc = {v["incident_id"] for v in visits if v["machine_id"] in {m["id"] for m in ho}}
    print(f"sites={len(SITES)} machines={len(machines)} (held out {len(ho)}) visits={len(visits)} incidents={len(inc)} (held-out {len(ho_inc)}) "
          f"alarms={len(alarms)} scenarios={len(live)} parts={len(stock)}")


if __name__ == "__main__":
    main()
