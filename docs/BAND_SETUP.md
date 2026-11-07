# Running the agents on Band

Cognify's four agents (Dispatcher, Diagnostician, Parts agent, Verifier) hand work to each other in a
[Band](https://band.ai) room. Each handoff is a real Band message that mentions the receiving agent; the receiver reads
it back from Band, acknowledges it, and only then acts on it. Without Band credentials the same four agents run
in-process, so nothing about the demo depends on Band being reachable.

## Status, stated plainly

The Band transport (`backend/mesh/band.py`) is written against Band's published OpenAPI schemas
(`https://docs.band.ai/openapi.json`) and tested against a mock Band server in `tests/test_band.py`: room creation,
participants, mentions, `messages/next`, `processing`/`processed`, and the fallback when any call fails.
It has **not** been run against the live Band service, because that needs your four agent API keys. The first live
run is the setup below; if a field name differs from the spec, the fallback keeps the run going and the room shows
"Band unreachable (...)" with the reason.

## Setup (about five minutes)

1. Open the Band web app (app.band.ai), go to **Agents**, click **Connect remote agent**.
2. Create four agents, one per role. Names are 3 to 24 letters, numbers or spaces; descriptions need at least 10 characters:

   | Name | Description |
   | --- | --- |
   | `SM Dispatcher` | Decides remote fix or technician for a machine alarm |
   | `SM Diagnostician` | Finds the root cause of a fault and cites past visits |
   | `SM Parts` | Decides which parts to carry and checks stock |
   | `SM Verifier` | Checks every claim against the raw visit records and can veto |

3. For each agent, copy the **API Key** from the success dialog. It is shown once; **Regenerate API key** in the
   agent's menu issues a new one.
4. Put the keys in `.env` (never commit this file):

   ```
   BAND_KEY_DISPATCHER=...
   BAND_KEY_DIAGNOSTICIAN=...
   BAND_KEY_PARTS=...
   BAND_KEY_VERIFIER=...
   ```

   `BAND_BASE_URL` defaults to `https://app.band.ai/api/v1`.
5. Restart the app. The header chip shows `Band: connected`.
6. Run an alarm on the Live demo page. The with-memory path creates a room titled `Cognify <alarm> <machine> <code>`, adds the four agents, and
   posts every handoff. Open **Rooms** in the Band app to watch the same conversation. In Cognify, handoff bubbles
   are tagged `via Band` when delivery through Band succeeded and `in-process` when it fell back.

All four keys are required. With fewer, the app runs in-process and says so.

## What it calls

| Purpose | Call |
| --- | --- |
| Who am I (id, handle) | `GET /agent/me` |
| New room per run | `POST /agent/chats` `{chat:{title}}` |
| Add the other three agents | `POST /agent/chats/{id}/participants` `{participant:{participant_id, role}}` |
| Hand off | `POST /agent/chats/{id}/messages` `{message:{content, mentions:[{id,handle,name}]}}` using the sender's own key |
| Receive | `GET /agent/chats/{id}/messages/next` using the receiver's key |
| Acknowledge | `POST /agent/chats/{id}/messages/{mid}/processing` then `/processed` |

Authentication is the `X-API-Key` header, one key per agent. The structured payload travels inside the message as a
fenced `json` block under a human-readable summary, so the room reads naturally and the receiving agent still gets
exact data.

## Troubleshooting

- **401 Unauthorized**: copy the key again or regenerate it; the old key stops working.
- **No handoff arrives**: a Band message only reaches an agent that is mentioned and is a participant in the room.
- **`limit_reached` when creating a room**: your Band plan's room quota is used up. The run continues in-process.
- **Anything else**: the run log in the Agent mesh tab says what failed and that it continued in-process.
