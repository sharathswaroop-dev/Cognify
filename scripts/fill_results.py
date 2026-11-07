"""Write the numbers from the latest evaluation into the README, the article draft and the LinkedIn post draft.

    python scripts/run_eval.py && python scripts/fill_results.py

Safe to run again after every evaluation: the README and article blocks sit between <!-- RESULTS-START --> and <!-- RESULTS-END -->, and the post line is
rewritten in place. Nothing is invented: every figure is read from backend/data/eval_results.json, and what could not be run is said in the text.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "backend" / "data" / "eval_results.json"
NAME = {"none": "No memory", "basic": "Basic search (BM25)", "basic_verified": "Basic search + Verifier", "hindsight": "Hindsight", "hindsight_verified": "Hindsight + Verifier"}


def pc(x):
    return "n/a" if x is None else f"{round(x * 100)}%"


def cell(o):
    return "n/a" if not o or o["rate"] is None else f"{pc(o['rate'])} ({o['k']}/{o['n']}, 95% {pc(o['ci'][0])}-{pc(o['ci'][1])})"


def build(r: dict) -> dict:
    A, T = r["test"]["arms"], r["test"]
    arms = [k for k in NAME if k in A]
    table = "| Arm | Predicted first-time fix | Right parts | Failed fix avoided |\n| --- | --- | --- | --- |\n" + "\n".join(
        f"| {NAME[k]} | **{cell(A[k]['ftf'])}** | {cell(A[k]['parts'])} | {cell(A[k]['warn'])} |" for k in arms)
    skipped = "; ".join(f"{NAME.get(k, k)}: {w}" for k, w in (r.get("skipped") or {}).items())
    fails = r.get("llm_failures", 0)
    notes = [f"Simulated: a replay of a synthetic history, scored on {T['n_incidents']} incidents on {r['split']['holdout_machines']} held-out machines that were never used for tuning.",
             f"Generated {r['generated'][:16].replace('T', ' ')} with {r['memory_backend']}."]
    if skipped:
        notes.append(f"Not run: {skipped}.")
    if fails:
        notes.append(f"{fails} of {r['llm_calls']} model calls came back empty (rate limits); those runs are excluded from the rates, so the intervals are wide.")
    ver = ""
    if "basic" in A and "basic_verified" in A and A["basic"]["ftf"]["rate"] is not None and A["basic_verified"]["ftf"]["rate"] is not None:
        a, b = A["basic"]["ftf"]["rate"], A["basic_verified"]["ftf"]["rate"]
        ver = (f"On basic search, the Verifier changed predicted first-time fix from {pc(a)} to {pc(b)}"
               + (": it lowered the score here, because when it vetoes the only candidate the plan falls back to escalation, which is scored as no answer." if b < a else "."))
    best_k = next((k for k in ("hindsight_verified", "hindsight", "basic_verified", "basic") if k in A and A[k]["ftf"]["rate"] is not None), None)
    none = A.get("none", {}).get("ftf", {})
    post = "n/a"
    if best_k and none.get("rate") is not None:
        kind = "Hindsight" if best_k.startswith("hindsight") else "keyword memory"
        post = f"{pc(none['rate'])} first-time fix with no memory vs {pc(A[best_k]['ftf']['rate'])} with {kind}, simulated, {T['n_incidents']} incidents."
    block = table + "\n\n" + " ".join(notes) + ("\n\n" + ver if ver else "") + "\n\nMethod, tuning and every failure: [docs/EVALUATION.md](docs/EVALUATION.md)."
    return {"block": block, "post": post}


def put_block(path: Path, token: str, text: str) -> None:
    s = path.read_text(encoding="utf-8")
    span = f"<!-- RESULTS-START -->\n{text}\n<!-- RESULTS-END -->"
    if "<!-- RESULTS-START -->" in s:
        s = re.sub(r"<!-- RESULTS-START -->.*?<!-- RESULTS-END -->", lambda m: span, s, flags=re.S)
    elif token in s:
        s = s.replace(token, span, 1)
    else:
        sys.exit(f"{path.name}: no placeholder or marker found")
    path.write_text(s, encoding="utf-8")


def put_post(path: Path, text: str) -> None:
    s = path.read_text(encoding="utf-8")
    s2 = re.sub(r"(• Replayed history with no leakage; held-out machines:).*", lambda m: f"{m.group(1)} {text}", s, count=1)
    if s2 == s and text not in s:
        sys.exit("post: line not found")
    path.write_text(s2, encoding="utf-8")


def main():
    r = json.loads(RES.read_text(encoding="utf-8"))
    if r.get("partial") or "test" not in r:
        sys.exit("The latest evaluation did not finish: run scripts/run_eval.py first.")
    out = build(r)
    put_block(ROOT / "README.md", "EVAL_SECTION", out["block"])
    put_block(ROOT / "docs" / "ARTICLE.md", "{{RESULTS}}", out["block"].replace("(docs/EVALUATION.md)", "(https://github.com/sharathswaroop-dev/sitememory/blob/main/docs/EVALUATION.md)"))
    put_post(ROOT / "docs" / "LINKEDIN_POST.md", out["post"])
    print("README, article and post updated from", r["generated"])
    print("post line:", out["post"])


if __name__ == "__main__":
    main()
