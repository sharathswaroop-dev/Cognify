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

*Screen: the Control Room, an alarm already selected: M-91, compressor overcurrent, supply normal.*

> "This is SiteMemory. When a service technician visits a machine, what the company knows about it is scattered across job cards, chat threads and the heads of people who may have left. SiteMemory is a team of agents on one shared Hindsight memory that remembers every repair, including the ones that failed, and checks itself against the raw records."

### 2. The problem without memory (0:20 to 0:45)

*Screen: press Run both paths. Point at the left column as it fills.*

> "Here is one alarm, worked two ways with the same agents and the same model. On the left, no memory. The dispatcher tries a remote reset because nothing says it won't work. The diagnostician guesses at a condenser coil. The verifier has no records, so it passes the generic plan through. Ravi would arrive with a coil cleaner and no inverter board."

### 3. Live demo (0:45 to 2:35)

**3a. Recall, with the evidence (0:45 to 1:15).** *Right column, then the memory panel.*

> "On the right, the same agents on the shared Hindsight bank. Watch the panel on the far right: every recall, reflect and retain lights up. The dispatcher finds that remote resets cleared none of the last five overcurrent alarms, so it sends a technician. The diagnostician shows its evidence: how many attempts, how many verified, the success rate and its interval, and it says plainly when that is a weak signal."

**3b. The Verifier vetoes (1:15 to 1:50).** *Point at the red VETO bubbles.*

> "Now the part I care about. The diagnostician's first idea is the usual fix, replacing the contactor. The verifier reads only the raw visit records and vetoes it: on units installed from 2023 that fix has failed four times out of four, and the board was what worked. It also vetoes the relay board, which past visits replaced on a hunch and which never fixed anything. The agents revise, the verifier checks again and approves. Every claim links to exact past visits."

**3c. The consequence (1:50 to 2:10).** *Point at the two result cards and the comparison strip.*

> "The same alarm, simulated: with no memory it ends in a return visit, two visits and twice the cost; with memory it is fixed first time. Everything labelled simulated is a replay of a synthetic history, not a field result."

**3d. Retain: it learns (2:10 to 2:35).** *Click "Send the briefing to the technician's phone", tap the mic, speak a short report, confirm.*

> "On the phone, the briefing. I log the visit by voice: Whisper transcribes it, the model structures it, and nothing is saved until I confirm. Failures are retained as carefully as fixes, and the memory panel lights up on the retain. Next time, this visit is part of what every agent remembers."

### 4. Takeaway (2:35 to 3:00)

*Screen: Dashboard, "Does memory actually help?", then the watchlist.*

> "And we measured it, without letting the future leak in. We replayed the whole history in date order, tuned on training machines, and scored the machines we held out: predicted first-time fix [read from EVALUATION.md: no memory X%, best arm Y%, with its interval]. It is a small synthetic dataset, so the caveats are written next to the numbers, including what we could not run. Every visit makes SiteMemory smarter, and the knowledge stays when a technician leaves."

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
