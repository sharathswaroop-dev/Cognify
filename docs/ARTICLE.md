<!--
DRAFT FOR A TEAM MEMBER TO ADAPT. Every member publishes their own article (800-1500 words) on Medium, Dev.to, Hashnode, Substack or LinkedIn Articles
(public; not Google Drive). Change the opening, add your own role and one thing you learned, and keep every number exactly as docs/EVALUATION.md states it
(including what was NOT run). Upload docs/architecture.svg (export as PNG) and the screenshots in docs/screenshots/. Do not use the event-type word anywhere.
Then share the link on r/llmdevs, r/sideproject, r/aiagents or r/aimemory. Required links are already in the text.
-->

# Hindsight memory plus a Verifier that can say no

A technician drives forty minutes to a rooftop AC unit that keeps tripping. He resets the breaker, tops up the gas, and watches it trip again. The real cause was a burnt part that sat in the warehouse the whole time. The person who knew had fixed this unit twice and had since left the company.

I built SiteMemory so that second trip doesn't happen. It is a team of agents for field-service companies that remember every machine, site and repair, and, the part I spent the most time on, **check their own memory before they recommend anything**.

## The problem, concretely

A repeat visit costs a technician's day, fuel and sometimes a customer. The knowledge that prevents it lives in job cards, chat threads and people's heads. But a service log is not a clean database. It is full of wrong diagnoses, parts replaced on a hunch, fixes that held three weeks, and fixes that quietly stop working when a newer generation of the same unit arrives. An agent that simply remembers all of that will confidently repeat the old mistakes.

My data is a fictional Bengaluru HVAC contractor: 12 sites, 51 machines, about 230 visits in 137 incidents, 180 alarms with the remote fixes tried, parts stock. All synthetic, but written to look like a real log and to contain exactly those problems. Eight machines are held out for testing and never used for tuning.

![Architecture](architecture.svg)

## One shared bank, and what goes in it

Four agents work in a [Band](https://band.ai) room: a Dispatcher (remote fix or technician), a Diagnostician, a Parts agent, and a Verifier. They all read and write **one** [Hindsight](https://github.com/vectorize-io/hindsight) bank per company ([what agent memory is](https://vectorize.io/what-is-agent-memory), and the [docs](https://hindsight.vectorize.io/)). Records are tagged by kind and appended in date order: visits, follow-ups, alarms, sites.

Each visit stores the suspected cause, what was done, and a **verified outcome on a ladder**: suspected, fixed at visit, stable 30 days, stable 90 days. A fix that comes back within 30 days never counts as fixed. Follow-up records are retained as they fall due, so the bank learns "it held" and "it came back" as time passes. Only verified outcomes raise confidence.

Recall uses tags that must all match, so a diagnosis sees visits for this machine and its model family and never an unrelated alarm:

```python
f1 = pool.submit(case.memory.recall, q, [f"machine:{m['id']}", "kind:visit"], 5, "all")
f2 = pool.submit(case.memory.recall, q, [fam, "kind:visit"], 8, "all")
```

## The Verifier

The Diagnostician and Parts agent propose. The Verifier sees only the raw visit records, never the other agents' reasoning, runs deterministic checks and can veto. A vetoed agent revises and the Verifier checks again. For the same unit, a part is approved only if it fixed the fault on comparable units:

```python
wins = [v for v in used if any(a["result"] == "worked" for a in v["actions"])
        and lv[v["job_id"]]["level"] != "suspected" and not lv[v["job_id"]]["recurred"]]
if len(wins) >= self.min_wins or (len(wins) == 1 and not losses):
    approve(part)
else:
    veto(part, f"Used in {len(used)} visit(s) on comparable units, but it fixed the fault in {len(wins)}.")
```

## Before and after, on one alarm

The alarm: a 2024 unit, compressor overcurrent, supply voltage normal. With no memory, the dispatcher tries a remote reset, the diagnostician guesses at a dirty condenser coil, and the plan ends in a return visit. With the shared bank the dispatcher sends a technician (remote resets cleared none of the last five similar alarms). The diagnostician's first idea is the usual fix, the contactor. The Verifier vetoes it:

> *Recent evidence contradicts this lesson: "Replaced compressor contactor" fixed Daikin VRV IV faults 20 of 22 times on units installed 2018-2022, but it failed 4 of 4 times since 2026-09-18 on units installed 2023-2024. ... In those incidents the fix that worked was "Replaced inverter PCB (A2P) and updated its firmware" (4 of 4).*

It also vetoes a relay board that past visits had replaced on a hunch: *used in 4 visits on comparable units, fixed the fault in 0.* The Diagnostician revises, and says exactly how sure it is: *n=4: 3 verified, 1 not yet stable, 0 failed; verified rate 75% (95% 30-95%); weak signal.* The Verifier approves. The simulated outcome: fixed first time, against a return visit.

![The mesh and the memory receipt](screenshots/02-live-demo-mesh.png)

## Did it help? A replay with no leakage

I replayed the whole history in date order. Every incident is planned using only records dated before it, and the harness raises if a later record is present. The Verifier's one threshold is tuned on training machines only; the score is on the held-out machines. Plans are scored against what really happened, deterministically, with no LLM judge.

<!-- RESULTS-START -->
| Arm | Predicted first-time fix | Right parts | Failed fix avoided |
| --- | --- | --- | --- |
| No memory | **0% (0/13, 95% 0%-23%)** | 62% (8/13, 95% 36%-82%) | 100% (7/7, 95% 65%-100%) |
| Basic search (BM25) | **64% (7/11, 95% 35%-85%)** | 82% (9/11, 95% 52%-95%) | 100% (6/6, 95% 61%-100%) |
| Basic search + Verifier | **64% (7/11, 95% 35%-85%)** | 64% (7/11, 95% 35%-85%) | 100% (6/6, 95% 61%-100%) |

Simulated: a replay of a synthetic history, scored on 24 incidents on 8 held-out machines that were never used for tuning. Generated 2026-11-07 07:33 with basic search (BM25). Not run: Hindsight: Hindsight was not used for this run. 94 of 179 model calls came back empty (rate limits); those runs are excluded from the rates, so the intervals are wide.

On basic search, the Verifier changed predicted first-time fix from 64% to 64%.

Method, tuning and every failure: [docs/EVALUATION.md](https://github.com/sharathswaroop-dev/sitememory/blob/main/docs/EVALUATION.md).
<!-- RESULTS-END -->

## What I'd tell you before you copy this

- **My first version silently did nothing.** Recall failed in the web server's worker threads, the agent caught the error and carried on without memory, and "memory on" looked identical to "memory off". Make failure visible.
- **Family-level statistics lied.** The newer-generation failures dragged the contactor's record down for old units too. Statistics and part support have to be computed on comparable units.
- **Hindsight rewrites your text.** Job ids vanished from recalled memories. I cite visits with the `document_id` Hindsight returns, and veto any citation the records do not support.
- **Services run out.** My Hindsight credit ran out mid-project and Groq's daily token limits hit repeatedly. The app now fails over across models, falls back to a local memory with a banner, and the evaluation marks anything it could not run as "not run" instead of quietly dropping it.
- **Everything labelled simulated is an assumption**, not a measurement, and the sample is small. The intervals are in the report.

The code, the data generator and the evaluation are in the repository and everything here can be rerun: [github.com/sharathswaroop-dev/sitememory](https://github.com/sharathswaroop-dev/sitememory).
