"""Extend the base dataset with: alarm history, live alarm scenarios, parts stock, newer VRV units
and a model-wide drift (contactor swap stops working on units installed from 2023).

Idempotent. Run after generate_data.py:   python scripts/extend_data.py
Everything is synthetic.
"""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "backend" / "data"
rng = random.Random(7)


def load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def save(name, obj):
    (DATA / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")


machines, history = load("machines.json"), load("job_history.json")
M = {m["id"]: m for m in machines}

# ------------------------------------------------------------------ newer VRV units (installed 2023+)
NEW_MACHINES = [
    {"id": "M-92", "site_id": "S-09", "model": "Daikin VRV IV RXYQ10", "type": "VRV outdoor unit",
     "location": "Roof, east", "installed": 2023, "model_family": "Daikin VRV IV"},
    {"id": "M-93", "site_id": "S-08", "model": "Daikin VRV IV RXYQ14", "type": "VRV outdoor unit",
     "location": "Terrace, north", "installed": 2023, "model_family": "Daikin VRV IV"},
    {"id": "M-94", "site_id": "S-05", "model": "Daikin VRV IV RXYQ8", "type": "VRV outdoor unit",
     "location": "Terrace, west", "installed": 2024, "model_family": "Daikin VRV IV"},
    {"id": "M-95", "site_id": "S-07", "model": "Daikin VRV IV RXYQ12", "type": "VRV outdoor unit",
     "location": "Rooftop", "installed": 2024, "model_family": "Daikin VRV IV"},
]
for nm in NEW_MACHINES:
    if nm["id"] not in M:
        machines.append(nm)
        M[nm["id"]] = nm

# ------------------------------------------------------------------ drift: contactor swap fails on newer units
CONTACTOR_FIX = "Replaced compressor contactor and checked phase voltages."
PCB_FIX = "Replaced inverter PCB (A2P) and updated its firmware."
DRIFT = [  # incident, machine, tech, first-visit date, second-visit date, measured volts
    ("I-951", "M-92", "T-01", "2026-09-09", "2026-09-11", "228/229/227V"),
    ("I-952", "M-93", "T-02", "2026-09-23", "2026-09-25", "226/228/227V"),
    ("I-953", "M-94", "T-04", "2026-10-06", "2026-10-08", "229/230/228V"),
    ("I-954", "M-95", "T-01", "2026-10-19", "2026-10-21", "227/228/229V"),
]
have = {v["job_id"] for v in history}
n = 1100
for inc, mid, tech, d1, d2, volts in DRIFT:
    m = M[mid]
    j1, j2 = f"J-{n}", f"J-{n + 1}"
    n += 2
    if j1 in have:
        continue
    history.append({
        "job_id": j1, "incident_id": inc, "visit_no": 1, "date": d1, "technician_id": tech, "machine_id": mid,
        "site_id": m["site_id"], "symptom": "Outdoor unit trips within minutes of start",
        "actions": [{"action": CONTACTOR_FIX, "result": "failed",
                     "detail": f"Contactor swapped as per the usual fix, but the unit tripped again within 20 minutes. Supply voltage was normal ({volts})."}],
        "root_cause": "", "fix": "", "parts_used": ["Compressor contactor 24V coil (DK-CTR-24V)"],
        "outcome": "revisit_needed", "recommendation": "Unit installed " + str(m["installed"]) + ": the usual contactor fix did not hold.",
        "notes": "Newer-generation unit. Contactor looked healthy when removed."})
    history.append({
        "job_id": j2, "incident_id": inc, "visit_no": 2, "date": d2, "technician_id": tech, "machine_id": mid,
        "site_id": m["site_id"], "symptom": "Outdoor unit trips within minutes of start",
        "actions": [{"action": PCB_FIX, "result": "worked",
                     "detail": "DC bus overvoltage trips traced to the inverter PCB; stable after replacement and firmware update."}],
        "root_cause": "Inverter PCB (A2P, revision C) causes DC bus overvoltage trips on units installed 2023 onwards; supply voltage was normal.",
        "fix": PCB_FIX, "parts_used": ["Inverter PCB A2P rev D (DK-PCB-A2P-D)"],
        "outcome": "resolved", "recommendation": "On units installed from 2023, check the inverter PCB before replacing the contactor.",
        "notes": ""})
history.sort(key=lambda v: (v["date"], v["job_id"]))

# ------------------------------------------------------------------ alarm history (with remote-fix outcomes)
CODES = {  # type -> list of (code, description, remote action, readings builder)
    "VRV outdoor unit": [("E3", "High-pressure / compressor protection trip", "Remote fault reset via controller"),
                         ("L8", "Compressor overcurrent", "Remote fault reset via controller")],
    "Cassette indoor unit": [("U4", "Indoor-outdoor communication error", "Remote power-cycle of the indoor group via BMS")],
    "Split AC": [("WL", "Water leak / drain sensor", "No remote action available")],
    "Precision AC": [("HT", "High return-air temperature", "Remote setpoint and fan-speed adjustment via BMS")],
    "Water-cooled chiller": [("HP", "Condenser high-pressure trip", "Remote chiller restart via BMS")],
    "Air handling unit": [("VB", "High vibration alarm", "No remote action available")],
    "Ductable AC": [("LC", "Low cooling capacity", "Remote setpoint reset via BMS")],
}
SYMPTOM_CODE = [  # symptom keyword -> (type-specific code index) so incident alarms line up with the visit
    ("communication error", "U4"), ("error U4", "U4"), ("U4 error", "U4"),
    ("E3", "E3"), ("tripp", "E3"), ("trips", "E3"), ("not cooling", "E3"),
    ("leak", "WL"), ("Water dripping", "WL"), ("dripping", "WL"),
    ("noise", "VB"), ("vibration", "VB"), ("grinding", "VB"),
    ("High return-air", "HT"), ("airflow low", "HT"),
    ("head pressure", "HP"), ("Chilled water", "HP"), ("HP", "HP"),
    ("below 27C", "LC"),
]


def pick_code(mtype, symptom):
    options = {c[0]: c for c in CODES.get(mtype, [])}
    for kw, code in SYMPTOM_CODE:
        if kw.lower() in symptom.lower() and code in options:
            return options[code]
    return next(iter(options.values())) if options else ("GEN", "General fault", "Remote fault reset via controller")


def readings(mid, code, ts):
    m = M[mid]
    r = {}
    if m["type"] == "VRV outdoor unit":
        low = m["site_id"] == "S-01"
        r = {"supply_v": rng.randint(186, 193) if low else rng.randint(224, 231), "compressor_a": round(rng.uniform(17, 24), 1)}
    elif m["type"] == "Precision AC":
        r = {"return_air_c": round(rng.uniform(31, 35), 1), "supply_air_c": round(rng.uniform(17, 20), 1)}
    elif m["type"] == "Water-cooled chiller":
        r = {"discharge_bar": round(rng.uniform(21, 24), 1), "cw_flow_pct": rng.randint(70, 95)}
    elif m["type"] == "Split AC":
        r = {"water_sensor": "wet", "indoor_coil_c": round(rng.uniform(3, 8), 1)}
    elif m["type"] == "Air handling unit":
        r = {"vibration_mm_s": round(rng.uniform(7.5, 12), 1)}
    elif m["type"] == "Cassette indoor unit":
        r = {"units_offline": rng.randint(1, 4)}
    return r


alarms = []
seq = 1


def add_alarm(ts, mid, code, desc, remote, result, dispatched, incident=None, extra_note=""):
    global seq
    m = M[mid]
    alarms.append({
        "id": f"A-{seq:04d}", "ts": ts.strftime("%Y-%m-%dT%H:%M:00"), "machine_id": mid, "site_id": m["site_id"],
        "code": code, "description": desc, "severity": "critical" if m["site_id"] in ("S-02", "S-04") else "major",
        "readings": readings(mid, code, ts), "remote_action": remote, "remote_result": result,
        "dispatched": dispatched, "incident_id": incident, "note": extra_note})
    seq += 1


# 1) one alarm shortly before every first visit (the remote attempt did not fix it: that is why a van rolled)
for v in history:
    if v["visit_no"] != 1:
        continue
    m = M[v["machine_id"]]
    code, desc, remote = pick_code(m["type"], v["symptom"])
    ts = datetime.fromisoformat(v["date"]) + timedelta(hours=rng.randint(6, 11), minutes=rng.randint(0, 59))
    if remote.startswith("No remote"):
        add_alarm(ts, m["id"], code, desc, None, "none", True, v["incident_id"], "No remote action possible; technician dispatched.")
    else:
        add_alarm(ts, m["id"], code, desc, remote, "failed", True, v["incident_id"],
                  "Remote action did not clear the alarm; it returned within 30 minutes. Technician dispatched.")

# 2) alarms that WERE fixed remotely (no visit) or where remote fix failed; builds the dispatcher's experience
by_type = {}
for m in machines:
    by_type.setdefault(m["type"], []).append(m["id"])


def random_ts():
    return datetime(2025, 11, 1) + timedelta(days=rng.randint(0, 340), hours=rng.randint(6, 21), minutes=rng.randint(0, 59))


PLAN = [  # type, code idx, cleared remotely, failed remotely
    ("Cassette indoor unit", 0, 8, 3),
    ("Precision AC", 0, 5, 2),
    ("Water-cooled chiller", 0, 4, 1),
    ("Ductable AC", 0, 3, 1),
    ("Split AC", 0, 0, 3),
    ("VRV outdoor unit", 0, 0, 3),
    ("VRV outdoor unit", 1, 0, 2),
]
for mtype, ci, ok, bad in PLAN:
    code, desc, remote = CODES[mtype][ci]
    ids = by_type[mtype]
    for _ in range(ok):
        add_alarm(random_ts(), rng.choice(ids), code, desc, remote, "cleared", False, None,
                  "Cleared by the remote action. No visit needed.")
    for _ in range(bad):
        rem = None if remote.startswith("No remote") else remote
        add_alarm(random_ts(), rng.choice(ids), code, desc, rem, "failed" if rem else "none", True, None,
                  "Remote action failed; technician dispatched." if rem else "Technician dispatched.")
# comm errors: a single unit offline is usually a glitch a power-cycle clears; several units in one zone
# is a wiring fault that needs a technician. Make the readings say so, so memory has a real signal to learn.
SYM = {(v["incident_id"]): v["symptom"] for v in history if v["visit_no"] == 1}
for a in alarms:
    if a["code"] != "U4":
        continue
    multi = "Several" in SYM.get(a["incident_id"], "")
    if a["remote_result"] == "cleared":
        a["readings"] = {"units_offline": 1}
    elif multi:
        a["readings"] = {"units_offline": rng.randint(3, 5)}
    else:
        a["readings"] = {"units_offline": rng.randint(1, 2)}
alarms.sort(key=lambda a: a["ts"])
for i, a in enumerate(alarms, 1):
    a["id"] = f"A-{i:04d}"

# ------------------------------------------------------------------ live alarm scenarios for the demo
LIVE = [
    {"id": "LIVE-1", "ts": "2026-11-07T09:12:00", "machine_id": "M-07", "site_id": "S-01", "code": "E3",
     "description": "High-pressure / compressor protection trip", "severity": "major",
     "readings": {"supply_v": 189, "compressor_a": 22.4}, "job_id": "J-1201",
     "headline": "M-07 tripped on E3 at 189V supply"},
    {"id": "LIVE-2", "ts": "2026-11-07T10:03:00", "machine_id": "M-42", "site_id": "S-05", "code": "U4",
     "description": "Indoor-outdoor communication error", "severity": "minor",
     "readings": {"units_offline": 1}, "job_id": None,
     "headline": "M-42 cassette lost communication"},
    {"id": "LIVE-3", "ts": "2026-11-07T11:20:00", "machine_id": "M-31", "site_id": "S-04", "code": "HT",
     "description": "High return-air temperature", "severity": "major",
     "readings": {"return_air_c": 32.4, "supply_air_c": 18.1}, "job_id": "J-1204",
     "headline": "M-31 return air at 32.4C in Hall 2"},
    {"id": "LIVE-4", "ts": "2026-11-07T13:45:00", "machine_id": "M-91", "site_id": "S-09", "code": "L8",
     "description": "Compressor overcurrent", "severity": "major",
     "readings": {"supply_v": 228, "compressor_a": 23.1}, "job_id": "J-1202",
     "headline": "M-91 compressor overcurrent, supply normal"},
    {"id": "LIVE-5", "ts": "2026-11-07T14:30:00", "machine_id": "M-12", "site_id": "S-02", "code": "WL",
     "description": "Water leak / drain sensor", "severity": "critical",
     "readings": {"water_sensor": "wet", "indoor_coil_c": 4.1}, "job_id": "J-1203",
     "headline": "M-12 leaking in the ICU"},
]

# ------------------------------------------------------------------ parts stock
parts = sorted({p for v in history for p in v.get("parts_used", [])})
stock = []
for p in parts:
    heavy = any(k in p.lower() for k in ("pcb", "compressor", "ec fan module", "bearing"))
    stock.append({"part": p, "van": 0 if "PCB" in p else rng.randint(0, 2),
                  "warehouse": (1 if "PCB" in p else rng.randint(1, 3)) if heavy else rng.randint(3, 12),
                  "lead_time_days": 5 if "PCB" in p else (2 if heavy else 1)})
# the contactor is the part everyone carries; keep van stock honest and low so the demo can flag it
for s in stock:
    if "DK-CTR-24V" in s["part"]:
        s.update({"van": 1, "warehouse": 4})

save("machines.json", machines)
save("job_history.json", history)
save("alarms_history.json", alarms)
save("alarms_live.json", LIVE)
save("stock.json", stock)
print(f"machines={len(machines)} visits={len(history)} alarms={len(alarms)} live={len(LIVE)} stock={len(stock)}")
