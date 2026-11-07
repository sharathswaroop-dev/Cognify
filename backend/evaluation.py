"""Leak-proof replay evaluation.

Walk the service history. For each incident, build the plan (diagnosis + parts) four ways, using ONLY records dated strictly before the incident:
    none                 no memory at all
    basic                basic keyword search (BM25) over earlier records
    basic_verified       the same proposals, then the Verifier vetoes and the agents revise
    hindsight(_verified) the same on a Hindsight bank, when Hindsight is available
and score each plan against what really happened, deterministically (no LLM judge):
    fix     the plan's top repair is the repair that really fixed it (a fix that came back within 30 days is not 'the fix')
    parts   the van would have carried every part the real fix needed
    ftf     predicted first-time fix: fix and parts
    warn    the plan did not recommend an attempt that really failed

Tuning uses the training machines only (the Verifier's one threshold). The final score is on held-out machines the tuning never saw.
A guard raises if any record dated on or after the incident is in the memory the plan was built from."""
from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import evidence as ev
import records
from agents import Case, Verifier
from evidence import wilson
from memory import LocalMemory
from plan import STUB_DISPATCH, build_plan
from simulate import _tok, plan_hits
from traced import NullMemory, TracedMemory

log = logging.getLogger("sitememory.eval")


class Progress:
    def __init__(self):
        self.lock = threading.Lock()
        self.state, self.done, self.total, self.message, self.started = "idle", 0, 0, "", None

    def set(self, **kw):
        with self.lock:
            self.__dict__.update(kw)

    def public(self) -> dict:
        return {"state": self.state, "done": self.done, "total": self.total, "message": self.message, "started": self.started}


PROGRESS = Progress()


class CountingLLM:
    """Counts calls that came back empty, so an outage is reported as an outage and never scored as a wrong answer."""

    def __init__(self, llm):
        self.llm, self.fail, self.calls = llm, 0, 0
        self.model = getattr(llm, "model", "?")
        self.available = getattr(llm, "available", True)

    def json_chat(self, *a, **k):
        r = self.llm.json_chat(*a, **k)
        self.calls += 1
        self.fail += r is None
        return r


def rate(vals) -> dict:
    v = [x for x in vals if x is not None]
    k = sum(1 for x in v if x)
    lo, hi = wilson(k, len(v))
    return {"k": k, "n": len(v), "rate": round(k / len(v), 3) if v else None, "ci": [lo, hi]}


def truth_for(inc_visits: list[dict], all_levels: dict, by_job: dict) -> dict:
    """What really fixed it. A fix that came back within 30 days is not the fix: follow the chain of
    returns until a repair that held (or, failing that, the last repair that worked)."""
    failed, fix, parts = [], "", []
    for v in sorted(inc_visits, key=lambda x: x["visit_no"]):
        for a in v["actions"]:
            if a["result"] == "failed":
                failed.append(a["action"])
    by_inc: dict[str, list[dict]] = {}
    for x in by_job.values():
        by_inc.setdefault(x["incident_id"], []).append(x)

    def worked(v):
        return next((a for a in v["actions"] if a["result"] == "worked"), None)

    cur, seen, last = next((v for v in sorted(inc_visits, key=lambda x: x["visit_no"]) if ev.is_fix(v)), None), set(), None
    while cur is not None and cur["job_id"] not in seen:
        seen.add(cur["job_id"])
        info, w = all_levels.get(cur["job_id"], {}), worked(cur)
        if w:
            last = (w, cur)
        if not info.get("recurred"):
            if w:
                fix, parts = w["action"], list(cur.get("parts_used") or [])
            break
        if w:
            failed.append(w["action"])
        nxt = by_job.get(info.get("recurrence_job"))
        if nxt is None:
            break
        chain = sorted(by_inc.get(nxt["incident_id"], [nxt]), key=lambda x: x["visit_no"])
        cur = next((x for x in chain if x["job_id"] == nxt["job_id"] or ev.is_fix(x)), nxt)
        if worked(cur) is None and cur is nxt:
            cur = next((x for x in chain if x["visit_no"] > nxt["visit_no"] and ev.is_fix(x)), None)
    if not fix:
        w, v = next(((worked(x), x) for x in sorted(inc_visits, key=lambda x: x["visit_no"], reverse=True) if worked(x)), (None, None))
        if last:
            w, v = last
        if w:
            fix, parts = w["action"], list(v.get("parts_used") or [])
    return {"fix_key": fix, "parts": parts, "failed": failed, "first_time": len(inc_visits) == 1 and ev.is_fix(inc_visits[0]) and not all_levels.get(inc_visits[0]["job_id"], {}).get("recurred")}


