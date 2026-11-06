"""Replay evaluation: does memory actually make the briefing better?

Walk the service history in date order. At each incident's first visit, brief the technician twice with the
same agent and model:
  WITHOUT  the job ticket only
  WITH     memory built ONLY from visits dated strictly before that incident (a fresh Hindsight bank that
           receives each visit after it has been scored, so nothing from the future can leak in)
Then score each briefing against what really happened in that incident:
  fix_hit   did it recommend the fix that actually worked?
  warn_hit  did it warn against the attempts that actually failed?
  part_hit  did it tell the technician to bring the part that actually fixed it?
  ftf       'predicted first-time fix' = fix_hit and no needed part missing
Scoring uses an LLM judge (same model: see the caveats in docs/EVALUATION.md) cross-checked by a plain
keyword matcher, and the two are compared.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("sitememory.eval")
STOP = set("the a an of on at for to in and or is was it this that with by from after before unit units replaced checked "
           "replace fixed using then also not did were has had its into".split())

JUDGE_PROMPT = """You are a strict grader of an HVAC technician briefing. You get what ACTUALLY happened on the job
(ground truth) and the briefing that was written BEFORE the visit. Judge only from the briefing text.
- recommends_working_fix: true only if the briefing tells the technician to do the same repair that actually worked
  (the same action, not merely a related check). A generic 'inspect the contactor' is false if the real fix was replacing it
  AND the briefing does not say to replace it.
- warned_against: one boolean per failed attempt, in order: true if the briefing tells the technician NOT to do it / that it
  failed before / to skip it. Generic cautions do not count.
