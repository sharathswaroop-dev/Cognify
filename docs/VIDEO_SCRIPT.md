# Team video script (target 4 minutes)

One video per team, 2 to 5 minutes, recorded at 1080p as a screen capture with voiceover (a talking head is optional).
Post it publicly on YouTube with a thumbnail. Rehearse the whole flow three times first; keep the app in the
state described under "Before you record".

## Before you record

- `python backend/app.py` running on real Hindsight and Groq keys, browser at 1920x1080, zoom 100%.
- Fresh demo state: delete `backend/data/logged_visits.json`, restart, wait two minutes for Hindsight to finish processing.
- Run the replay evaluation once (`python scripts/run_eval.py`) so the dashboard shows real numbers.
- Close other tabs. Turn on do-not-disturb. Use a headset microphone.
- Have `docs/screenshots/` open as a fallback if the network drops.

## Structure

### 1. Intro (0:00 to 0:30)

*Screen: the app's technician view, queue visible.*

> "This is SiteMemory. When a service technician visits a machine, the company's knowledge about that machine is
> scattered across job cards, chat threads and the heads of people who may have left. SiteMemory gives every
> technician the memory of the best engineer in the company, before they leave the depot. It is built on Hindsight
> agent memory. In the next few minutes I'll show you what changes when an agent can remember."

### 2. The problem without memory (0:30 to 1:00)

*Screen: **Memory off / on** tab. Pick J-1201 and press Run both. Leave the divider fully to the left.*

> "Here's a real-looking job: an AC unit on the roof at a tech park, not cooling, tripping. This is the same agent
> and the same model, with memory switched off. It gives sensible but generic advice: reset the unit, check the
> pressures, bring a multimeter. That is what a new technician would do. And the history says it will fail: this
> unit has been reset and topped up before, and neither helped."

### 3. Live demo (1:00 to 3:30)

**3a. Recall: the same job with memory (1:00 to 1:40).** *Drag the divider right.*

> "Now the same job with Hindsight memory. Recalled from this unit's own history: reset failed twice, the
> compressor contactor was the real cause both times, supply voltage dips to about 190 volts. It tells the
> technician to skip the reset and the top-up, carry the contactor, and call the facility manager before ten. Those
> three tiles underneath are the difference: zero memories behind the answer, versus six."

**3b. Retain: the agent learns (1:40 to 2:20).** *Technician tab, J-1202. Tap the mic, say a short failed-visit report.*

> "The next job is a newer unit at a site we've never visited. I'll log the visit by voice."
> *(speak)* "I replaced the compressor contactor and the unit still tripped. Supply voltage was normal. I'll come back with a thermal camera."
> "Whisper transcribes it, the model turns it into a structured log, and nothing is saved until I confirm. Failures
> are retained as carefully as fixes. That is the idea behind Hindsight: the agent learns from what didn't work."

**3c. Self-correcting memory (2:20 to 2:50).** *Show the amber "Belief updated" card in the briefing, then Dashboard, "How each fix performs over time".*

> "Look at this card. Across nine visits the contactor fixed these units every time. But on units installed from
> 2023 it failed four times in a row. The agent noticed, scoped the correction to the newer units, named the fix
> that did work, the inverter board, and retained that correction to Hindsight. On the older unit it still says
> contactor. That's memory that corrects itself instead of going stale."

**3d. Four agents in a Band room (2:50 to 3:30).** *Agent mesh tab. Fire "M-91 compressor overcurrent".*

> "In production the first thing that happens is a machine alarm. Four agents, each with its own memory bank, pass
> it along in a Band room. The dispatcher checks which remote fixes have ever worked for this code. Zero of two, so
> it sends a technician. The diagnostician cites the actual past visits. The parts agent notices the replacement
> board isn't on the van. The field assistant writes the briefing. Every message shows which memories the agent used."

### 4. Takeaway (3:30 to 4:00)

*Screen: Dashboard, "Does memory actually help?" panel.*

> "And we measured it. We replayed the whole service history in date order, briefing every incident using only what
> was known before that day, and scored the briefings against what actually happened. [Read the real numbers from
> docs/EVALUATION.md.] It's a small synthetic dataset, so the direction matters more than the exact percentage,
> and the caveats are written down next to the numbers. Every visit makes SiteMemory smarter, and the knowledge
> stays when a technician leaves."

## Do not

- Say or show the word that names the event type, in the video, title, description or tags.
- Quote a number you didn't read from `docs/EVALUATION.md` that day.
- Cut away from a slow step. The recall takes a few seconds; narrate it.

## Thumbnail (Nano Banana prompt)

> A clean dark graphite background with one acid-lime accent. A phone showing a repair briefing with a struck-through
> red line through the words "Reset breaker" and a lime "Carry DK-CTR-24V" tag. Large bold title "It remembers every repair".
> No people, no logos, no gradients, flat design.

## Publishing checklist

- [ ] 1080p, 2 to 5 minutes
- [ ] Public on YouTube, custom thumbnail
- [ ] Title mentions Hindsight, describes the idea, no buzzwords
- [ ] Description links the repo, https://github.com/vectorize-io/hindsight and https://hindsight.vectorize.io/
- [ ] Link added to every team member's article and post
