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

## Script (about 2.5 minutes, four scenes: the page follows the same order)

Click the numbered steps at the top of the page (Intro, Problem, Demo, Wrap-up), or the big buttons. Type your name into "Hi, I'm ___" before you start.

### 1. Intro (0:00 to 0:30)

*Screen: Intro scene. The animated diagram: four agents around one shared memory.*

> "Hi, I'm [name]. This is SiteMemory: a crew of four AI agents for HVAC field service. They share one Hindsight memory of every repair, including the ones that failed, and a Verifier checks them before a technician drives out. I built it because the person who knew how to fix a machine has usually left."

### 2. The problem (0:30 to 1:00)

*Screen: Problem scene. Press "Run it with no memory".*

> "Same alarm, same agents, but no memory. It tries a remote reset, checks the wrong thing, and sends a plan that ends in a return visit: two visits, five hundred dollars, two days of downtime. That is the mistake a technician who remembered would not make."

### 3. The demo (1:00 to 2:00)

*Screen: Demo scene. Press "Send the alarm into the mesh". Keep the graph and the memory receipt on screen.*

> "Now the same alarm, with memory. Watch the graph: the Dispatcher searches past alarms, the Diagnostician searches this machine and its model family, and every search shows up live on the right as a recall. [Click the Diagnostician.] This is how it searched: the question, the tags that must all match, and the visits that came back. [If a veto happened:] The Verifier read the raw job records and said no to the usual fix, because on newer units it failed four times out of four; the agent searched again and revised. [Scroll to the correction trail.] Now the fix fails on site. [Click 'Log: the recommended fix failed'.] That visit is retained: attempts go up, the failed count goes from zero to one. [Click 'Brief the same alarm again'.] Same alarm, and the briefing has changed, because the memory has."

Optional, 10 seconds: choose **Break something first: Hindsight**, send the alarm again, and point at the yellow backup line: it falls back to local memory and still solves it.

### 4. Wrap-up (2:00 to 2:30)

*Screen: Wrap-up scene.*

> "The takeaway: memory is not enough. An agent also has to find out it was wrong. What surprised me: remembering more made it worse until something checked it. [Read the numbers shown, exactly as on screen, including 'simulated' and anything marked 'not run'.]"

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