- parts_listed: one boolean per needed part, in order: true if the briefing tells the technician to bring that part.
Return ONLY JSON: {"recommends_working_fix":bool,"warned_against":[bool,...],"parts_listed":[bool,...]}"""


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 3 and w not in STOP}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round((c - m) / d, 3), round((c + m) / d, 3))


def rate(vals: list[bool | None]) -> dict:
    v = [x for x in vals if x is not None]
    k = sum(1 for x in v if x)
    lo, hi = wilson(k, len(v))
    return {"k": k, "n": len(v), "rate": round(k / len(v), 3) if v else None, "ci": [lo, hi]}


def ground_truth(visits: list[dict]) -> dict:
    failed, fix, parts = [], "", []
    for v in sorted(visits, key=lambda x: x["visit_no"]):
        for a in v["actions"]:
            if a["result"] == "failed" and a["action"] not in failed:
                failed.append(a["action"])
            if a["result"] == "worked" and not fix:
                fix, parts = a["action"], list(v.get("parts_used") or [])
    return {"failed": failed, "fix": fix, "parts": parts,
            "first_time": len(visits) == 1 and visits[0]["outcome"] == "resolved"}


def brief_text(b: dict, keys: tuple[str, ...]) -> str:
    return " ".join(str(b.get(k) or "") if not isinstance(b.get(k), list) else " ".join(map(str, b[k])) for k in keys)


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


class Evaluator:
    def __init__(self, store, agent, llm, memory, out_path: Path, site_records: list[dict] | None = None,
                 visit_record=None, progress: Progress = PROGRESS):
        self.store, self.agent, self.llm, self.memory = store, agent, llm, memory
        self.out_path, self.progress = out_path, progress
        self.site_records, self.visit_record = site_records or [], visit_record
        self.retained: list[dict] = []  # visits currently inside the eval memory

    # ------------------------------------------------------------------ scoring
    def judge(self, b: dict, truth: dict) -> dict:
        user = (f"GROUND TRUTH\nFixes that FAILED: {truth['failed'] or 'none'}\nFix that WORKED: {truth['fix']}\n"
                f"Parts needed: {truth['parts'] or 'none'}\n\nBRIEFING\nHeadline: {b.get('headline')}\nLikely cause: {b.get('likely_cause')}\n"
                f"Do first: {b.get('do_first')}\nAvoid: {b.get('avoid')}\nBring: {b.get('bring')}")
        d = self.llm.json_chat(JUDGE_PROMPT, user, required=("recommends_working_fix",)) if self.llm else None
        if d is None:
            return {"error": True}
        fa = [bool(x) for x in (d.get("warned_against") or [])]
        pl = [bool(x) for x in (d.get("parts_listed") or [])]
        fa += [False] * (len(truth["failed"]) - len(fa))
        pl += [False] * (len(truth["parts"]) - len(pl))
        return {"fix": bool(d["recommends_working_fix"]), "warned": fa[:len(truth["failed"])], "parts": pl[:len(truth["parts"])]}

    def keyword_check(self, b: dict, truth: dict) -> dict:
        plan = tokens(brief_text(b, ("headline", "likely_cause", "do_first")))
        avoid = tokens(brief_text(b, ("avoid",)))
        bring = tokens(brief_text(b, ("bring",)))
        fix_t = tokens(truth["fix"])
        fix = bool(fix_t) and len(fix_t & plan) / len(fix_t) >= 0.6
        warned = [bool(tokens(f)) and len(tokens(f) & avoid) / len(tokens(f)) >= 0.6 for f in truth["failed"]]
        parts = [bool(tokens(p)) and len(tokens(p) & bring) / len(tokens(p)) >= 0.5 for p in truth["parts"]]
        return {"fix": fix, "warned": warned, "parts": parts}

    def score(self, b: dict, truth: dict) -> dict:
        j, k = self.judge(b, truth), None
        k = self.keyword_check(b, truth)
        use = k if j.get("error") else j
        fix = use["fix"]
        warn = (all(use["warned"]) if use["warned"] else None) if truth["failed"] else None
        part = (all(use["parts"]) if use["parts"] else None) if truth["parts"] else None
        return {"fix_hit": fix, "warn_hit": warn, "part_hit": part, "ftf": bool(fix and part is not False),
                "judge": j, "keyword": k, "judge_error": bool(j.get("error"))}

    # ------------------------------------------------------------------ replay
    def _retain(self, v: dict) -> None:
        rec = self.visit_record(v)
        self.memory.retain(rec["text"], rec["tags"], rec["date"], rec["doc_id"], rec["meta"])
        self.retained.append(v)

    def run(self, limit: int | None = None) -> dict:
        visits = sorted(self.store.history, key=lambda v: (v["date"], v["visit_no"]))
        by_inc: dict[str, list[dict]] = {}
        for v in visits:
            by_inc.setdefault(v["incident_id"], []).append(v)
        firsts = [v for v in visits if v["visit_no"] == 1]
        if limit:
            firsts = firsts[:limit]
        self.progress.set(state="running", done=0, total=len(firsts), started=datetime.now().isoformat(timespec="seconds"),
                          message="Seeding site profiles")
        if self.site_records:
            self.memory.retain_many(self.site_records)  # site access rules are standing policy, not dated history
        queue = list(visits)
        rows = []
        for i, v in enumerate(firsts, 1):
            while queue and queue[0]["date"] < v["date"]:
                self._retain(queue.pop(0))
            leak = [x["job_id"] for x in self.retained if x["date"] >= v["date"]]
            if leak:
                raise AssertionError(f"future visits leaked into memory: {leak}")
            truth = ground_truth(by_inc[v["incident_id"]])
            job = {"job_id": v["job_id"], "date": v["date"], "machine_id": v["machine_id"], "site_id": v["site_id"],
                   "technician_id": v["technician_id"], "symptom": v["symptom"]}
            self.progress.set(message=f"Incident {i}/{len(firsts)}: {v['symptom'][:50]}")
            as_of = list(self.retained)
            arms = {}
            for arm, use_memory in (("without", False), ("with", True)):
                res = self.agent.briefing(job, use_memory, as_of=v["date"], visits=as_of)
                sc = self.score(res["briefing"], truth)
                arms[arm] = {**sc, "briefing": res["briefing"], "memories_used": len(res["memories_used"]),
                             "beliefs": [b["text"] for b in res.get("belief_updates", [])]}
            rows.append({"n": i, "incident": v["incident_id"], "job_id": v["job_id"], "date": v["date"],
                         "machine_id": v["machine_id"], "symptom": v["symptom"], "truth": truth,
                         "memory_visits": len(self.retained), "arms": arms})
            self.progress.set(done=i)
            self._save(rows, partial=True)
        out = self._summarise(rows)
        self._save(rows, out=out)
        self.progress.set(state="done", message="Finished")
        return out

    # ------------------------------------------------------------------ report
    def _summarise(self, rows: list[dict]) -> dict:
        def arm(name, key):
            return rate([r["arms"][name][key] for r in rows])
        summary = {n: {"fix": arm(n, "fix_hit"), "warn": arm(n, "warn_hit"), "part": arm(n, "part_hit"), "ftf": arm(n, "ftf")}
                   for n in ("without", "with")}
        third = max(1, len(rows) // 3)
        thirds = []
        for label, chunk in (("first third", rows[:third]), ("middle third", rows[third:2 * third]), ("last third", rows[2 * third:])):
            if chunk:
                thirds.append({"label": label, "n": len(chunk), "memory_visits": f"{chunk[0]['memory_visits']}-{chunk[-1]['memory_visits']}",
                               **{n: rate([r["arms"][n]["ftf"] for r in chunk]) for n in ("without", "with")},
                               **{f"{n}_fix": rate([r["arms"][n]["fix_hit"] for r in chunk]) for n in ("without", "with")}})
        curve = []
        for idx, r in enumerate(rows):
            win = rows[max(0, idx - 7): idx + 1]
            curve.append({"n": r["n"], "date": r["date"], "memory_visits": r["memory_visits"],
                          **{f"{n}_fix_roll": round(sum(1 for x in win if x["arms"][n]["fix_hit"]) / len(win), 3) for n in ("without", "with")},
                          **{f"{n}_ftf_roll": round(sum(1 for x in win if x["arms"][n]["ftf"]) / len(win), 3) for n in ("without", "with")},
                          **{f"{n}_fix": int(bool(r["arms"][n]["fix_hit"])) for n in ("without", "with")}})
        agree = [(r["arms"][a]["judge"].get("fix") == r["arms"][a]["keyword"]["fix"]) for r in rows for a in ("without", "with")
                 if not r["arms"][a]["judge_error"]]
        actual = sum(1 for r in rows if r["truth"]["first_time"]) / len(rows) if rows else 0
        return {"generated": datetime.now().isoformat(timespec="seconds"), "n_incidents": len(rows),
                "model": getattr(self.llm, "model", "?"), "memory_backend": getattr(self.memory, "name", "?"),
                "bank": getattr(self.memory, "bank_id", "local"), "summary": summary, "thirds": thirds, "curve": curve,
                "actual_company_first_time_fix": round(actual, 3),
                "judge_keyword_agreement_on_fix": round(sum(agree) / len(agree), 3) if agree else None,
                "judge_errors": sum(1 for r in rows for a in ("without", "with") if r["arms"][a]["judge_error"])}

    def _save(self, rows, out=None, partial=False):
        data = {"partial": partial, "incidents": rows}
        if out:
            data.update(out)
            data["partial"] = False
        self.out_path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def pct(x) -> str:
    return "n/a" if x is None else f"{round(x * 100)}%"


def fmt(r: dict) -> str:
    return f"{pct(r['rate'])} ({r['k']}/{r['n']}, 95% CI {pct(r['ci'][0])}-{pct(r['ci'][1])})"


def render_markdown(res: dict) -> str:
    s = res["summary"]
    L = ["# Replay evaluation", "",
         f"Generated {res['generated']} · model `{res['model']}` · memory `{res['memory_backend']}` (bank `{res['bank']}`) · "
         f"{res['n_incidents']} incidents replayed in date order.", "",
         "## Method", "",
         "Every incident in the service history is briefed twice with the same agent and model: once from the job ticket alone "
         "(**without memory**), and once from a fresh memory bank that contains **only visits dated before that incident** "
         "(**with memory**). Each visit is added to the bank only after its incident has been scored, so nothing from the future can leak in "
         "(the harness asserts this). Briefings are scored against what actually happened.", "",
         "| Metric | Meaning |", "| --- | --- |",
         "| Fix recommended | The briefing tells the technician to do the repair that actually worked |",
         "| Warned off failed attempts | The briefing says to skip every attempt that actually failed (only incidents that had failed attempts) |",
         "| Right part to bring | The briefing lists the part that actually fixed it (only incidents that needed a part) |",
         "| Predicted first-time fix | Fix recommended **and** no needed part missing |", "",
         "## Results", "", "| Metric | Without memory | With memory |", "| --- | --- | --- |",
         f"| Fix recommended | {fmt(s['without']['fix'])} | {fmt(s['with']['fix'])} |",
         f"| Warned off failed attempts | {fmt(s['without']['warn'])} | {fmt(s['with']['warn'])} |",
         f"| Right part to bring | {fmt(s['without']['part'])} | {fmt(s['with']['part'])} |",
         f"| **Predicted first-time fix** | **{fmt(s['without']['ftf'])}** | **{fmt(s['with']['ftf'])}** |", "",
         f"For reference, the company's *actual* first-time-fix rate over these incidents was {pct(res['actual_company_first_time_fix'])} "
         "(incidents resolved on one visit, with no memory-assisted briefing).", "",
         "## Learning curve", "",
         "Predicted first-time-fix rate as memory grows (the early incidents have little or no history to draw on):", "",
         "| Part of the replay | Incidents | Visits in memory | Without memory | With memory |", "| --- | --- | --- | --- | --- |"]
    for t in res["thirds"]:
        L.append(f"| {t['label']} | {t['n']} | {t['memory_visits']} | {fmt(t['without'])} | {fmt(t['with'])} |")
    L += ["", "The dashboard shows the same curve as a chart (rolling 8-incident window).", "",
          "## Caveats (read these before quoting a number)", "",
          f"- **Small sample.** {res['n_incidents']} incidents; the confidence intervals above are wide. Treat the direction as the result, not the exact percentage.",
          "- **Synthetic data.** The history is generated, so recurring faults repeat on purpose. Real fleets are noisier.",
          "- **The judge is an LLM from the same model family as the agent.** To limit this, every score is also computed by a plain keyword matcher; "
          f"the two agree on 'fix recommended' {pct(res['judge_keyword_agreement_on_fix'])} of the time. Judge failures: {res['judge_errors']} (keyword score used instead).",
          "- **Single run.** LLM output varies between runs; one run is reported, not an average.",
          "- **Site access rules** (gate codes, contacts) are standing policy and are loaded at the start, not replayed by date. They do not affect these metrics.",
          "- 'Predicted first-time fix' is a score of the written briefing, not a field trial."]
    return "\n".join(L) + "\n"
