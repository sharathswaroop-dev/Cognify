"""Run the replay evaluation from the command line (the same code the dashboard button uses).

    python scripts/run_eval.py             # all held-out incidents plus a training sample for tuning
    python scripts/run_eval.py --limit 6   # quick smoke run on 6 held-out incidents

Writes backend/data/eval_results.json and docs/EVALUATION.md. Hindsight arms run only if Hindsight is reachable and has credit;
otherwise they are listed as 'not run' with the reason. Uses a fresh Hindsight bank per run, so it never touches the demo memory.
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import evaluation  # noqa: E402
from llm import LLM  # noqa: E402
from memory import build_memory  # noqa: E402
from store import Store  # noqa: E402


class Printing(evaluation.Progress):
    def set(self, **kw):
        super().set(**kw)
        if "message" in kw:
            print(f"[{time.strftime('%H:%M:%S')}] {self.done}/{self.total} {self.message}", flush=True)


def hindsight_if_available():
    """A fresh Hindsight bank, but only if a real round trip works (no key or no credit means: skip those arms and say why)."""
    try:
        mem = build_memory("eval", bank_id=f"sitememory-v3-eval-{int(time.time())}")
        if mem.name != "hindsight":
            return None, "no Hindsight key configured"
        mem.retain("probe", ["kind:site"], None, "probe", {})
        return mem, ""
    except Exception as exc:
        return None, f"Hindsight unavailable: {str(exc).splitlines()[0][:140]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-hindsight", action="store_true")
    args = ap.parse_args()
    hs, why = (None, "skipped with --no-hindsight") if args.no_hindsight else hindsight_if_available()
    print("Hindsight arms:", "ON" if hs else f"OFF ({why})", flush=True)
    evaluation.PROGRESS = Printing()
    res = evaluation.run_in_process(Store(), LLM(), args.limit, hindsight=hs, reason=why)
    print("done:", res["test"]["n_incidents"], "held-out incidents")


if __name__ == "__main__":
    main()
