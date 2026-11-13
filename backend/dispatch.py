"""Dispatch: a problem is reported, ranked against every other open problem, and offered to the best technician, the way a ride-hailing app offers a ride.

What makes it Cognify and not a plain dispatch app is the experience term. "Nearest" is 38% of the score and experience 30%: how many times THIS technician has
fixed THIS kind of fault and had it stay fixed, counted from the raw visit records, and the rest is skill and availability. Every number is shown, so a manager
(or a judge) can see exactly why one technician was offered the job and another was not.

Everything here is deterministic and runs with no model. Coordinates, positions and availability are simulated for the demo (data/geo.json).
Technicians whose phone app is not connected are simulated: they accept or decline after a few seconds, so the board is alive with no phones at all.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

import evidence as ev

RINGS = (3, 8, 15, 30)               # search radius ladder in km: look close first, widen only when nobody inside the current radius takes the job
OTP_TRIES = 5                      # wrong codes allowed before the job locks and the manager is asked
WINDOW = 4                         # seconds after the first accept in which the best match among the acceptors is chosen
OFFER_TTL = 45                     # seconds a technician has to answer an offer
DEMO_SPEED = 0.05                  # one real second stands for 20 travel seconds, so a 20-minute drive takes about a minute
ONLINE_WINDOW = 20                 # a phone that polled in the last 20 s counts as a connected technician
W = {"closeness": 0.38, "experience": 0.30, "skill": 0.12, "availability": 0.20}
SEVERITY = {"urgent": 40, "high": 30, "normal": 15}
SKILLS = {"vrv": ("vrv", "vrf"), "chill": ("chiller", "ahu", "air handling", "screw"), "precision": ("precision", "vertiv", "liebert"),
          "split": ("split", "cassette"), "duct": ("ductable", "duct")}
SYMPTOMS = [
    ("Outdoor unit keeps tripping and the floor is not cooling", "urgent"), ("Water dripping from the indoor unit onto the false ceiling", "high"),
    ("Error code on the display, unit is off", "high"), ("Unit is cooling but making a loud grinding noise", "normal"),
    ("Server room temperature rising, alarm sounding", "urgent"), ("Weak airflow and the room is warm", "normal"),
    ("Communication error between indoor and outdoor units", "high"), ("Strange burning smell near the outdoor unit", "urgent"),
]


EXTRA_NAMES = ["Kiran Patil", "Anita Desai", "Vikram Shetty", "Lakshmi Narayan", "Rohan Mehta", "Divya Hegde", "Manoj Pillai", "Sneha Kulkarni", "Imran Pasha", "Pooja Reddy",
                "Naveen Gowda", "Fatima Khan", "Ganesh Bhat", "Revathi Iyer", "Sandeep Nair", "Kavya Menon", "Harish Babu", "Zoya Siddiqui", "Prakash Rao", "Meghana Shenoy",
                "Tarun Joshi", "Bhavana Murthy", "Suhas Kamath", "Nisha Varghese"]
EXTRA_SKILLS = ["VRV / VRF systems", "Chillers and AHUs", "Precision cooling", "Split and cassette units", "Ductable units", "General HVAC"]


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def _roll(*parts: object) -> float:
    """A repeatable pseudo-random number in [0, 1) so the simulated technicians behave the same way every time for the same report."""
    h = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def ring_of(km: float) -> int:
    """1 = within the first radius, ... len(RINGS) + 1 = beyond the last."""
    for i, r in enumerate(RINGS, 1):
        if km <= r:
            return i
    return len(RINGS) + 1


def ring_label(i: int) -> str:
    return f"within {RINGS[i - 1]} km" if i <= len(RINGS) else f"beyond {RINGS[-1]} km"


def machine_kind(m: dict) -> str:
    t = f"{m.get('model', '')} {m.get('type', '')}".lower()
    for kind, keys in SKILLS.items():
        if any(k in t for k in keys):
            return kind
    return "other"


def tech_kind(t: dict) -> str:
    s = t.get("speciality", "").lower()
    for kind, keys in SKILLS.items():
        if any(k in s for k in keys):
            return kind
    return "general" if "general" in s else "other"


class Dispatch:
    def __init__(self, store, path: Path, clock=time.time, watch=None):
        self.store, self.path, self.now, self.watch = store, Path(path), clock, watch
        self.lock = threading.RLock()
        geo = json.loads((Path(__file__).parent / "data" / "geo.json").read_text(encoding="utf-8"))
        self.site_geo = geo["sites"]
        self.geo_t = geo["technicians"]
        self.state = {"users": {}, "reports": [], "seq": 0, "techs": {}, "new_techs": [], "fleet_big": False}
        if self.path.exists():
            try:
                self.state.update(json.loads(self.path.read_text(encoding="utf-8")))
            except Exception:
                pass
        for t in self.state["new_techs"]:
            if t["id"] not in store._t:
                store.add_tech(t)
        for tid, g in geo["technicians"].items():
            cur = self.state["techs"].setdefault(tid, {"lat": g["lat"], "lng": g["lng"], "base_lat": g["lat"], "base_lng": g["lng"], "status": g["status"],
                                                      "busy_until": self.now() + g.get("busy_minutes", 0) * 60 if g["status"] == "busy" else 0, "last_seen": 0,
                                                      "area": g.get("area", "")})
            cur.setdefault("base_lat", g["lat"])
            cur.setdefault("base_lng", g["lng"])
        rnd = random.Random(2026)
        self.extra = []
        for i, name in enumerate(EXTRA_NAMES):
            tid = f"T-{101 + i}"
            lat, lng = 12.865 + rnd.random() * 0.175, 77.52 + rnd.random() * 0.245
            tech = {"id": tid, "name": name, "years": 1 + int(rnd.random() * 11), "joined": "2024-01-01", "speciality": EXTRA_SKILLS[i % len(EXTRA_SKILLS)], "extra": True}
            self.extra.append(tech)
            store._t[tid] = tech
            self.state["techs"].setdefault(tid, {"lat": lat, "lng": lng, "base_lat": lat, "base_lng": lng, "status": "available", "busy_until": 0, "last_seen": 0, "area": ""})
        for rep in self.state["reports"]:                 # a restart must not lose the jobs technicians have accepted
            if rep.get("job_id") and rep["status"] in ("en_route", "on_site"):
                self._make_job(rep, register_only=True)

    # ------------------------------------------------------------------ push notifications (best effort)
    push_hook = None          # set by the app: callable(key, title, body, data). key is a technician id or a reporter's user id.

    def register_push(self, key: str, token: str) -> None:
        with self.lock:
            toks = self.state.setdefault("push", {}).setdefault(key, [])
            if token in toks:
                toks.remove(token)
            toks.append(token)
            del toks[:-3]                                     # a person is on at most a few phones
            self._save()

    def unregister_push(self, key: str, token: str) -> None:
        with self.lock:
            toks = self.state.setdefault("push", {}).get(key, [])
            if token in toks:
                toks.remove(token)
                self._save()

    def push_tokens(self, key: str) -> list[str]:
        with self.lock:
            return list(self.state.setdefault("push", {}).get(key, []))

    def _push(self, key: str, title: str, body: str, data: dict | None = None) -> None:
        if self.push_hook:
            try:
                self.push_hook(key, title, body, data or {})
            except Exception:
                pass                                          # a failed notification must never break dispatch

    def _fleet(self) -> list[dict]:
        """The technicians in play: the six named ones, or the whole city (30) when the city fleet is on."""
        return list(self.store.techs) + (self.extra if self.state.get("fleet_big") else [])

    def set_fleet(self, big: bool) -> dict:
        with self.lock:
            self.state["fleet_big"] = bool(big)
            self._save()
            return {"fleet_big": self.state["fleet_big"], "size": len(self._fleet())}

    # ------------------------------------------------------------------ persistence
    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------------ people
    def register(self, name: str, role: str, site_id: str | None = None, speciality: str = "", area: str = "") -> dict:
        name = " ".join(name.split())
        if len(name) < 2:
            raise ValueError("Please enter your name.")
        if role not in ("reporter", "technician"):
            raise ValueError("Role must be reporter or technician.")
        with self.lock:
            uid = f"U-{len(self.state['users']) + 1:03d}"
            user = {"id": uid, "name": name, "role": role, "created": self.now()}
            if role == "reporter":
                if site_id:
                    self.store.site(site_id)
                user["site_id"] = site_id
            else:
                n = len(self.store.techs) + 1
                tid = f"T-{n:02d}"
                lat, lng = 12.9757 + (_roll(uid, "la") - 0.5) * 0.08, 77.6068 + (_roll(uid, "ln") - 0.5) * 0.12
                tech = {"id": tid, "name": name, "years": 1, "joined": datetime.now().date().isoformat(), "speciality": speciality or "General HVAC (new joiner)"}
                self.store.add_tech(tech)
                self.state["new_techs"].append(tech)
                self.state["techs"][tid] = {"lat": lat, "lng": lng, "base_lat": lat, "base_lng": lng, "status": "available", "busy_until": 0, "last_seen": 0, "area": area or "MG Road"}
                user["tech_id"] = tid
            self.state["users"][uid] = user
            self._save()
            return user

    def set_mode(self, tid: str, mode: str) -> dict:
        """Demo: this technician is played by the simulation (accepts, drives, enters the OTP by itself). Manual: the person with the phone decides."""
        if mode not in ("demo", "manual"):
            raise ValueError("Mode must be demo or manual.")
        with self.lock:
            st = self.state["techs"].get(tid)
            if st is None:
                raise KeyError("Unknown technician")
            st["mode"] = mode
            st["last_seen"] = self.now()
            self._save()
            return {"id": tid, "mode": mode}

    def set_duty(self, tid: str, on: bool) -> dict:
        """A technician goes online (receives offers) or offline (receives nothing), like a ride-hailing captain. Not while on a job."""
        with self.lock:
            st = self.state["techs"].get(tid)
            if st is None:
                raise KeyError("Unknown technician")
            if not on and st["status"] in ("en_route", "on_site"):
                raise ValueError("Finish your current job before going offline.")
            st["duty"] = "on" if on else "off"
            st["last_seen"] = self.now()
            waiting = 0
            if on and st["status"] == "available":
                name = self._tech(tid)["name"]
                for rep in self.state["reports"]:
                    if rep["status"] == "unassigned" and self.now() - rep["created"] < 1800:        # nobody could take it: a technician coming online gets the chance
                        rep["ranking"] = self.rank(rep["site_id"], rep["machine_id"])
                        rep["status"] = "offered"
                        self._event(rep, f"{name} came online. Offering the waiting request again.", "search")
                        self._open_wave(rep)
                waiting = sum(1 for r in self.state["reports"] if r["status"] == "offered" and any(o["tech_id"] == tid and o["result"] == "pending" for o in r["offers"]))
                if waiting:
                    self._push(tid, "You are online", f"{waiting} task{'s' if waiting != 1 else ''} waiting for you. Open the app to accept.", {"type": "online", "waiting": waiting})
            self._save()
            return {"id": tid, "duty": st["duty"], "waiting": waiting}

    def user(self, uid: str) -> dict:
        u = self.state["users"].get(uid)
        if not u:
            raise KeyError("Unknown user")
        return u

    # ------------------------------------------------------------------ the matching
    def _experience(self) -> dict:
        visits = self.store.all_visits()
        lv = ev.visit_levels(visits)
        out: dict = {}
        for v in visits:
            tid = v.get("technician_id")
            if not tid or not ev.is_fix(v):
                continue
            info = lv.get(v["job_id"])
            if not info or not ev.is_verified(info):
                continue
            m = self.store.machine(v["machine_id"])
            d = out.setdefault(tid, {"family": {}, "fault": {}, "machine": {}})
            d["family"][m["model_family"]] = d["family"].get(m["model_family"], 0) + 1
            d["fault"][m.get("fault_class", "")] = d["fault"].get(m.get("fault_class", ""), 0) + 1
            d["machine"][m["id"]] = d["machine"].get(m["id"], 0) + 1
        return out

    def rank(self, site_id: str, machine_id: str | None = None, baseline: bool = False) -> list[dict]:
        """baseline=True ranks as if everyone were at their home base, which is what the 'how it works' page shows so its example never depends on who is out on a job."""
        site, m = self.store.site(site_id), (self.store.machine(machine_id) if machine_id else None)
        here = (self.site_geo[site_id]["lat"], self.site_geo[site_id]["lng"])
        exp = self._experience()
        rows = []
        for t in self._fleet():
            st = self.state["techs"].get(t["id"])
            if not st:
                continue
            if baseline:
                g = self.geo_t.get(t["id"], {})
                lat, lng, status, wait = st["base_lat"], st["base_lng"], g.get("status", "available"), (g.get("busy_minutes", 0) if g.get("status") == "busy" else 0)
            else:
                lat, lng, status = st["lat"], st["lng"], st["status"]
                if st.get("duty") == "off" and status in ("available", "busy"):
                    status = "off_duty"                                  # offline: not notified, not asked, not counted as free
                wait = 0 if status == "available" else max(0, (st.get("busy_until", 0) - self.now()) / 60) if status == "busy" else 8
            km = _haversine((lat, lng), here)
            available = status == "available"
            eta = round(km / 22 * 60 + 6 + wait)
            e = exp.get(t["id"], {"family": {}, "fault": {}, "machine": {}})
            fam = e["family"].get(m["model_family"], 0) if m else 0
            fault = e["fault"].get(m.get("fault_class", ""), 0) if m else 0
            same = e["machine"].get(m["id"], 0) if m else 0
            k_m, k_t = (machine_kind(m) if m else "other"), tech_kind(t)
            skill = 1.0 if k_m == k_t and k_m != "other" else (0.45 if k_t == "general" else 0.2)
            comp = {"closeness": max(0.0, 1 - km / 22) ** 1.4, "experience": min(1.0, (fault + 0.4 * max(0, fam - fault) + 0.5 * same) / 5), "skill": skill,
                    "availability": 1.0 if available else (0.5 if status == "busy" and wait <= 20 else 0.15)}
            pts = {k: round(100 * W[k] * v, 1) for k, v in comp.items()}
            reasons = [f"{km:.1f} km away, ETA about {eta} min"]
            if fault:
                reasons.append(f"has fixed {fault} similar fault{'s' if fault != 1 else ''} that stayed fixed" + (f", {same} on this very unit" if same else ""))
            elif fam:
                reasons.append(f"has fixed {fam} {m['model_family']} unit{'s' if fam != 1 else ''} before")
            else:
                reasons.append("no verified fixes of this kind yet")
            if skill == 1.0:
                reasons.append(f"specialises in {t['speciality']}")
            reasons.append("available now" if available else ("off duty" if status == "off_duty" else f"busy ({status.replace('_', ' ')})"))
            rows.append({"tech_id": t["id"], "name": t["name"], "speciality": t["speciality"], "years": t["years"], "distance_km": round(km, 1), "eta_min": eta,
                         "status": status, "available": available, "scores": {k: round(v, 2) for k, v in comp.items()}, "points": pts,
                         "total": round(sum(pts.values()), 1), "ring": ring_of(km), "reasons": reasons, "experience": {"fault": fault, "family": fam, "same_machine": same}})
        return sorted(rows, key=lambda r: -r["total"])

    def queue_for(self, ranking: list[dict]) -> list[str]:
        """The order offers go out. Free technicians first, one search radius at a time (closest radius first, best score first inside it), then busy
        technicians by how soon they could get there. A radius is only widened when nobody inside the previous one took the job."""
        free = [r for r in ranking if r["available"]]
        order: list[str] = []
        for ring in range(1, len(RINGS) + 2):
            order += [r["tech_id"] for r in sorted((x for x in free if x["ring"] == ring), key=lambda x: -x["total"])]
        order += [r["tech_id"] for r in sorted((x for x in ranking if not x["available"] and x["status"] == "busy"), key=lambda x: x["eta_min"])]
        return order

    def ladder(self, ranking: list[dict]) -> list[dict]:
        """How many free technicians each search radius holds, for the board and the explainer."""
        out = []
        for i in range(1, len(RINGS) + 2):
            inside = [r for r in ranking if r["ring"] <= i and r["available"]]
            out.append({"ring": i, "label": ring_label(i), "km": RINGS[i - 1] if i <= len(RINGS) else None, "free": len(inside),
                        "new": [r["name"] for r in ranking if r["ring"] == i and r["available"]]})
        return out

    def priority(self, rep: dict) -> dict:
        """Which problem should be handled first: how bad, how critical the site, how long it has waited, how likely it is to come back."""
        site = self.store.site(rep["site_id"])
        reasons, score = [], SEVERITY.get(rep["severity"], 15)
        reasons.append(f"{rep['severity']} severity (+{score})")
        n = site["name"].lower()
        crit = 20 if any(k in n for k in ("hospital", "data center", "pharma", "diagnostic", "lab")) else (10 if any(k in n for k in ("hotel", "mall", "park", "office", "campus", "centre")) else 5)
        score += crit
        reasons.append(f"{'critical' if crit == 20 else 'business-critical' if crit == 10 else 'residential'} site (+{crit})")
        wait = max(0.0, (self.now() - rep["created"]) / 60)
        age = min(20, round(wait * 4))
        if age:
            score += age
            reasons.append(f"waiting {wait:.0f} min (+{age})")
        if rep.get("machine_id") and self.watch is not None:
            row = next((r for r in self.watch if r["machine_id"] == rep["machine_id"]), None)
            if row:
                risk = min(20, row["score"] * 2)
                score += risk
                reasons.append(f"likely to come back: {row['reasons'][0]} (+{risk})")
        return {"score": min(100, score), "reasons": reasons}

    # ------------------------------------------------------------------ reports
    def create_report(self, user_id: str, site_id: str, machine_id: str | None, symptom: str, severity: str = "normal", manual: bool = False, source: str = "web", accept_after: int | None = None, photo: str | None = None) -> dict:
        if photo and (not photo.startswith("data:image/") or len(photo) > 700_000):
            raise ValueError("The photo must be an image under about 500 KB.")
        symptom = " ".join(symptom.split())
        if len(symptom) < 6:
            raise ValueError("Tell us a little more about what is wrong.")
        severity = severity if severity in SEVERITY else "normal"
        site = self.store.site(site_id)
        if machine_id:
            if self.store.machine(machine_id)["site_id"] != site_id:
                raise ValueError("That unit is not at this site.")
        else:
            machine_id = next((x["id"] for x in self.store.machines if x["site_id"] == site_id), None)
        with self.lock:
            user = self.user(user_id)
            crowd = accept_after is not None and accept_after >= 4 and not self.state.get("fleet_big")
            if crowd:
                self.state["fleet_big"] = True                    # nobody could reject 7 or 12 times with six technicians: bring in the city fleet
            self.state["seq"] += 1
            rid = f"R-{self.state['seq']:04d}"
            ranking = self.rank(site_id, machine_id)
            queue = self.queue_for(ranking)
            rep = {"id": rid, "created": self.now(), "reporter": {"id": user["id"], "name": user["name"]}, "site_id": site_id, "site": site["name"], "area": site["area"],
                   "machine_id": machine_id, "symptom": symptom, "severity": severity, "status": "offered", "ranking": ranking, "queue": queue, "wave": 0, "decide_at": None, "manual": bool(manual), "source": source, "accept_after": accept_after, "declined_n": 0, "photo": photo or None, "otp": None, "otp_tries": 0,
                   "offers": [], "ladder": [], "assigned": None, "eta_min": None, "events": [], "job_id": None, "scenario_id": None, "travel_secs": 0, "started": None, "on_site_at": None}
            self._event(rep, f"Problem reported by {user['name']} at {site['name']}.", "report")
            if crowd:
                self._event(rep, f"This scenario needs many technicians to answer, so the city fleet ({len(self._fleet())} technicians) is in play.", "info")
            rep["priority"] = self.priority(rep)
            rep["ladder"] = self.ladder(ranking)
            for step in rep["ladder"]:
                if step["new"]:
                    self._event(rep, f"Searching {step['label']}: {len(step['new'])} free ({', '.join(step['new'])}). Ranking them by match.", "search")
                    break
                self._event(rep, f"Searching {step['label']}: nobody free. Widening the search.", "search")
            else:
                self._event(rep, "Nobody is free anywhere. Trying the busy technicians by how soon they can get there.", "search")
            self.state["reports"].append(rep)
            self._open_wave(rep)
            self._save()
            return rep

    def _event(self, rep: dict, text: str, kind: str = "info") -> None:
        rep["events"].append({"t": round(self.now(), 1), "text": text, "kind": kind})

    def _tech(self, tid: str) -> dict:
        return self.store.tech(tid)

    def _online(self, tid: str) -> bool:
        """A technician with a connected phone in Manual mode is a real person who decides. In Demo mode the phone is driven by the simulation instead."""
        st = self.state["techs"][tid]
        return st.get("mode", "manual") != "demo" and self.now() - st.get("last_seen", 0) < ONLINE_WINDOW

    def _open_wave(self, rep: dict) -> None:
        """Open the next layer: everyone free inside the nearest radius that still has anyone is notified AT ONCE. Busy technicians are the last resort."""
        offered = {o["tech_id"] for o in rep["offers"]}
        by_ring: dict[int, list[dict]] = {}
        for r in rep["ranking"]:
            if r["available"] and r["tech_id"] not in offered:
                by_ring.setdefault(r["ring"], []).append(r)
        if by_ring:
            ring = min(by_ring)
            group, free = sorted(by_ring[ring], key=lambda r: -r["total"]), True
        else:
            busy = [r for r in rep["ranking"] if not r["available"] and r["status"] == "busy" and r["tech_id"] not in offered]
            if not busy:
                rep["status"] = "unassigned"
                self._event(rep, "Nobody could take it. The service manager has been asked to assign it.", "alert")
                return
            group, free = [min(busy, key=lambda r: r["eta_min"])], False
            ring = group[0]["ring"]
        prev = rep["offers"][-1] if rep["offers"] else None
        if prev and free and ring > prev["ring"]:
            self._event(rep, f"Everyone {ring_label(prev['ring'])} said no or did not answer. Widening the search to {ring_label(ring)}.", "search")
        if not free:
            self._event(rep, "Nobody free took it. Asking the busy technician who can get there soonest.", "search")
        rep["wave"] += 1
        rep["decide_at"] = None
        rep["status"] = "offered"
        now = self.now()
        for r in group:
            rep["offers"].append({"tech_id": r["tech_id"], "wave": rep["wave"], "at": round(now, 1), "expires": round(now + OFFER_TTL, 1), "result": "pending",
                                  "ring": ring, "free": free, "total": r["total"]})
        names = ", ".join(r["name"] for r in group)
        self._event(rep, f"Layer {rep['wave']}: notifying {len(group)} technician{'s' if len(group) != 1 else ''} {ring_label(ring)} at once ({names}).", "offer")
        for r in group:
            self._push(r["tech_id"], "New job offer", f"{rep['symptom'][:70]} at {rep['site']}. Open the app to accept.", {"type": "offer", "report": rep["id"]})

    def _make_job(self, rep: dict, register_only: bool = False) -> None:
        m = self.store.machine(rep["machine_id"])
        job = {"job_id": rep["job_id"] or f"{rep['id']}", "date": datetime.now().date().isoformat(), "machine_id": m["id"], "site_id": m["site_id"],
               "technician_id": rep["assigned"], "symptom": rep["symptom"], "priority": {"urgent": "High", "high": "High", "normal": "Medium"}[rep["severity"]],
               "reported_by": rep["reporter"]["name"], "report_id": rep["id"]}
        rep["job_id"] = job["job_id"]
        if all(j["job_id"] != job["job_id"] for j in self.store.dyn_jobs):
            self.store.dyn_jobs.append(job)
        tpl = next((s for s in self.store.scenarios if self.store.machine(s["machine_id"]).get("fault_class") == m.get("fault_class")), None)
        if tpl:
            sid = f"RPT-{rep['id'][2:]}"
            rep["scenario_id"] = sid
            if all(s["id"] != sid for s in self.store.dyn_scenarios):
                self.store.dyn_scenarios.append({**tpl, "id": sid, "machine_id": m["id"], "site_id": m["site_id"], "job_id": job["job_id"],
                                                 "headline": f"{m['id']}: {rep['symptom']}"})

    # ------------------------------------------------------------------ the clock: offers expire, simulated technicians answer, travel progresses
    def tick(self) -> None:
        with self.lock:
            now = self.now()
            changed = False
            for tid, st in self.state["techs"].items():
                if st["status"] == "busy" and now >= st.get("busy_until", 0):
                    st["status"], changed = "available", True
            for rep in self.state["reports"]:
                if rep["status"] == "offered":
                    due = []
                    for off in self._wave(rep):
                        if off["result"] != "pending":
                            continue
                        delay = 3 + 7 * _roll(rep["id"], off["tech_id"], "d")
                        if not rep.get("manual") and not self._online(off["tech_id"]) and now - off["at"] >= delay:
                            due.append((off["at"] + delay, off))
                        elif now >= off["expires"]:
                            off["result"] = "timeout"
                            self._event(rep, f"{self._tech(off['tech_id'])['name']} did not answer in time.", "offer")
                            changed = True
                    for _, off in sorted(due, key=lambda x: x[0]):
                        self._auto_answer(rep, off)
                        changed = True
                    changed = self._advance(rep) or changed
                elif rep["status"] == "en_route" and not self._online(rep["assigned"]) and now - rep["started"] >= rep["travel_secs"]:
                    self._arrive(rep)
                    changed = True
                elif rep["status"] == "on_site" and not self._online(rep["assigned"]) and not rep.get("manual") and now - rep["on_site_at"] >= 4:
                    self._start(rep)                                  # a simulated customer reads out the OTP
                    changed = True
                elif rep["status"] == "working" and not self._online(rep["assigned"]) and now - rep["work_at"] >= 25:
                    self._resolve(rep, "fixed")
                    changed = True
            if changed:
                self._save()

    REASONS = ["is wrapping up another job", "is too far from their next stop", "is on a break", "is stuck in traffic", "has a part to collect first"]

    def _auto_answer(self, rep: dict, off: dict) -> None:
        """A simulated technician answers. With a plan, the first `accept_after` of them decline and the next accepts (0 = the first accepts, -1 = nobody does)."""
        plan = rep.get("accept_after")
        if plan is None:
            accept = _roll(rep["id"], off["tech_id"], "a") < (1.0 if self.state["techs"][off["tech_id"]].get("mode") == "demo" else 0.75)
        elif plan < 0:
            accept = False
        else:
            accept = rep.get("declined_n", 0) >= plan
        if accept:
            self._tentative(rep, off)
        else:
            rep["declined_n"] = rep.get("declined_n", 0) + 1
            self._refuse(rep, off, f"{self.REASONS[int(_roll(rep['id'], off['tech_id'], 'r') * len(self.REASONS))]} and declined")

    def _wave(self, rep: dict) -> list[dict]:
        return [o for o in rep["offers"] if o["wave"] == rep["wave"]]

    def _advance(self, rep: dict) -> bool:
        """Decide the layer: pick the winner once everyone has answered or the acceptance window closed; open the next layer if nobody took it."""
        wave = self._wave(rep)
        acc = [o for o in wave if o["result"] == "accepted"]
        pend = [o for o in wave if o["result"] == "pending"]
        if acc and (not pend or (rep.get("decide_at") and self.now() >= rep["decide_at"])):
            win = max(acc, key=lambda o: o["total"])
            for o in wave:
                if o is not win and o["result"] in ("accepted", "pending"):
                    o["result"] = "lost"
                    self._event(rep, f"{self._tech(o['tech_id'])['name']} was not chosen: a better match took it.", "offer")
            self._assign(rep, win, len(acc))
            return True
        if not acc and not pend and rep["status"] == "offered":
            self._open_wave(rep)
            return True
        return False

    def _tentative(self, rep: dict, off: dict) -> None:
        off["result"] = "accepted"
        off["said_yes"] = True
        if not rep.get("decide_at"):
            rep["decide_at"] = self.now() + WINDOW
        self._event(rep, f"{self._tech(off['tech_id'])['name']} accepted (match {off['total']}).", "accept")

    def _refuse(self, rep: dict, off: dict, why: str = "declined") -> None:
        off["result"] = "declined"
        self._event(rep, f"{self._tech(off['tech_id'])['name']} {why}.", "offer")

    def _assign(self, rep: dict, off: dict, n_accepted: int = 1) -> None:
        tid = off["tech_id"]
        off["result"] = "won"
        row = next((r for r in rep["ranking"] if r["tech_id"] == tid), {"eta_min": 15, "distance_km": 5})
        rep.update(assigned=tid, status="en_route", eta_min=row["eta_min"], started=self.now(), travel_secs=min(50, max(12, row["eta_min"] * 3.0)), decide_at=None)
        st = self.state["techs"][tid]
        st["status"], st["target"] = "en_route", self.site_geo[rep["site_id"]]
        st["from"] = {"lat": st["lat"], "lng": st["lng"]}
        rep["otp"] = f"{secrets.randbelow(9000) + 1000}"
        rep["otp_tries"] = 0
        why = f" Best match of the {n_accepted} who accepted." if n_accepted > 1 else ""
        self._event(rep, f"{self._tech(tid)['name']} gets the job and is on the way (ETA {row['eta_min']} min).{why}", "accept")
        rep["confirmed_at"] = self.now()
        rep["confirmed_via"] = "phone" if self._online(tid) else ("demo" if st.get("mode") == "demo" else "simulated")
        via = {"phone": "from a connected phone", "demo": "by the demo simulation", "simulated": "by the simulated technician"}[rep["confirmed_via"]]
        self._event(rep, f"CONFIRMED: {self._tech(tid)['name']} accepted {via}. The reporter has been told.", "accept")
        self._push(rep["reporter"]["id"], "Technician confirmed", f"{self._tech(tid)['name']} accepted and is on the way. ETA {row['eta_min']} min.", {"type": "confirmed", "report": rep["id"]})
        self._push(tid, "You got the job", f"{rep['symptom'][:70]} at {rep['site']}. Head there now.", {"type": "assigned", "report": rep["id"]})
        self._make_job(rep)

    def _arrive(self, rep: dict) -> None:
        rep["status"], rep["on_site_at"] = "on_site", self.now()
        st = self.state["techs"][rep["assigned"]]
        st.update(lat=self.site_geo[rep["site_id"]]["lat"], lng=self.site_geo[rep["site_id"]]["lng"], status="on_site")
        self._event(rep, f"{self._tech(rep['assigned'])['name']} arrived at the site.", "arrive")
        self._push(rep["reporter"]["id"], "Technician arrived", "Open the app and give them your OTP so the work can start.", {"type": "arrived", "report": rep["id"]})

    def _start(self, rep: dict, by: str = "the customer") -> None:
        rep["status"], rep["work_at"] = "working", self.now()
        self._event(rep, f"OTP verified: {self._tech(rep['assigned'])['name']} started the work.", "start")

    def start_work(self, rid: str, tid: str, otp: str, demo: bool = False) -> dict:
        """The customer gives the technician a one-time code when they arrive. Entering it starts the work and proves who is solving the problem."""
        with self.lock:
            rep = self.get(rid)
            if rep["assigned"] != tid:
                raise ValueError("This job is not assigned to you.")
            if rep["status"] != "on_site":
                raise ValueError("Arrive at the site first, then ask the customer for the OTP." if rep["status"] == "en_route" else "The work has already started.")
            if rep["otp_tries"] >= OTP_TRIES:
                raise ValueError("Too many wrong codes. The service manager has been told.")
            if str(otp).strip() != rep["otp"]:
                rep["otp_tries"] += 1
                left = OTP_TRIES - rep["otp_tries"]
                self._event(rep, f"A wrong OTP was entered ({left} tries left).", "alert")
                self._save()
                raise ValueError(f"That code is not right. {left} {'try' if left == 1 else 'tries'} left.")
            if not demo:
                self.state["techs"][tid]["last_seen"] = self.now()
            self._start(rep)
            self._save()
            return rep

    def _resolve(self, rep: dict, how: str = "fixed") -> None:
        rep["status"] = "resolved"
        rep["outcome"] = "done" if how == "fixed" else "not_done"
        rep["resolved_at"] = self.now()
        st = self.state["techs"][rep["assigned"]]
        st.update(lat=self.site_geo[rep["site_id"]]["lat"], lng=self.site_geo[rep["site_id"]]["lng"], status="available")
        st.pop("target", None)
        st.pop("from", None)
        self._event(rep, f"{self._tech(rep['assigned'])['name']} marked the problem {how}.", "resolved")
        done = rep.get("outcome") == "done"
        self._push(rep["reporter"]["id"], "Work done" if done else "Not done, revisit needed", f"{rep['symptom'][:70]}: {'fixed.' if done else 'a revisit is needed.'}", {"type": "resolved", "report": rep["id"]})

    # ------------------------------------------------------------------ what the apps and pages call
    def respond(self, rid: str, tid: str, action: str, demo: bool = False) -> dict:
        """demo=True is the dispatch page's manual mode: the presenter answers on behalf of a technician without a phone."""
        with self.lock:
            rep = self.get(rid)
            if action not in ("accept", "decline"):
                raise ValueError("Unknown action")
            off = next((o for o in self._wave(rep) if o["tech_id"] == tid and o["result"] == "pending"), None)
            if off is None or rep["status"] != "offered":
                raise ValueError("That offer is no longer open.")
            if action == "accept" and any(r["assigned"] == tid and r["status"] in ("en_route", "on_site", "working") for r in self.state["reports"]):
                raise ValueError("You are already on another job. Finish it first.")
            if not demo:
                self.state["techs"][tid]["last_seen"] = self.now()
            if action == "accept":
                self._tentative(rep, off)
            else:
                self._refuse(rep, off, "declined")
            self._advance(rep)
            self._save()
            return rep

    def set_status(self, rid: str, tid: str, status: str, done: bool = True) -> dict:
        with self.lock:
            rep = self.get(rid)
            if rep["assigned"] != tid:
                raise ValueError("This job is not assigned to you.")
            self.state["techs"][tid]["last_seen"] = self.now()
            if status == "on_site" and rep["status"] == "en_route":
                self._arrive(rep)
            elif status == "resolved" and rep["status"] == "working":
                self._resolve(rep, "fixed" if done else "not fixed, a revisit is needed")
            elif status == "resolved":
                raise ValueError("Start the work with the customer's OTP before closing the job.")
            else:
                raise ValueError("That update does not fit where the job is.")
            self._save()
            return rep

    def on_visit_logged(self, job_id: str, fixed: bool) -> None:
        """The technician logged the visit in the app: the report closes, and the job goes into the shared memory like any other."""
        with self.lock:
            rep = next((r for r in self.state["reports"] if r.get("job_id") == job_id), None)
            if rep and rep["status"] == "working":
                self._resolve(rep, "fixed" if fixed else "not fixed, a revisit is needed")
                self._save()

    def get(self, rid: str) -> dict:
        rep = next((r for r in self.state["reports"] if r["id"] == rid), None)
        if not rep:
            raise KeyError("Unknown report")
        return rep

    def view(self, rep: dict, viewer: str | None = None) -> dict:
        """viewer is a user id. Only the person who reported the problem is shown the OTP (and the presenter, in the manual demo mode)."""
        self.tick()
        a = rep["assigned"]
        prog = 0.0
        if rep["status"] == "en_route" and rep["travel_secs"]:
            prog = min(1.0, (self.now() - rep["started"]) / rep["travel_secs"])
        elif rep["status"] in ("on_site", "working", "resolved"):
            prog = 1.0
        out = {k: rep[k] for k in ("id", "site_id", "site", "area", "machine_id", "symptom", "severity", "status", "events", "job_id", "scenario_id", "eta_min", "reporter")}
        out["created"] = rep["created"]
        out["manual"] = bool(rep.get("manual"))
        out["source"] = rep.get("source", "web")
        out["photo"] = rep.get("photo")
        out["otp_verified"] = rep["status"] in ("working", "resolved")
        out["otp"] = rep.get("otp") if (viewer and rep["status"] in ("en_route", "on_site") and (viewer == rep["reporter"]["id"] or (viewer == "demo" and rep.get("manual")))) else None
        out["priority"] = self.priority(rep)
        out["assigned"] = ({"id": a, "name": self._tech(a)["name"], "speciality": self._tech(a)["speciality"], "phone": self._online(a), "mode": self.state["techs"][a].get("mode", "manual")} if a else None)
        out["confirmed"] = bool(rep.get("confirmed_at"))
        out["confirmed_via"] = rep.get("confirmed_via")
        out["outcome"] = rep.get("outcome")
        out["progress"] = round(prog, 2)
        out["ranking"] = rep["ranking"][:4]
        out["ladder"] = rep.get("ladder", [])
        now = self.now()
        wave = self._wave(rep)
        cur = wave[0] if wave else None
        out["current_ring"] = cur["ring"] if cur else None
        out["wave"] = rep["wave"]
        out["queue"] = [{"tech_id": t, "name": self._tech(t)["name"], "state": next((o["result"] for o in rep["offers"] if o["tech_id"] == t), "waiting")} for t in rep["queue"]]
        pend = [o for o in wave if o["result"] == "pending"]
        out["offer"] = ({"count": len(pend), "name": ", ".join(self._tech(o["tech_id"])["name"] for o in pend), "ring_km": RINGS[cur["ring"] - 1] if cur["ring"] <= len(RINGS) else None,
                         "expires_in": max(0, round(min(o["expires"] for o in pend) - now))} if pend and rep["status"] == "offered" else None)
        out["offers"] = [{"tech_id": o["tech_id"], "tech": self._tech(o["tech_id"])["name"], "wave": o["wave"], "ring": o["ring"], "free": o["free"], "result": o["result"], "total": o["total"],
                          "left": max(0, round(o["expires"] - now)) if o["result"] == "pending" else 0} for o in rep["offers"]]
        layers = []
        first = min((o["ring"] for o in rep["offers"]), default=None)
        for step in rep.get("ladder", []):
            r = step["ring"]
            offs = [o for o in rep["offers"] if o["ring"] == r and o["free"]]
            if not offs:
                state = "skipped" if first and r < first else "idle"
            elif any(o["result"] == "won" for o in offs):
                state = "won"
            elif rep["status"] == "offered" and cur and cur["ring"] == r:
                state = "active"
            else:
                state = "failed"
            layers.append({**step, "state": state})
        out["layers"] = layers
        offs = rep["offers"]
        out["counts"] = {"notified": len(offs), "declined": sum(1 for o in offs if o["result"] == "declined"), "no_answer": sum(1 for o in offs if o["result"] == "timeout"),
                         "accepted": sum(1 for o in offs if o.get("said_yes")), "waiting": sum(1 for o in offs if o["result"] == "pending")}
        out["waves"] = [{"wave": w, "ring": next(o["ring"] for o in offs if o["wave"] == w), "notified": sum(1 for o in offs if o["wave"] == w),
                         "declined": sum(1 for o in offs if o["wave"] == w and o["result"] == "declined"), "no_answer": sum(1 for o in offs if o["wave"] == w and o["result"] == "timeout"),
                         "accepted": sum(1 for o in offs if o["wave"] == w and o.get("said_yes"))} for w in sorted({o["wave"] for o in offs})]
        out["accept_after"] = rep.get("accept_after")
        m = self.store.machine(rep["machine_id"]) if rep["machine_id"] else None
        out["machine"] = {"id": m["id"], "model": m["model"], "location": m["location"]} if m else None
        return out

    def board(self, viewer: str | None = None) -> list[dict]:
        self.tick()
        rows = [self.view(r, viewer) for r in self.state["reports"]]
        for row in rows:                                   # the board is polled every second: send a flag, not the picture (GET /api/reports/{id} has it)
            row["has_photo"] = bool(row.pop("photo", None))
        return sorted(rows, key=lambda r: (r["status"] == "resolved", -r["priority"]["score"], r["created"]))

    def inbox(self, tid: str) -> dict:
        """What a technician's phone shows: an offer waiting for an answer, or the job they are on."""
        with self.lock:
            st = self.state["techs"].get(tid)
            if st is None:
                raise KeyError("Unknown technician")
            st["last_seen"] = self.now()
        self.tick()
        offer = active = None
        for rep in self.state["reports"]:
            o = next((x for x in rep["offers"] if x["tech_id"] == tid and x["result"] == "pending"), None)
            if o and rep["status"] == "offered":
                v = self.view(rep)
                row = next((r for r in rep["ranking"] if r["tech_id"] == tid), None)
                offer = {**v, "why": (row or {}).get("reasons", []), "distance_km": (row or {}).get("distance_km"), "eta_for_you": (row or {}).get("eta_min"),
                         "expires_in": max(0, round(o["expires"] - self.now()))}
            elif rep["assigned"] == tid and rep["status"] in ("en_route", "on_site", "working"):
                active = self.view(rep)
        return {"technician": {"id": tid, "status": st["status"], "duty": st.get("duty", "on"), "mode": st.get("mode", "manual")}, "offer": offer, "active": active}

    def positions(self) -> dict:
        self.tick()
        now = self.now()
        techs = []
        for t in self._fleet():
            st = self.state["techs"].get(t["id"])
            if not st:
                continue
            lat, lng = st["lat"], st["lng"]
            rep = next((r for r in self.state["reports"] if r["assigned"] == t["id"] and r["status"] == "en_route"), None)
            if rep and st.get("from"):
                p = min(1.0, (now - rep["started"]) / max(1, rep["travel_secs"]))
                lat, lng = st["from"]["lat"] + (st["target"]["lat"] - st["from"]["lat"]) * p, st["from"]["lng"] + (st["target"]["lng"] - st["from"]["lng"]) * p
            techs.append({"id": t["id"], "name": t["name"], "status": "off_duty" if (st.get("duty") == "off" and st["status"] in ("available", "busy")) else st["status"], "lat": lat, "lng": lng, "online": self._online(t["id"]), "mode": st.get("mode", "manual"),
                          "report": rep["id"] if rep else None})
        sites = [{"id": s["id"], "name": s["name"], "area": s["area"], **self.site_geo[s["id"]],
                  "open": sum(1 for r in self.state["reports"] if r["site_id"] == s["id"] and r["status"] != "resolved")} for s in self.store.sites]
        return {"sites": sites, "technicians": techs, "fleet_big": bool(self.state.get("fleet_big"))}

    def typical(self, m: dict) -> str:
        """What this kind of unit usually reports, taken from the sample job of the same fault type, so a demo report and the agents' briefing agree."""
        tpl = next((x for x in self.store.scenarios if self.store.machine(x["machine_id"]).get("fault_class") == m.get("fault_class")), None)
        job = next((j for j in self.store.open_jobs if tpl and j["job_id"] == tpl.get("job_id")), None)
        return (job or {}).get("symptom") or (tpl or {}).get("description") or ""

    def meta(self) -> dict:
        return {"sites": [{"id": s["id"], "name": s["name"], "area": s["area"],
                           "machines": [{"id": m["id"], "model": m["model"], "location": m["location"], "typical": self.typical(m)} for m in self.store.machines if m["site_id"] == s["id"]]}
                          for s in self.store.sites],
                "technicians": [{"id": t["id"], "name": t["name"], "speciality": t["speciality"], "years": t["years"]} for t in self.store.techs],
                "severities": list(SEVERITY), "weights": W}

    def explain(self, site_id: str, machine_id: str | None, severity: str = "high") -> dict:
        """The whole calculation for one imaginary problem, with every number, so the 'how it works' page can show it and let people change the inputs."""
        site = self.store.site(site_id)
        rep = {"site_id": site_id, "machine_id": machine_id, "severity": severity if severity in SEVERITY else "high", "created": self.now() - 6 * 60}
        return {"site": {"id": site_id, "name": site["name"], "area": site["area"]}, "machine": (self.store.machine(machine_id) if machine_id else None),
                "weights": W, "ranking": self.rank(site_id, machine_id, baseline=True), "priority": self.priority(rep),
                "ttl": OFFER_TTL, "rings": list(RINGS), "ladder": self.ladder(self.rank(site_id, machine_id, baseline=True)), "queue": [{"tech_id": t, "name": self._tech(t)["name"]} for t in self.queue_for(self.rank(site_id, machine_id, baseline=True))], "formula": "score = 100 x (0.38 closeness + 0.30 experience + 0.12 skill + 0.20 availability)"}

    def demo_report(self, manual: bool = False, source: str = "demo", accept_after: int | None = None) -> dict:
        user = next((u for u in self.state["users"].values() if u["role"] == "reporter"), None) or self.register("Demo reporter", "reporter")
        site = self.store.sites[int(self.now() * 7) % len(self.store.sites)]
        machines = [m for m in self.store.machines if m["site_id"] == site["id"]]
        m = random.choice(machines) if machines else None
        text, sev = random.choice(SYMPTOMS)
        if m and self.typical(m):
            text = self.typical(m)
        return self.create_report(user["id"], site["id"], m["id"] if m else None, text, sev, manual, source, accept_after)
