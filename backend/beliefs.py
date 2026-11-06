"""Self-correcting memory.

Memory that only accumulates goes stale: a fix that worked many times can quietly stop working when a new hardware revision arrives, and an agent
that remembers only the old successes keeps sending technicians to repeat it. This module watches the outcome of every fix per model family over
time and notices when recent evidence contradicts an older lesson.

The rule is deliberately simple and explainable, not an LLM judgement:
  * take every worked / failed attempt of one fix on one model family, in date order (a fix that came back within 30 days counts as failed)
  * let r be the trailing run of failures. The lesson 'this fix works' is contradicted if
      - the attempts before the run were at least 75% successful over at least 4 attempts, and
      - with the Laplace-smoothed earlier success rate p = (k+1)/(n+2), the chance of r failures in a row, (1-p)^r, is below 5%
  * if every recent failure is on units installed from year Y and the earlier successes were on older units, the belief is scoped to
    units installed from Y; older units keep the original lesson
  * the belief names the fix that actually worked in those incidents.
The correction is retained to Hindsight (so recall surfaces it) and the Verifier uses it to veto a recommendation that the newer evidence contradicts.
"""
from __future__ import annotations

import hashlib
import logging
from collections import Counter, defaultdict

import evidence as ev
from evidence import attempts as _attempts, fix_key
from memory import slug

log = logging.getLogger("sitememory.beliefs")
MIN_EARLIER, MIN_RATE, MIN_RUN, ALPHA = 4, 0.75, 2, 0.05
GOOD = ("verified", "provisional")


def attempts(visits, machine_of, as_of=None):
    return _attempts(visits, machine_of, as_of)


def _years(vals: list[int]) -> str:
    lo, hi = min(vals), max(vals)
    return str(lo) if lo == hi else f"{lo}-{hi}"


def _p(earlier):
    k, n = sum(1 for a in earlier if a["result"] in GOOD), len(earlier)
    return k, n, (k + 1) / (n + 2)


def detect(att: list[dict]) -> dict | None:
    """Two ways a lesson gets contradicted: the latest attempts all fail (time drift), or every attempt on one generation of units fails
    while older units' record stays strong (cohort drift: a newer hardware revision)."""
    r = 0
    for a in reversed(att):                       # 1) the trailing run of failures
        if a["result"] in GOOD:
            break
        r += 1
    earlier, recent = att[:len(att) - r], att[len(att) - r:]
    if r >= MIN_RUN and len(earlier) >= MIN_EARLIER:
        k, n, p = _p(earlier)
        if k / n >= MIN_RATE and (1 - p) ** r < ALPHA:
            return {"earlier": earlier, "recent": recent, "k": k, "n": n, "run": r, "cohort_from": None}
    for y in sorted({a["installed"] for a in att})[1:]:   # 2) one generation of units fails, older units do not
        new, old = [a for a in att if a["installed"] >= y], [a for a in att if a["installed"] < y]
        if len(new) >= MIN_RUN and all(a["result"] not in GOOD for a in new) and len(old) >= MIN_EARLIER:
            k, n, p = _p(old)
            if k / n >= MIN_RATE and (1 - p) ** len(new) < ALPHA:
                return {"earlier": old, "recent": new, "k": k, "n": n, "run": len(new), "cohort_from": y}
    return None


