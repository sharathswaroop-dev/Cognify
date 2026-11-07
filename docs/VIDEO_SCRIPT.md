# Team video script (3 minutes)

One video per team, 2 to 5 minutes, 1080p screen capture with voiceover (a talking head is optional). Post it publicly on YouTube with a custom thumbnail.
Structure from the content guide: intro, the problem without memory, a live demo that shows retain and recall and the before/after, a takeaway.
Rehearse the whole flow three times. Read every number from `docs/EVALUATION.md` on the day you record; do not quote one from memory.

## Before you record

- `python backend/app.py` on real Hindsight and Groq keys, browser at 1920x1080, zoom 100%, no banner showing (if the banner says Hindsight is unavailable, fix that first).
- Fresh state: delete `backend/data/logged_visits.json`, restart, wait until the header chip shows the memory count.
- Run `python scripts/run_eval.py` once so the dashboard shows real numbers.
- Do-not-disturb on, headset microphone, other tabs closed. Keep `docs/screenshots/` open as a fallback if the network drops.
- Say "held-out", "simulated" and "weak signal" exactly as the UI shows them. Never use the word that names the event type.

## Script

### 1. Intro (0:00 to 0:20)

*Screen: the Home page, slowly scrolling past the headline and the "Same alarm. Same people. One had the notebook." section.*

> "A technician drives forty minutes to a rooftop unit, resets it, tops up the gas, and it trips again. The part was in the warehouse, and the person who knew has left. SiteMemory is a crew of four agents on one shared Hindsight memory that remembers every repair, including the ones that failed, and checks itself against the raw job cards."

### 2. The live demo, act by act (0:20 to 2:50)

*Screen: Live demo page. Say "act" and the number each time you scroll to the next one; the page is built in these six acts.*

**Act 1 and 2, input and the mesh (0:20 to 1:00).** *Pick the M-91 compressor alarm, leave the drill on "Everything up", press "Send the alarm into the mesh". Keep the mesh diagram on screen.*

> "An alarm comes in from a machine. Watch the mesh. The Dispatcher decides remote fix or technician from the alarm log: remote resets cleared none of the last five, so it sends a technician. The Diagnostician recalls this machine, its model family and the site. The Parts agent decides what goes in the van. Each dot you see is a hand-off in the Band room, and each coloured line to the bank is a real Hindsight recall, reflect or retain, which the receipt on the right records."

**Act 3, with and without, and the veto (1:00 to 1:40).** *Scroll to the two paths. Point at the red VETO stamp.*

> "On the left the same agents with no records: reset the breaker, clean the coil, and it comes back. On the right, the shared memory. The Diagnostician's first idea is the usual fix, the contactor. The Verifier reads only the raw visit records and vetoes it: on units from 2023 that fix failed four times out of four, and the inverter board is what worked. The agents revise, it checks again and approves. The simulated result: fixed first time, against a return visit."

**Act 4, when something breaks (1:40 to 2:05).** *Scroll up, choose the "Hindsight down" drill, send the alarm again. Point at the chip that turns yellow and the log line.*

> "Now I switch Hindsight off for this run. The agents notice, fall back to a local memory kept in step, say so on screen, and still finish the job. The same goes for Band, where the agents hand off in-process, and for the main model, where the chain moves to the next one. If every model is down, the Diagnostician and Parts agent fall back to ranking by the verified record, and the Verifier still checks the result."

**Act 5, it learns (2:05 to 2:30).** *Click "Log: the recommended fix failed", show the retained record and the counts, then "Brief the same alarm again".*

> "Now the fix does not hold on site. That visit is retained to the bank, the failed count goes up, and I ask again: the briefing changes with the evidence. Failures are remembered as carefully as fixes. By voice, the technician does the same from the phone: Whisper, structure, confirm, retain."

**Act 6, how accurate (2:30 to 2:50).** *Scroll to the bars and the learning curve.*

> "And we measured it, without letting the future leak in. We replayed the whole history in date order, tuned on training machines and scored the machines we held out. [Read the exact numbers from EVALUATION.md here, including what could not be run.] It is a small synthetic dataset, so the caveats are written next to the numbers."

### 3. Takeaway (2:50 to 3:00)

*Screen: the Home page call to action.*

> "Every visit makes the next one better, and the knowledge stays when a technician leaves."

## Do not

- Quote a number you did not read from `docs/EVALUATION.md` that day, or call a simulated result a measurement.
- Show a run where the banner says Hindsight is unavailable and call it Hindsight recall.
- Cut away from a slow step. A run takes a while on real services; narrate it.

## Thumbnail (Nano Banana prompt)

> Clean dark graphite background with one acid-lime accent. Two phone screens side by side: left shows a repair plan with a red "VETO" stamp, right shows a lime "Replace inverter board" plan with a green check. Large bold title "It checks its own memory". No people, no logos, no gradients, flat design.

## Publishing checklist

- [ ] 1080p, 2 to 5 minutes
- [ ] Public on YouTube, custom thumbnail
- [ ] Title mentions Hindsight, describes the idea, no buzzwords
- [ ] Description links the repo, https://github.com/vectorize-io/hindsight and https://hindsight.vectorize.io/
- [ ] Link added to every team member's article and post
