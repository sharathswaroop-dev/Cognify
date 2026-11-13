# Cognify Field

The phone app for Cognify: one app, two roles (Reporter and Technician). A thin Flutter client over the same backend the website uses (no logic of its own).

- **Jobs**: today's open jobs. Open one and press **Brief me**: the four agents (Dispatcher, Diagnostician, Parts, Verifier) run in a Band room, their hand-offs stream live, and a briefing appears (what to do first, what failed before and must not be repeated, what to bring, site notes).
- **Log this visit**: type it or speak it (the microphone records, the backend transcribes and structures it); what you save is retained to the shared memory and changes the next briefing.
- **Ask**: a conversation with the company memory. It greets, asks what is wrong when a problem is vague, answers from past repairs, and learns from a correction typed in plain words.
- **Learn**: watch the memory learn, incident by incident, using only the records before each one.

## Run it

1. On the laptop: `HOST=0.0.0.0 python backend/app.py` (PowerShell: `$env:HOST="0.0.0.0"; python backend/app.py`). Allow Python through the firewall if asked.
2. Install `Cognify-Field.apk` on an Android phone on the same Wi-Fi (or build it: `cd mobile && flutter build apk --release`).
3. Open the app, enter `http://<laptop-ip>:8000`, tap **Join the demo company**.

On the Android emulator the laptop is `http://10.0.2.2:8000`.
