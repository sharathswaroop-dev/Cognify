# SiteMemory

**Field-service agents that remember every machine, every site and every repair, so the next visit is fixed the first time.**

Four agents, each with its own [Hindsight](https://github.com/vectorize-io/hindsight) memory bank, coordinate in a [Band](https://band.ai) room
to turn a machine alarm into a diagnosis, a parts plan and a technician briefing. They learn from what *failed* as well as what worked,
correct themselves when a fix stops working on newer equipment, and are scored by replaying the company's whole history in date order.

![SiteMemory architecture](docs/architecture.svg)

| | |
| --- | --- |
| ![Briefing](docs/screenshots/01-technician-briefing.png) | ![Belief updated](docs/screenshots/02-belief-updated.png) |
| Memory-driven briefing: skip what failed, carry the part that fixed it | A belief corrected from evidence, scoped to the newer units |
| ![Memory off vs on](docs/screenshots/04-memory-off-vs-on.png) | ![Agent mesh](docs/screenshots/05-agent-mesh.png) |
| The same job with memory off and on (drag to wipe) | Four agents in a room; each message shows the memories it used |
| ![Voice logging](docs/screenshots/03-voice-logging.png) | ![Dashboard](docs/screenshots/06-dashboard.png) |
| Log a visit by voice, confirm, then retain | Fix outcomes over time and the replay evaluation |

## The problem

A repeat visit costs a service company a technician's day, fuel, an SLA penalty or a customer. The knowledge that prevents it (what failed on this
unit last time, what finally fixed it, which part to carry, the gate code) sits in job cards, chat threads and the heads of people who leave.
Every visit starts from zero.

## What it does

1. **Multi-agent mesh on Band.** A machine alarm (for example `M-07 E3 trip, supply 189V`) starts the flow automatically.
   - **Dispatcher** decides *remote fix* or *send a technician* from its memory of which remote fixes ever worked for that alarm.
   - **Diagnostician** recalls this machine, the same model elsewhere and the site, and returns a root cause that cites the past visits it relied on.
   - **Parts agent** decides what to carry from past fixes, and flags what is not on the van.
   - **Field assistant** writes the technician briefing and records the visit.

   The room streams live to the web UI: who said what, and which memories each agent used. Setup: [docs/BAND_SETUP.md](docs/BAND_SETUP.md).
2. **Replay evaluation.** Every incident in the history is briefed twice (without memory; with memory built only from *earlier* visits) and scored against what really happened. Numbers below.
3. **Voice logging.** Tap the mic in the phone view and speak the visit. Groq Whisper transcribes it, the LLM structures it (attempts with worked/failed, root cause, parts, notes), and you confirm before anything is retained.
4. **Self-correcting memory.** The agent tracks every fix's outcomes per model family. When recent failures are statistically implausible given the fix's record, it updates its belief, scopes it to the cohort that fails, names the fix that worked, retains the correction to Hindsight, and says **"Belief updated"** in the briefing.

## How Hindsight memory is used

Each agent has its own bank, holding only what that role needs:

| Bank | Seeded with | Recalled for | Learns after a visit |
| --- | --- | --- | --- |
| `<prefix>-dispatcher` | Alarms with the remote action tried and whether it cleared | Is a remote fix worth trying for this code? | What finally fixed an alarm it routed |
| `<prefix>-diagnostician` | Full visit records: what was tried, what failed, root cause | Root cause, with the job ids that support it | The new visit; belief corrections |
| `<prefix>-parts` | Parts used per visit; whether a missing part forced a second trip | What to carry | The parts record of the new visit |
| `<prefix>-field` | Site profiles (gate codes, contacts) and visits | The briefing: this machine, same model elsewhere, the site | The new visit; belief corrections |

The three Hindsight operations, and where they live in the code:

| Operation | When | Code |
| --- | --- | --- |
| `retain` | After every visit, for every agent that learns from it; once per correction | `memory.py`, `mesh/runner.py: record_visit`, `beliefs.py: sync` |
| `recall` | Before every job: tag-scoped to `machine:`, `family:`, `site:`, `code:` | `agent.py: recall_context`, `mesh/roles.py` |
| `reflect` | Before every diagnosis and briefing: lessons across many visits | `agent.py`, `mesh/roles.py: Diagnostician` |

Design points that made it work:

- **Tags give three levels of recall.** `machine:M-07` (this unit), `family:daikin-vrv-iv` (same model at other sites, which is how a site with no history still gets a useful briefing), `site:S-01` (access rules).
- **Failures are first-class.** Every attempt is retained as `DID NOT FIX IT` or `FIXED IT`, so the agent can tell a technician what to skip, not only what to do.
- **Citations survive.** Hindsight rewrites memories into facts, so job ids are not in the recalled text. The `document_id` it returns is used to tag every memory (`[source J-0902, 2026-03-14]`), and the Diagnostician's evidence is discarded unless it cites an id that was actually recalled.
- **Corrections are memory too.** A belief correction is retained as its own document (updated in place when it changes), so it comes back through recall in later sessions.
- **One event loop.** The Hindsight client is async; its sync wrappers fail inside web-server threads. Every call goes through one background loop (`memory._LoopThread`). Before that fix, recall silently returned nothing and "memory on" looked identical to "memory off".

## Replay evaluation

EVAL_SECTION

## Self-correcting memory

The history contains a real drift: the compressor-contactor swap fixed Daikin VRV IV trips 9 of 9 times on units installed 2018 to 2021, then failed 4 of 4 times on units installed 2023 and later,
where the real cause was the inverter board. `backend/beliefs.py` notices this with a rule you can read in one screen:

```python
MIN_EARLIER, MIN_RATE, MIN_RUN, ALPHA = 4, 0.75, 2, 0.05

def detect(att: list[dict]) -> dict | None:       # attempts of one fix on one model family, in date order
    r = 0
    for a in reversed(att):                        # the trailing run of failures
        if a["result"] != "failed":
            break
        r += 1
    earlier, recent = att[:len(att) - r], att[len(att) - r:]
    if r < MIN_RUN or len(earlier) < MIN_EARLIER:  # a lesson needs a record to contradict
        return None
    k, n = sum(1 for a in earlier if a["result"] == "worked"), len(earlier)
    if k / n < MIN_RATE or (1 - (k + 1) / (n + 2)) ** r >= ALPHA:   # Laplace-smoothed: would r failures in a row be an accident?
        return None
    return {"earlier": earlier, "recent": recent, "k": k, "n": n, "run": r}
```

It then scopes the belief to the units that fail (installed from 2023) so older units keep the original lesson, names the fix that worked in those incidents,
retains the correction to Hindsight, and injects it into the briefing and the Diagnostician's prompt. The dashboard plots every fix's outcomes over time.
If the fix starts working again, the trailing run of failures breaks and the belief disappears.

## Run it

Requires Python 3.11+.

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows. On macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # add GROQ_API_KEY and HINDSIGHT_API_KEY (and the BAND_KEY_* values, optional)
python backend/app.py             # http://localhost:8000
```

On first start the app seeds the four Hindsight banks (allow two to three minutes for Hindsight to finish processing). With no keys at all it runs on a local
keyword memory and rule-based briefings, so the demo cannot break.

```bash
python -m pytest tests -q         # 43 tests, no network or keys needed
python scripts/run_eval.py        # the replay evaluation, about 15 minutes on real Hindsight + Groq
python scripts/extend_data.py     # regenerate the alarm history, newer units and the drift (idempotent)
```

## Failure handling

- LLM returns bad JSON or errors: retried, then a fallback model, then a deterministic briefing that still uses memory.
- Hindsight unreachable: recall errors are caught and the agent continues, and the UI shows which backend is active.
- Band unreachable or misconfigured: the run continues in-process and the room says so.
- Bad audio, silence, an unreadable file or an extraction failure: specific messages, and a type-instead fallback. Nothing is saved without confirmation.
- A missing or invented citation: dropped, never shown.

## Layout

```
backend/   app.py (API + SSE)  agent.py  memory.py  llm.py  beliefs.py  evaluation.py  voice.py  store.py
           mesh/  band.py  roles.py  runner.py  records.py
           data/  synthetic company, machines, sites, history, alarms, stock; eval_results.json
frontend/  index.html (the whole UI, no build step)
scripts/   generate_data.py  extend_data.py  run_eval.py
tests/     mesh, Band (mock server), evaluation, voice, beliefs, alarm feed
docs/      architecture.svg  BAND_SETUP.md  EVALUATION.md  VIDEO_SCRIPT.md  ARTICLE.md  LINKEDIN_POST.md  screenshots/
```

## Data

All data is synthetic: a fictional Bengaluru HVAC contractor (CoolCare Facility Services), 9 sites, 25 machines, 6 technicians, 67 visits across 43 incidents,
78 alarms with remote-fix outcomes, and parts stock. No real company, person or customer.

## Honest limits

- The evaluation is small (43 incidents) and synthetic; read the direction, not the exact percentage. See [docs/EVALUATION.md](docs/EVALUATION.md).
- The Band transport is implemented from Band's published OpenAPI schemas and tested against a mock; it needs your four agent keys for a first live run ([docs/BAND_SETUP.md](docs/BAND_SETUP.md)).
- Remote fixes in the demo are simulated: no real BMS is driven.
- Whisper mishears brand names (a spoken "Daikin" can come back as "Dakin"); the confirmation step exists for that reason.
