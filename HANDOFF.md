# SiteMemory: handoff for the next Claude session

Read this file and README.md first, then continue from "Next steps".

## Context
- Event: "AI Agents That Learn Using Hindsight" (Vectorize). Required: Hindsight memory + Band AI desktop.
- Judging: Innovation 30%, Hindsight memory use 25%, Technical 20%, UX 15%, Real-world impact 10%.
- Idea: **SiteMemory**, a field-service technician assistant (HVAC). Chosen because incident response, accounts payable and claims were
  already built many times with Hindsight. Team brief doc: https://claude.ai/artifact/Mrk5rjy7VrPj3ptquD3ENd

## Content rules (from the content guide; breaking them disqualifies)
- Never use the event-type word (the one in the brief's title) in articles, LinkedIn posts, hashtags, video titles or repo docs.
- Each member: one article (800-1500 words, public on Medium/Dev.to/Hashnode/LinkedIn Articles) and one LinkedIn post (<800 chars,
  repo link in the post, article link as first comment, Hindsight GitHub link as another comment, tag Code.in).
- Team: one 2-5 minute video on YouTube (1080p, screen + voiceover, show retain/recall live), thumbnail via Nano Banana.
- Articles must link github.com/vectorize-io/hindsight, hindsight.vectorize.io and vectorize.io/what-is-agent-memory.
- Share the article on r/llmdevs, r/sideproject, r/aiagents or r/aimemory.
- Drafts are in `docs/ARTICLE.md`, `docs/LINKEDIN_POST.md`, `docs/VIDEO_SCRIPT.md`.

## What is built

**Round 1** (single agent): recall at machine / model-family / site level, reflect, Groq JSON briefing with fallbacks, retain after
every visit, memory off/on comparison, manager dashboard. `backend/agent.py`, `memory.py`, `llm.py`, `app.py`, `frontend/index.html`.

**Round 2** (this session):
1. **Multi-agent mesh on Band** (`backend/mesh/`): Dispatcher, Diagnostician, Parts agent, Field assistant, each with its own Hindsight
   bank (`<prefix>-dispatcher|diagnostician|parts|field`). Handoffs go through a Band room using the REST Agent API (`mesh/band.py`);
   falls back to in-process if Band is not configured or fails. Alarm feed (`data/alarms_*.json`), live room streamed over SSE,
   citations validated against recalled memories. Band is tested against a mock only (see `docs/BAND_SETUP.md`).
2. **Replay evaluation** (`backend/evaluation.py`, `scripts/run_eval.py`): replays history in date order with leakage assertion,
   scores without vs with memory, Wilson intervals, learning curve. Results in `backend/data/eval_results.json`, `docs/EVALUATION.md`.
3. **Voice logging** (`backend/voice.py`): MediaRecorder -> Groq Whisper (`whisper-large-v3`) -> LLM extraction -> confirm -> retain.
4. **Self-correcting memory** (`backend/beliefs.py`): tracks fix outcomes per model family; a statistical rule flags a contradicted
   lesson, scopes it to the failing cohort (units installed 2023+), retains the correction to Hindsight, says "Belief updated" in briefings.
   `scripts/extend_data.py` adds the drift (4 newer VRV units where the contactor swap fails and the inverter PCB fixes it).

Tests: `python -m pytest tests -q` (no network or keys needed; uses a fake LLM and local memory).

## Gotchas learned the hard way
- The Hindsight client's sync methods break inside FastAPI worker threads. All calls go through one background event loop (`memory._LoopThread`).
- Hindsight rewrites memories into facts, so job ids vanish from the text. Citations use the `document_id` it returns (`Memory.ref()`).
- `retain_many` is processed in the background (1-3 minutes); single `retain` is synchronous.
- Destructive tests (logging visits) write to the real banks. Use `HINDSIGHT_BANK_PREFIX=sitememory-v2dev` for a sandbox.
- Bash heredocs choke on long Python/JS with quotes; write patch scripts to a file instead.

## Run
```
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python backend\app.py        # http://localhost:8000
```
First start seeds four Hindsight banks (allow 2-3 minutes). Keys in `.env` (never commit it).

## Next steps
1. Add the four Band agent keys to `.env` and run once against live Band (`docs/BAND_SETUP.md`); fix any field name that differs.
2. Rotate the Groq and Hindsight keys after the event (they were shared in a chat).
3. Record the team video; each member writes an article and a post from the drafts.
4. Optional: add a second drift (a different family) so the belief panel shows two corrections.
