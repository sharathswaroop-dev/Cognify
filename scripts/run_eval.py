"""Run the replay evaluation from the command line (same code the dashboard button uses).

    python scripts/run_eval.py            # all incidents, about 20 minutes on real Hindsight + Groq
    python scripts/run_eval.py --limit 8  # quick smoke run

Writes backend/data/eval_results.json and docs/EVALUATION.md. Uses a fresh Hindsight bank per run, so it never
touches the demo memory.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from agent import Agent  # noqa: E402
from beliefs import BeliefEngine  # noqa: E402
from evaluation import Evaluator, Progress, render_markdown  # noqa: E402
from memory import bank_prefix, build_memory  # noqa: E402
from store import Store  # noqa: E402


class Printing(Progress):
    def set(self, **kw):
        super().set(**kw)
        if "message" in kw or "done" in kw:
            print(f"[{time.strftime('%H:%M:%S')}] {self.done}/{self.total} {self.message}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    store = Store()
    mem = build_memory("eval", bank_id=f"{bank_prefix()}-eval-{int(time.time())}")
    if mem.name == "local":
        mem.reset()
    agent = Agent(mem, store)
    agent.belief_fn = BeliefEngine(store).for_machine
    out = ROOT / "backend" / "data" / "eval_results.json"
    ev = Evaluator(store, agent, agent.llm, mem, out, site_records=[agent.site_record(s) for s in store.sites],
                   visit_record=agent.visit_record, progress=Printing())
    ev.run(args.limit)
    md = ROOT / "docs" / "EVALUATION.md"
    md.parent.mkdir(exist_ok=True)
    md.write_text(render_markdown(json.loads(out.read_text(encoding="utf-8"))), encoding="utf-8")
    print(f"done: {out}\n      {md}")


if __name__ == "__main__":
    main()
