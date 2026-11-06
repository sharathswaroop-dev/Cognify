"""Reference data (machines, sites, technicians, history, alarms, stock) plus visits logged live."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import HTTPException

DATA = Path(__file__).resolve().parent / "data"


def _load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


class Store:
    """Read-only reference data + the visits logged live during the demo."""

    def __init__(self) -> None:
        self.company = _load("company.json")
        self.sites = _load("sites.json")
        self.machines = _load("machines.json")
        self.techs = _load("technicians.json")
        self.history = _load("job_history.json")
        self.open_jobs = _load("open_jobs.json")
        self.alarms = _load("alarms_history.json")      # alarm log with remote-fix outcomes (dispatcher memory)
        self.live_alarms = _load("alarms_live.json")    # scenarios the alarm feed fires during a demo
        self.stock = _load("stock.json")                # van and warehouse parts stock
        self.logged_path = DATA / "logged_visits.json"
        self.logged = json.loads(self.logged_path.read_text(encoding="utf-8")) if self.logged_path.exists() else []
        self._m = {m["id"]: m for m in self.machines}
        self._s = {s["id"]: s for s in self.sites}
        self._t = {t["id"]: t for t in self.techs}

    def machine(self, mid):
        if mid not in self._m:
            raise HTTPException(404, f"Unknown machine {mid}")
        return self._m[mid]

    def site(self, sid):
        if sid not in self._s:
            raise HTTPException(404, f"Unknown site {sid}")
        return self._s[sid]

    def tech(self, tid):
        if tid not in self._t:
            raise HTTPException(404, f"Unknown technician {tid}")
        return self._t[tid]

    def job(self, jid):
        for j in self.open_jobs:
            if j["job_id"] == jid:
                return j
        raise HTTPException(404, f"Unknown job {jid}")

    def all_visits(self):
        return sorted(self.history + self.logged, key=lambda v: v["date"])

    def alarm_log(self):
        return self.alarms

    def add_logged(self, visit):
        self.logged.append(visit)
        self.logged_path.write_text(json.dumps(self.logged, indent=1, ensure_ascii=False), encoding="utf-8")

    def clear_logged(self):
        self.logged = []
        if self.logged_path.exists():
            self.logged_path.unlink()