def score(final: dict, truth: dict) -> dict:
    top = final["diagnosis"]["causes"][0]
    unknown = top["fix"].lower().startswith(("escalate", "run the standard", "perform", "check"))
    hits = plan_hits({"diagnosis": final["diagnosis"], "parts": final["parts"]}, {"fix_key": truth["fix_key"], "parts": truth["parts"]})
    fix = bool(hits["fix_hit"] and not unknown)
    parts = (hits["parts_hit"] if truth["parts"] else None)
    failed_keys = [_tok(f) for f in truth["failed"]]
    warn = None
    if truth["failed"]:
        tt = _tok(top["fix"])
        warn = not any(tt and ft and len(tt & ft) / len(ft) >= 0.6 for ft in failed_keys)
    return {"fix": fix, "parts": parts, "ftf": bool(fix and parts is not False), "warn": warn, "top": top["fix"], "missing": hits["missing_parts"]}


class Replay:
    """The memory as it stood on a given date: records are added in date order and nothing dated on or after the incident is ever present."""

    def __init__(self, store, recs: list[dict], mem):
        self.store, self.recs, self.mem, self.i = store, recs, mem, 0
        self.retained: list[dict] = []

    def advance(self, before: str) -> None:
        batch = []
        while self.i < len(self.recs) and (self.recs[self.i]["date"] or "0000") < before:
            batch.append(self.recs[self.i]); self.i += 1
        if batch:
            import inspect
            if hasattr(self.mem, "retain_many"):
                wait = "wait" in inspect.signature(self.mem.retain_many).parameters
                self.mem.retain_many(batch, wait=True) if wait else self.mem.retain_many(batch)
            else:
                [self.mem.retain(r["text"], r["tags"], r["date"], r["doc_id"], r["meta"]) for r in batch]
            self.retained += batch
        late = [r["doc_id"] for r in self.retained if r["date"] and r["date"] >= before]
        if late:
            raise AssertionError(f"records from the future leaked into memory: {late[:3]}")


