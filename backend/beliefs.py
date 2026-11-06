"""Self-correcting memory.

Memory that only ever accumulates goes stale: a fix that worked nine times can quietly stop working when a new
hardware revision arrives, and an agent that remembers only the old successes keeps sending technicians to
repeat it. This module tracks the outcome of every fix per model family over time and notices when recent
evidence contradicts an older lesson.

Rule (deliberately simple and explainable, not an LLM judgement):
  * Take every worked/failed attempt of one fix on one model family, in date order.
  * Let r be the trailing run of failures. The lesson 'this fix works' is contradicted if
      - the attempts before the run were at least 75% successful over at least 4 attempts, and
      - with the Laplace-smoothed earlier success rate p = (k+1)/(n+2), the chance of r failures in a row,
        (1-p)^r, is below 5%.
  * If every recent failure is on units installed from year Y and the earlier successes were all on older units,
    the belief is scoped to units installed from Y: older units keep the original lesson.
  * The belief names the fix that actually worked in those incidents.
The correction is retained to Hindsight (so recall surfaces it) and injected into briefings and diagnoses.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter, defaultdict

from memory import slug

log = logging.getLogger("sitememory.beliefs")
MIN_EARLIER, MIN_RATE, MIN_RUN, ALPHA = 4, 0.75, 2, 0.05


def fix_key(action: str) -> str:
    """Group wordings of the same fix: 'Replaced compressor contactor and checked...' ~ 'Replaced compressor contactor (DK-CTR-24V)'."""
    return " ".join(re.findall(r"[a-z]+", action.lower())[:3])


def _years(vals: list[int]) -> str:
    lo, hi = min(vals), max(vals)
    return str(lo) if lo == hi else f"{lo}-{hi}"


def _label(actions: list[str]) -> str:
    return Counter(a.rstrip(". ") for a in actions).most_common(1)[0][0]


def attempts(visits: list[dict], machine_of, as_of: str | None = None) -> dict:
    """{family: {fix_key: [attempt,...]}} for worked/failed actions dated before as_of, in date order."""
    out: dict = defaultdict(lambda: defaultdict(list))
    for v in sorted(visits, key=lambda x: (x["date"], x.get("visit_no", 1), x["job_id"])):
        if as_of and v["date"] >= as_of:
            continue
        m = machine_of(v["machine_id"])
        for a in v.get("actions", []):
            if a["result"] in ("worked", "failed"):
                out[m["model_family"]][fix_key(a["action"])].append(
                    {"date": v["date"], "result": a["result"], "installed": m["installed"], "machine_id": m["id"],
                     "job_id": v["job_id"], "incident_id": v["incident_id"], "label": a["action"]})
    return out


def detect(att: list[dict]) -> dict | None:
    r = 0
    for a in reversed(att):
        if a["result"] != "failed":
            break
        r += 1
    earlier, recent = att[:len(att) - r], att[len(att) - r:]
    if r < MIN_RUN or len(earlier) < MIN_EARLIER:
        return None
    k, n = sum(1 for a in earlier if a["result"] == "worked"), len(earlier)
    if k / n < MIN_RATE or (1 - (k + 1) / (n + 2)) ** r >= ALPHA:
        return None
    return {"earlier": earlier, "recent": recent, "k": k, "n": n, "run": r}


def analyse(visits: list[dict], machine_of, as_of: str | None = None) -> list[dict]:
    by_inc = defaultdict(list)
    for v in visits:
        by_inc[v["incident_id"]].append(v)
    beliefs = []
    for fam, fixes in attempts(visits, machine_of, as_of).items():
        for key, att in fixes.items():
            d = detect(att)
            if not d:
                continue
            earlier, recent, k, n, r = d["earlier"], d["recent"], d["k"], d["n"], d["run"]
            ok_years = [a["installed"] for a in earlier if a["result"] == "worked"]
            bad_years = [a["installed"] for a in recent]
            cohort = min(bad_years)
            old_ok = [a for a in earlier if a["installed"] < cohort and a["result"] == "worked"]
            new_ok = [a for a in earlier if a["installed"] >= cohort and a["result"] == "worked"]
            cohort_from = cohort if (len(old_ok) >= 3 and not new_ok) else None
            # what really fixed the recent incidents (a different fix, later in the same incident)
            alt = Counter()
            for inc in {a["incident_id"] for a in recent}:
                for v in by_inc[inc]:
                    if as_of and v["date"] >= as_of:
                        continue
                    for a in v["actions"]:
                        if a["result"] == "worked" and fix_key(a["action"]) != key:
                            alt[a["action"].rstrip(". ")] += 1
            alt_label, alt_n = (alt.most_common(1)[0] if alt else (None, 0))
            label = _label([a["label"] for a in att])
            last_ok = max(a["date"] for a in earlier if a["result"] == "worked")
            text = (f'Belief updated: "{label}" fixed {fam} faults {k} of {n} times on units installed {_years(ok_years)} '
                    f'(latest {last_ok}), but it failed {r} of {r} times since {recent[0]["date"]} on units installed {_years(bad_years)}.')
            if cohort_from:
                text += f" Treat it as unreliable on units installed from {cohort_from}; older units keep the original lesson."
            if alt_label:
                text += f' In those incidents the fix that worked was "{alt_label}" ({alt_n} of {len({a["incident_id"] for a in recent})}).'
            beliefs.append({"family": fam, "fix": label, "fix_key": key, "earlier": {"worked": k, "n": n, "last_worked": last_ok},
                            "recent": {"failed": r, "since": recent[0]["date"], "until": recent[-1]["date"]},
                            "cohort_from": cohort_from, "alternative": alt_label, "alternative_count": alt_n, "text": text,
                            "doc_id": f"belief-{slug(fam)}-{slug(key)}", "date": recent[-1]["date"]})
    return beliefs


def timeline(visits: list[dict], machine_of, family: str) -> list[dict]:
    """Outcome of every fix on one model family over time (what the dashboard plots)."""
    beliefs = {b["fix_key"]: b for b in analyse(visits, machine_of) if b["family"] == family}
    rows = []
    for key, att in attempts(visits, machine_of).get(family, {}).items():
        rows.append({"fix": _label([a["label"] for a in att]), "key": key, "worked": sum(a["result"] == "worked" for a in att),
                     "failed": sum(a["result"] == "failed" for a in att),
                     "attempts": [{k: a[k] for k in ("date", "result", "installed", "machine_id", "job_id")} for a in att],
                     "belief": beliefs.get(key, {}).get("text")})
    return sorted(rows, key=lambda r: -(r["worked"] + r["failed"]))


class BeliefEngine:
    def __init__(self, store, memories: dict | None = None, state_get=None, state_set=None):
        self.store, self.memories = store, memories or {}
        self.state_get, self.state_set = state_get or (lambda: {}), state_set or (lambda **kw: None)

    def _machine(self, mid):
        return self.store.machine(mid)

    def current(self, as_of: str | None = None, visits: list[dict] | None = None) -> list[dict]:
        return analyse(visits if visits is not None else self.store.all_visits(), self._machine, as_of)

    def for_machine(self, machine: dict, as_of: str | None = None, visits: list[dict] | None = None) -> tuple[str, list[dict]]:
        """(prompt text, belief updates that apply to this unit). Plugged into Agent.briefing and the mesh."""
        mine = [b for b in self.current(as_of, visits) if b["family"] == machine["model_family"]]
        text, updates = [], []
        for b in mine:
            if b["cohort_from"] is None or machine["installed"] >= b["cohort_from"]:
                updates.append(b)
                text.append(f"CORRECTED LESSON (overrides older memories that disagree; follow it for this unit, installed {machine['installed']}):\n{b['text']}")
            else:
                text.append(f"NOTE: a correction exists for {machine['model_family']} units installed from {b['cohort_from']} "
                            f"(\"{b['fix']}\" stopped working there), but THIS unit is older (installed {machine['installed']}), "
                            f"so the original lesson still holds here.")
        return "\n\n".join(text), updates

    def sync(self) -> list[str]:
        """Retain each correction to Hindsight (field + diagnostician banks) once, and again whenever its text changes."""
        done = []
        seen = dict(self.state_get().get("beliefs_retained", {}))
        for b in self.current():
            h = hashlib.sha1(b["text"].encode()).hexdigest()[:12]
            if seen.get(b["doc_id"]) == h:
                continue
            for role in ("field", "diagnostician"):
                mem = self.memories.get(role)
                if mem is None:
                    continue
                try:
                    mem.retain(f"BELIEF CORRECTION. {b['text']}", [f"family:{slug(b['family'])}", "kind:belief"], b["date"], b["doc_id"],
                               {"doc_kind": "belief", "fix": b["fix"]})
                except Exception as exc:
                    log.warning("could not retain belief to %s: %s", role, str(exc)[:120])
                    break
            else:
                seen[b["doc_id"]] = h
                done.append(b["doc_id"])
        if done:
            self.state_set(beliefs_retained=seen)
        return done