def analyse(visits: list[dict], machine_of, as_of: str | None = None) -> list[dict]:
    by_inc = defaultdict(list)
    for v in visits:
        by_inc[v["incident_id"]].append(v)
    out = []
    for fam, fixes in attempts(visits, machine_of, as_of).items():
        for key, att in fixes.items():
            d = detect(att)
            if not d:
                continue
            earlier, recent, k, n, r = d["earlier"], d["recent"], d["k"], d["n"], d["run"]
            ok_years = [a["installed"] for a in earlier if a["result"] in GOOD]
            bad_years = [a["installed"] for a in recent]
            cohort_from = d["cohort_from"]
            if cohort_from is None:                  # time drift: scope to a newer cohort only if the record cleanly splits by install year
                cohort = min(bad_years)
                old_ok = [a for a in earlier if a["installed"] < cohort and a["result"] in GOOD]
                new_ok = [a for a in earlier if a["installed"] >= cohort and a["result"] in GOOD]
                cohort_from = cohort if (len(old_ok) >= 3 and not new_ok) else None
            alt, incs = Counter(), {a["incident_id"] for a in recent}
            for inc in incs:
                for v in by_inc[inc]:
                    if as_of and v["date"] >= as_of:
                        continue
                    for a in v["actions"]:
                        if a["result"] == "worked" and fix_key(a["action"]) != key:
                            alt[a["action"].rstrip(". ")] += 1
            alt_label, alt_n = (alt.most_common(1)[0] if alt else (None, 0))
            label = Counter(a["label"].rstrip(". ") for a in att).most_common(1)[0][0]
            last_ok = max(a["date"] for a in earlier if a["result"] in GOOD)
            first_bad = min(a["date"] for a in recent)
            text = (f'Belief updated: "{label}" fixed {fam} faults {k} of {n} times on units installed {_years(ok_years)} (latest {last_ok}), '
                    f'but it failed {r} of {r} times since {first_bad} on units installed {_years(bad_years)}.')
            if cohort_from:
                text += f" Treat it as unreliable on units installed from {cohort_from}; older units keep the original lesson."
            if alt_label:
                text += f' In those incidents the fix that worked was "{alt_label}" ({alt_n} of {len(incs)}).'
            out.append({"family": fam, "fix": label, "fix_key": key, "earlier": {"worked": k, "n": n, "last_worked": last_ok},
                        "recent": {"failed": r, "since": first_bad, "until": max(a["date"] for a in recent), "jobs": [a["job_id"] for a in recent]},
                        "cohort_from": cohort_from, "alternative": alt_label, "alternative_count": alt_n, "text": text,
                        "doc_id": f"belief-{slug(fam)}-{slug(key)}", "date": max(a["date"] for a in recent)})
    return out


def timeline(visits: list[dict], machine_of, family: str, as_of: str | None = None) -> list[dict]:
    """Outcome of every fix on one model family over time (what the dashboard plots)."""
    bl = {b["fix_key"]: b for b in analyse(visits, machine_of, as_of) if b["family"] == family}
    rows = []
    for key, att in attempts(visits, machine_of, as_of).get(family, {}).items():
        st = ev.fix_stats(att)
        rows.append({"fix": Counter(a["label"].rstrip(". ") for a in att).most_common(1)[0][0], "key": key, **st,
                     "attempts": [{k: a[k] for k in ("date", "result", "installed", "machine_id", "job_id", "level", "wrong_diagnosis")} for a in att],
                     "belief": bl.get(key, {}).get("text")})
    return sorted(rows, key=lambda r: -r["n"])


class BeliefEngine:
    def __init__(self, store, memory=None, state_get=None, state_set=None):
        self.store, self.memory = store, memory
        self.state_get, self.state_set = state_get or (lambda: {}), state_set or (lambda **kw: None)

    def current(self, as_of: str | None = None, visits: list[dict] | None = None) -> list[dict]:
        return analyse(visits if visits is not None else self.store.all_visits(), self.store.machine, as_of)

    def sync(self) -> list[str]:
        """Retain each correction to the shared bank once, and again whenever its text changes."""
        done, seen = [], dict(self.state_get().get("beliefs_retained", {}))
        for b in self.current():
            h = hashlib.sha1(b["text"].encode()).hexdigest()[:12]
            if seen.get(b["doc_id"]) == h or self.memory is None:
                continue
            try:
                self.memory.retain(f"BELIEF CORRECTION. {b['text']}", [f"family:{slug(b['family'])}", "kind:belief"], b["date"], b["doc_id"],
                                   {"doc_kind": "belief", "fix": b["fix"]})
            except Exception as exc:
                log.warning("could not retain belief: %s", str(exc)[:120])
                continue
            seen[b["doc_id"]] = h
            done.append(b["doc_id"])
        if done:
            self.state_set(beliefs_retained=seen)
        return done