class Evaluator:
    def __init__(self, store, llm, out_path: Path, progress: Progress = PROGRESS, train_n: int = 8, hindsight=None, hindsight_reason: str = ""):
        self.store, self.llm, self.out, self.progress = store, CountingLLM(llm), out_path, progress
        self.train_n, self.hindsight, self.hindsight_reason = train_n, hindsight, hindsight_reason
        self.recs = sorted(records.build_all(store, visits=store.history), key=lambda r: (r["date"] or "0000", r["doc_id"]))
        self.levels = ev.visit_levels(store.history, "9999-12-31")
        self.by_job = {v["job_id"]: v for v in store.history}
        self.by_inc: dict[str, list[dict]] = {}
        for v in store.history:
            self.by_inc.setdefault(v["incident_id"], []).append(v)

    # ---------------------------------------------------------------- one incident
    def case(self, v: dict, mem, use_memory: bool) -> Case:
        m = self.store.machine(v["machine_id"])
        a = next((x for x in self.store.alarms if x.get("incident_id") == v["incident_id"]), None)
        alarm = {"id": f"EV-{v['job_id']}", "code": a["code"] if a else "", "description": a["description"] if a else v["symptom"],
                 "readings": a["readings"] if a else {}, "severity": "major", "machine_id": m["id"], "ts": v["date"] + "T09:00:00"}
        job = {"job_id": v["job_id"], "date": v["date"], "machine_id": m["id"], "symptom": v["symptom"]}
        before = v["date"]
        return Case(alarm, m, self.store.site(m["site_id"]), job, self.store, self.llm, TracedMemory(mem, lambda e: None, self.store) if use_memory else NullMemory(),
                    use_memory, before, self.store.visits_before(before) if use_memory else [], self.store.alarms_before(before) if use_memory else [])

    def run_arm(self, v, mem, use_memory, verifier, truth):
        before = self.llm.fail
        out = build_plan(self.case(v, mem, use_memory), verifier)
        ok = self.llm.fail == before
        return out, ok

    # ---------------------------------------------------------------- the run
    def pick(self, limit_test: int | None):
        hold = self.store.holdout_ids()
        firsts = sorted((v for v in self.store.history if v["visit_no"] == 1), key=lambda v: (v["date"], v["job_id"]))
        test = [v for v in firsts if v["machine_id"] in hold]
        train = [v for v in firsts if v["machine_id"] not in hold]
        step = max(1, len(train) // max(1, self.train_n))
        train = train[::step][:self.train_n]
        return train, (test[:limit_test] if limit_test else test)

    def run(self, limit_test: int | None = None) -> dict:
        train, test = self.pick(limit_test)
        self.progress.set(state="running", done=0, total=len(train) + len(test), started=datetime.now().isoformat(timespec="seconds"), message="Tuning on training machines")
        tmp = Path(tempfile.mkdtemp())
        # ---- pass 1: tune the Verifier's parts threshold on TRAINING machines only
        rp = Replay(self.store, self.recs, LocalMemory(tmp / "train.json"))
        stash, train_rows = [], []
        for n, v in enumerate(train, 1):
            rp.advance(v["date"])
            truth = truth_for(self.by_inc[v["incident_id"]], self.levels, self.by_job)
            out, ok = self.run_arm(v, rp.mem, True, None, truth)
            case = self.case(v, rp.mem, True)
            stash.append((case, out, truth, ok))
            train_rows.append({"job": v["job_id"], "machine": v["machine_id"], "ok": ok, "basic": score(out["final"], truth) if ok else None})
            self.progress.set(done=n, message=f"Training incident {n}/{len(train)}")
        best_k, f1s = self.tune(stash)
        tuning = (f"The Verifier's parts threshold (fixes needed on comparable units) was tuned on {len(stash)} training incidents: "
                  + ", ".join(f"K={k}: F1 {f1s[k]:.2f}" for k in sorted(f1s)) + f". K={best_k} chosen. The held-out machines were not looked at.")
        # ---- pass 2: the final score on HELD-OUT machines
        arms = {"none": [], "basic": [], "basic_verified": []}
        if self.hindsight is not None:
            arms |= {"hindsight": [], "hindsight_verified": []}
        rp_b = Replay(self.store, self.recs, LocalMemory(tmp / "test_basic.json"))
        rp_h = Replay(self.store, self.recs, self.hindsight) if self.hindsight is not None else None
        rows, failures = [], []
        ver = Verifier(min_wins=best_k)
        for n, v in enumerate(test, 1):
            truth = truth_for(self.by_inc[v["incident_id"]], self.levels, self.by_job)
            row = {"job": v["job_id"], "date": v["date"], "machine": v["machine_id"], "symptom": v["symptom"], "truth": truth["fix_key"], "arms": {}}
            res_none, ok_n = self.run_arm(v, NullMemory(), False, None, truth)
            row["arms"]["none"] = score(res_none["final"], truth) if ok_n else None
            rp_b.advance(v["date"])
            out_b, ok_b = self.run_arm(v, rp_b.mem, True, ver, truth)
            row["arms"]["basic"] = score(out_b["raw"], truth) if ok_b else None
            row["arms"]["basic_verified"] = score(out_b["final"], truth) if ok_b else None
            row["basic_vetoes"] = [{"item": x["item"], "target": x["target"]} for x in out_b["vetoes"]]
            if rp_h is not None:
                rp_h.advance(v["date"])
                out_h, ok_h = self.run_arm(v, rp_h.mem, True, ver, truth)
                row["arms"]["hindsight"] = score(out_h["raw"], truth) if ok_h else None
                row["arms"]["hindsight_verified"] = score(out_h["final"], truth) if ok_h else None
            for k in arms:
                s = row["arms"].get(k)
                arms[k].append(s)
                if s is None:
                    failures.append({"job": v["job_id"], "machine": v["machine_id"], "arm": k, "why": "the LLM was unavailable for this run (excluded from the rates)"})
                elif not s["ftf"]:
                    why = ("it did not name the repair that really fixed it (proposed: " + s["top"][:70] + "; real: " + truth["fix_key"][:60] + ")") if not s["fix"] \
                        else "right repair but the van would be missing " + ", ".join(s["missing"])
                    failures.append({"job": v["job_id"], "machine": v["machine_id"], "arm": k, "why": why})
            rows.append(row)
            self.progress.set(done=len(train) + n, message=f"Held-out incident {n}/{len(test)}")
            self._save(rows, None)
        res = {"generated": datetime.now().isoformat(timespec="seconds"), "model": ", ".join(f"{m} ({n})" for m, n in getattr(self.llm.llm, "used", {}).items()) or self.llm.model,
               "memory_backend": "basic search (BM25)" + (" + Hindsight" if self.hindsight is not None else ""),
               "skipped": {} if self.hindsight is not None else {"hindsight": self.hindsight_reason or "Hindsight was not available"},
               "tuning": tuning, "chosen_min_wins": best_k, "llm_calls": self.llm.calls, "llm_failures": self.llm.fail,
               "split": {"holdout_machines": len(self.store.holdout_ids()), "train_machines": len(self.store.machines) - len(self.store.holdout_ids())},
               "train": {"n_incidents": len(train), "arms": {"basic": {"ftf": rate([r["basic"]["ftf"] if r["basic"] else None for r in train_rows]),
                                                                       "fix": rate([r["basic"]["fix"] if r["basic"] else None for r in train_rows])}}},
               "test": {"n_incidents": len(test), "arms": {k: {m: rate([(s[m] if s else None) for s in lst]) for m in ("fix", "parts", "ftf", "warn")} for k, lst in arms.items()}},
               "failures": failures[:60], "partial": False, "incidents": rows}
        self.out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
        self.progress.set(state="done", message="Finished")
        return res

    def tune(self, stash):
        """Pick the Verifier threshold K by the F1 of the parts it lets through, using training incidents only (no extra LLM calls)."""
        f1s = {}
        for k in (1, 2, 3):
            vals = []
            for case, out, truth, ok in stash:
                if not ok or not truth["parts"]:
                    continue
                carry = out["raw"]["parts"]["carry"]
                v = Verifier(min_wins=k).review(case, STUB_DISPATCH, {"causes": out["raw"]["diagnosis"]["causes"]}, {"carry": carry})
                gone = {x["item"] for x in v["vetoes"] if x["target"] == "parts"}
                kept = [p["part"] for p in carry if p["part"] not in gone]
                need = [p.lower() for p in truth["parts"]]
                tp = sum(1 for n in need if any(n in c.lower() or c.lower() in n for c in kept))
                prec, rec = (tp / len(kept) if kept else 0.0), tp / len(need)
                vals.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
            f1s[k] = sum(vals) / len(vals) if vals else 0.0
        best = max(sorted(f1s), key=lambda k: (round(f1s[k], 4), -k))
        return best, f1s

    def _save(self, rows, res):
        self.out.write_text(json.dumps({"partial": True, "incidents": rows}, indent=1, ensure_ascii=False), encoding="utf-8")


def run_in_process(store, llm, limit: int | None = None, out: Path | None = None, hindsight=None, reason: str = "") -> dict:
    from store import DATA
    out = out or DATA / "eval_results.json"
    try:
        if hindsight is None and not reason:
            reason = "Hindsight was not used for this run"
        res = Evaluator(store, llm, out, progress=PROGRESS, hindsight=hindsight, hindsight_reason=reason).run(limit)
        md = out.parent.parent.parent / "docs" / "EVALUATION.md"
        md.parent.mkdir(exist_ok=True)
        md.write_text(render_markdown(res), encoding="utf-8")
        return res
    except Exception as exc:
        log.exception("evaluation failed")
        PROGRESS.set(state="error", message=str(exc)[:300])
        raise


def _pct(x): return "n/a" if x is None else f"{round(x * 100)}%"
def _fmt(r): return "n/a" if not r or r["rate"] is None else f"{_pct(r['rate'])} ({r['k']}/{r['n']}, 95% CI {_pct(r['ci'][0])}-{_pct(r['ci'][1])})"


ARM_LABEL = {"none": "No memory", "basic": "Basic search (BM25)", "basic_verified": "Basic search + Verifier", "hindsight": "Hindsight", "hindsight_verified": "Hindsight + Verifier"}


def render_markdown(r: dict) -> str:
    T = r["test"]["arms"]
    L = ["# Replay evaluation", "",
         f"Generated {r['generated']}. Plans built by {r['model']}; memory: {r['memory_backend']}. "
         f"{r['test']['n_incidents']} incidents on {r['split']['holdout_machines']} held-out machines (final score) and {r['train']['n_incidents']} on training machines (tuning).", "",
         "**Everything below is simulated: a replay of a synthetic history, not a field trial.**", "",
         "## Method", "",
         "Every incident is planned several ways using **only records dated before it** (the harness raises if a later record is present). A plan is a diagnosis (the repair to do) "
         "and a parts list. Plans are scored against what really happened, deterministically, without an LLM judge:", "",
         "| Metric | Meaning |", "| --- | --- |",
         "| Right fix | The plan's top repair is the repair that really fixed it. A fix that came back within 30 days is not counted as the fix; the later repair is. |",
         "| Right parts | The van would have carried every part the real fix needed. |",
         "| Predicted first-time fix | Right fix and right parts. |",
         "| Failed fix avoided | The plan did not recommend an attempt that really failed on that incident. |", "",
         "Arms: **no memory**; **basic search** (BM25 keyword search over earlier records); **+ Verifier** (a deterministic checker that sees only raw visit records, vetoes claims "
         "the records do not support, and sends the agent back to revise). Hindsight arms run the same plans on the Hindsight bank.", "",
         "## Result on held-out machines", "", "| Arm | Right fix | Right parts | Predicted first-time fix | Failed fix avoided |", "| --- | --- | --- | --- | --- |"]
    for k, lab in ARM_LABEL.items():
        if k in T:
            L.append(f"| {lab} | {_fmt(T[k]['fix'])} | {_fmt(T[k]['parts'])} | **{_fmt(T[k]['ftf'])}** | {_fmt(T[k]['warn'])} |")
    for k, why in r.get("skipped", {}).items():
        L.append(f"| {ARM_LABEL.get(k, k)} (+ Verifier) | not run | not run | not run | not run |")
    if r.get("skipped"):
        L += ["", "**Not run:** " + "; ".join(f"{ARM_LABEL.get(k, k)}: {w}" for k, w in r["skipped"].items()) + ". The rows above are the arms that could be run honestly; they are not a Hindsight result."]
    L += ["", "## Tuning (training machines only)", "", r["tuning"], "",
          f"On the {r['train']['n_incidents']} training incidents, basic search alone predicted first-time fix for {_fmt(r['train']['arms']['basic']['ftf'])}.", "",
          "## Failures, listed honestly", ""]
    for f in r["failures"][:25]:
        L.append(f"- `{f['job']}` on {f['machine']}, {ARM_LABEL.get(f['arm'], f['arm'])}: {f['why']}")
    L += ["", "## Caveats (read before quoting a number)", "",
          f"- **Small sample.** {r['test']['n_incidents']} held-out incidents: the intervals are wide, so read the direction, not the percentage.",
          "- **Synthetic data.** The history is generated, with realistic mess (wrong diagnoses, parts shortages, fixes that stop working) but recurring faults repeat on purpose.",
          "- **Single run, LLM output varies.** A different run will give different numbers.",
          f"- **LLM availability.** {r['llm_failures']} of {r['llm_calls']} LLM calls came back empty (rate limits); runs where that happened are excluded from the rates, never scored as wrong answers.",
          "- **The Verifier is deterministic code, not an LLM.** It cannot be talked into approving something the records do not support, and it can be wrong when the records are thin (n < 5 is labelled a weak signal).",
          "- **Remote fixes** are decided by rules over the alarm log and are not part of this score."]
    return "\n".join(L) + "\n"
