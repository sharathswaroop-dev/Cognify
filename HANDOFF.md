# SiteMemory: handoff for the next Claude session

Read this file and README.md first, then continue from "Next steps".

## Context
- Event: "AI Agents That Learn Using Hindsight" (Vectorize). Required: Hindsight memory + Band AI desktop.
- Judging: Innovation 30%, Hindsight memory use 25%, Technical 20%, UX 15%, Real-world impact 10%.
- Idea chosen: **SiteMemory**, an HVAC field-service technician assistant. Picked because incident-response, AP, claims and similar ideas were already built many times in earlier Hindsight projects.
- Team brief doc: https://claude.ai/artifact/Mrk5rjy7VrPj3ptquD3ENd

## Content rules (from the content guide, or disqualified)
- Never use the event-type word (the one in the brief's title) in articles, LinkedIn posts, hashtags or repo docs.
- Each member: one article (800-1500 words, public on Medium/Dev.to/Hashnode/LinkedIn Articles) and one LinkedIn post (<800 chars, repo link in post, article link as first comment, Hindsight GitHub link as a comment, tag Code.in).
- Team: one 2-5 minute video on YouTube (1080p, screen + voiceover, show retain/recall live), thumbnail via Nano Banana.
- Articles must link github.com/vectorize-io/hindsight, hindsight.vectorize.io and vectorize.io/what-is-agent-memory.
- Share the article on r/llmdevs, r/sideproject, r/aiagents or r/aimemory.

## What is built (round 1)
- `backend/app.py`: FastAPI and the static UI. Endpoints: /api/status, /api/jobs/open, /api/briefing, /api/jobs/{id}/log, /api/stats, /api/machines/{id}/history, /api/seed, /api/reset-demo.
- `backend/memory.py`: HindsightMemory (retain, retain_batch, recall with tags, reflect) and a LocalMemory fallback. Tags: machine:, site:, family:, kind:.
- `backend/agent.py`: recall at three levels (machine, model family, site), then reflect, then a Groq JSON briefing. Falls back to a rules-based briefing if the LLM fails.
- `backend/llm.py`: Groq with retries, JSON validation and a fallback model.
- `frontend/index.html`: Technician view (phone frame, memory toggle, recalled memories panel, log-visit form), Memory off vs on comparison, manager dashboard.
- `backend/data/*.json`: synthetic data (CoolCare Facility Services, Bengaluru; 9 sites, 21 machines, 59 past visits). Demo hero job J-1201, machine M-07.
- `.env` holds GROQ_API_KEY and HINDSIGHT_API_KEY (Hindsight Cloud, $5 credit; promo code expired). Never commit it.
- Tested only with the local fallback and a mocked Hindsight client. **Not yet run against real Hindsight or Groq.**

## Run
```
cd sitememory
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python backend\app.py   # http://localhost:8000
```
The first start with Hindsight keys seeds 68 records into bank `sitememory-coolcare` (async; wait 1-3 minutes).

## Next steps
1. Run against real Hindsight and Groq; fix any API mismatch (recall result fields, list_memories total, reflect tags).
2. Check that recall with tags returns the right memories for J-1201 and that the briefing is specific.
3. Band AI integration: expose SiteMemory as an agent in Band (free plan) so technicians can chat with it there.
4. Polish the demo flow; add a "learning curve" moment (log a failed visit on J-1202, re-brief).
5. Push to GitHub (repo `sitememory`), then generate content with the guide's prompts run inside the repo.
