# SiteMemory: handoff for the next Claude session

Read this file and README.md first, then continue from "Next steps".

## Context
- Event: "AI Agents That Learn Using Hindsight" (Vectorize). Required: Hindsight memory + Band AI desktop. Online round: judged on the repo, the video and the posts.
- Judging: Innovation 30%, Hindsight memory use 25%, Technical 20%, UX 15%, Real-world impact 10%.
- Idea: **SiteMemory**, field-service agents (HVAC) that remember repairs and check themselves. Team brief doc: https://claude.ai/artifact/Mrk5rjy7VrPj3ptquD3ENd; the flow the website follows: https://claude.ai/artifact/KU4zBJ75YTF9b7oJ9NEyjp

## Content rules (from the content guide; breaking them disqualifies)
- Never use the event-type word (the one in the brief's title) in articles, posts, hashtags, video titles or repo docs. `python scripts/check_content.py` checks this and the length/format rules.
- Each member: one article (800-1500 words, public on Medium/Dev.to/Hashnode/LinkedIn Articles) and one LinkedIn post (<800 chars, repo link in the post, article link as first comment, Hindsight GitHub link as another comment, tag Code.in). Drafts: `docs/ARTICLE.md`, `docs/LINKEDIN_POST.md`.
- Team: one 2-5 minute video on YouTube. Script: `docs/VIDEO_SCRIPT.md`.

## What is built (final)
- **Four agents on one shared bank** (`backend/agents.py`): Dispatcher (rules over the alarm log; reset/setpoint/read-log only; never repeats a failed remote fix), Diagnostician (recall + reflect; n / verified / rate / Wilson interval; n<5 weak signal; cites jobs), Parts agent (proposes, never judges), Verifier (raw records only, deterministic, vetoes; a vetoed agent revises).
- **Evidence levels** (`evidence.py`): suspected -> fixed at visit -> stable 30d -> stable 90d, computed from raw records as of any date; a fix that comes back within 30 days never counts.
- **Shared bank records** (`records.py`): visits, follow-ups, alarms, sites, beliefs; machine ids validated. Local BM25 fallback (`memory.FallbackMemory`) when Hindsight fails, with a visible banner.
- **Live demo** (`mesh/runner.py`, `frontend/index.html`): one alarm, two paths (no memory / shared bank), live streaming over SSE, memory panel, vetoes, simulated consequence (`simulate.py`). Band handoffs for the with-memory path (`mesh/band.py`), in-process fallback.
- **Phone + voice** (`voice.py`), **dashboard** (watchlist, ROI with Benchmark/Simulated/Your-inputs labels, fix outcomes), **beliefs** (`beliefs.py`).
- **Leak-proof replay evaluation** (`evaluation.py`, `scripts/run_eval.py`): no memory / basic BM25 / +Verifier (and Hindsight arms when reachable), tuned on training machines, scored on held-out machines, deterministic scoring.
- Data: `scripts/generate_data.py` (deterministic): 12 sites, 51 machines (8 held out), ~230 visits.
- Tests: `python -m pytest tests -q` (no network or keys).

## State when this was written (read this)
- **Hindsight credit was exhausted** ($5 promo credit; balance ~$0.01, HTTP 402). The app runs on the local fallback and says so. Every Hindsight-dependent claim is marked not run. To finish: top up at https://ui.hindsight.vectorize.io, restart (it seeds the shared bank), then `python scripts/run_eval.py` to add the Hindsight arms.
- **Groq free-tier daily token limits** were hit repeatedly; the wrapper fails over across gpt-oss-120b, gpt-oss-20b and qwen/qwen3.8-27b.
- **Band** is implemented against the OpenAPI spec and tested against a mock; not run against the live service (needs 4 agent keys).
- Keys were pasted in chat: rotate them after the event.

## Gotchas learned the hard way
- The Hindsight client's sync methods break inside FastAPI worker threads. One background event loop (`memory._LoopThread`).
- Hindsight rewrites memories into facts: job ids vanish from text. Citations use the returned `document_id` (`Memory.ref()`).
- `recall` with several tags needs `match="all"` or alarms pollute diagnoses.
- Family-level statistics hide a generation split: stats and part support are scoped to comparable units (`agents.scoped`).
- Bash heredocs choke on long Python/JS with quotes; write patch scripts to a file instead.

## Next steps
1. Top up Hindsight, rerun the evaluation, regenerate `docs/EVALUATION.md`, update the numbers in the article, post and video.
2. Four Band agent keys in `.env`; first live Band run (`docs/BAND_SETUP.md`).
3. Record the video; each member writes an article and a post from the drafts.
4. Rotate the keys.
