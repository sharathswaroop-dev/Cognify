"""Reference data (machines, sites, technicians, history, alarms, stock, scenarios) plus visits logged live.

Machine ids are validated here: nothing is retained to, or recalled from, memory for a machine that does not exist."""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"


class UnknownMachine(KeyError):
    """A machine id that is not in the fleet. Raised before anything touches memory."""


class NotFound(KeyError):
    pass


def _load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


class Store:
    def __init__(self) -> None:
        self.company = _load("company.json")
        self.sites = _load("sites.json")
        self.machines = _load("machines.json")
        self.techs = _load("technicians.json")
        self.history = _load("job_history.json")
        self.open_jobs = _load("open_jobs.json")
        self.alarms = _load("alarms_history.json")
        self.scenarios = _load("alarms_live.json")      # control-room inputs; each carries a hidden "truth"
        self.stock = _load("stock.json")
        self.logged_path = DATA / "logged_visits.json"
        self.logged = json.loads(self.logged_path.read_text(encoding="utf-8")) if self.logged_path.exists() else []
        self._m = {m["id"]: m for m in self.machines}
        self._s = {s["id"]: s for s in self.sites}
        self._t = {t["id"]: t for t in self.techs}

    # ------------------------------------------------------------------ lookups
    def has_machine(self, mid) -> bool:
        return mid in self._m

    def machine(self, mid):
        if mid not in self._m:
            raise UnknownMachine(f"Unknown machine id {mid!r}")
        return self._m[mid]

    def site(self, sid):
        if sid not in self._s:
            raise NotFound(f"Unknown site {sid}")
        return self._s[sid]

    def tech(self, tid):
        if tid not in self._t:
            raise NotFound(f"Unknown technician {tid}")
        return self._t[tid]

    def job(self, jid):
        for j in self.open_jobs:
            if j["job_id"] == jid:
                return j
        raise NotFound(f"Unknown job {jid}")

    def scenario(self, sid):
        for s in self.scenarios:
            if s["id"] == sid:
                return s
        raise NotFound(f"Unknown scenario {sid}")

    # ------------------------------------------------------------------ records
    def all_visits(self):
        return sorted(self.history + self.logged, key=lambda v: (v["date"], v["job_id"]))

    def visits_before(self, as_of: str | None):
        return [v for v in self.all_visits() if as_of is None or v["date"] < as_of]

    def alarms_before(self, as_of: str | None):
        return [a for a in self.alarms if as_of is None or a["ts"][:10] < as_of]

    def holdout_ids(self) -> set[str]:
        return {m["id"] for m in self.machines if m.get("holdout")}

    def add_logged(self, visit):
        self.logged.append(visit)
        self.logged_path.write_text(json.dumps(self.logged, indent=1, ensure_ascii=False), encoding="utf-8")

    def clear_logged(self):
        self.logged = []
        if self.logged_path.exists():
            self.logged_path.unlink()
