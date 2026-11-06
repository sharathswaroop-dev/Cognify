# SiteMemory

**An AI assistant for HVAC field technicians that remembers every machine, every site and every repair, so the next visit is fixed the first time.**

Built on [Hindsight](https://github.com/vectorize-io/hindsight) agent memory ([docs](https://hindsight.vectorize.io/)) and Groq.

## The problem

Field service companies lose money every time a technician visits the same site twice for one problem. The knowledge about each machine (what failed before, what was tried, what actually fixed it, how to get onto the roof) lives in paper job cards, WhatsApp chats and the heads of people who eventually leave. Every new visit starts from zero.

## What SiteMemory does

Before a job, the technician gets a briefing built from memory:

- **Likely cause**, based on what fixed this exact unit before
- **Don't repeat**: attempts that already failed on this unit or the same model elsewhere, with dates
- **Bring**: the parts that fixed it last time
- **Site notes**: gate codes, contact preferences, permits

After the job, the technician logs what was tried. Failures are kept as well as fixes, so every visit makes the next briefing better.

## How Hindsight memory is used

| Hindsight call | When | What it does here |
| --- | --- | --- |
| `retain` | After every visit (and once to load history) | Stores the visit in natural language, tagged `machine:<id>`, `site:<id>`, `family:<model>` |
| `recall` | Before every job | Three tag-scoped recalls: this machine, same model at other sites, this site's rules |
| `reflect` | Before every job | Synthesises the lessons: what keeps failing, what fixes it, which parts to carry |

The recalled memories and the reflection go to the LLM, which writes the briefing. The UI has a **memory on/off switch** and a side-by-side view, so you can see the same agent with and without memory.

Code: `backend/memory.py` (Hindsight wrapper plus an offline fallback), `backend/agent.py` (recall, reflect, brief, retain).

## Architecture

```
Browser (technician view, compare view, manager dashboard)
        |
FastAPI backend (backend/app.py)
        |-- agent.py: recall -> reflect -> LLM briefing; retain after visit
        |-- memory.py ---> Hindsight Cloud (retain / recall / reflect)
        |-- llm.py   ---> Groq (openai/gpt-oss-120b, retries + JSON validation)
```

Edge cases handled:
- LLM returns malformed JSON or errors: retried, then falls back to a second model, then to a rules-based briefing that still uses memory.
- Hindsight unreachable: recall errors are caught and the agent continues without memory, and the UI shows which backend is active.
- No keys at all: the app runs on a local keyword-memory fallback so the demo never breaks.

## Run it

Requires Python 3.10+.

1. Copy `.env.example` to `.env` and add your keys (Groq: console.groq.com; Hindsight: ui.hindsight.vectorize.io → Get API Key).
2. Windows: double-click `run.bat`. Mac/Linux: `./run.sh`.
3. Open http://localhost:8000

On first start with Hindsight keys, the app loads 59 past visits and 9 site profiles into the bank `sitememory-coolcare`. Hindsight processes them in the background, so give it 1 to 3 minutes before the first briefing.

## Demo script (90 seconds)

1. **Memory off vs on** tab, job J-1201: without memory you get generic checks; with memory: "reset failed twice, carry contactor DK-CTR-24V, gate code 4471, call Priya before 10am".
2. **Technician** tab, job J-1202 (new site, no history): memory still helps through the same-model pattern at other sites.
3. Log a failed attempt on J-1202, then reopen it: the briefing now includes your own visit.
4. **Dashboard**: first-time-fix rate, the attempts that keep failing, and full machine history.

## Data

All data is synthetic: a fictional Bengaluru HVAC contractor (CoolCare Facility Services), 9 sites, 21 machines, 6 technicians and 59 past visits. Regenerate with `python scripts/generate_data.py`.
