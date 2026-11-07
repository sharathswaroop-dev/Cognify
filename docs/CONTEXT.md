# Cognify: full context from the planning conversation

Everything decided before coding. Read this, then `Problem_Statement.pdf` and `Content_Guide.pdf` in this folder, then `../HANDOFF.md` and `../README.md`.

## 1. The event (from Problem_Statement.pdf)
- Theme: "AI Agents That Learn Using Hindsight". Build an agent with persistent memory that improves from past interactions.
- Required tech: **Hindsight** (Vectorize memory system) and **Band AI desktop** (band.ai).
- Links: docs https://hindsight.vectorize.io/ · GitHub https://github.com/vectorize-io/hindsight · Cloud https://ui.hindsight.vectorize.io
- LLM: any; Groq recommended (openai/gpt-oss-120b, qwen/qwen3-32b). Handle function-calling and JSON errors.
- Avoid student-centric projects (tutors, quiz generators, group project managers). Think professional world.
- Data: realistic data matters most. Use real-sounding names, numbers and logs.
- Keep scope tight: one workflow, one persona, one value proposition.

### Judging criteria
| Criterion | Weight | Looking for |
| --- | --- | --- |
| Innovation | 30% | Fresh take on a real problem, beyond obvious chatbots |
| Use of Hindsight memory | 25% | Memory central to the value; agent clearly improves over time |
| Technical implementation | 20% | Clean, well-architected, functional, handles edge cases |
| User experience | 15% | Intuitive; demo tells a compelling story |
| Real-world impact | 10% | Genuine problem, path to adoption |

### Submission requirements
- GitHub repo with clean, documented code
- Demo video
- Live demo to judges
- Content: every team member writes an article and a social post; plus a team video
- Explanation of how Hindsight memory is used

## 2. Content rules (from Content_Guide.pdf). Breaking these means disqualification.
- **Never use the event-type word** (the one in the brief's title) in the article title or body, the social post, hashtags or repo docs. Do not frame anything as a competition entry or student project.
- Article: 800-1,500 words (the prompt asks for 1,200-2,000), first person, technical, no hype. Publish publicly on Medium, Dev.to, Hashnode, Substack or LinkedIn Articles (not Google Drive).
  - Title: about the idea or result, at most 10 words, mentions Hindsight, no buzzwords.
  - Must include: a specific opening hook, the problem in concrete terms, where and how Hindsight is integrated, at least one real code snippet, a before/after example, one honest lesson or limitation, screenshots and an architecture diagram.
  - Must link: https://github.com/vectorize-io/hindsight, https://hindsight.vectorize.io/, https://vectorize.io/what-is-agent-memory
  - Share as a Link post on r/llmdevs, r/sideproject, r/aiagents or r/aimemory.
- LinkedIn post: under 800 characters, hook in the first 2 lines (no links or hashtags there), 3-7 concrete takeaways including one before/after, 3-5 hashtags on the last line only (#AIAgents #AI #Hindsight #AgentMemory #AIMemory #LLM), no event-type or student tags. Put the GitHub repo link in the post, the article link as the first comment, and a comment linking https://github.com/vectorize-io/hindsight. Tag Code.in.
- Video: one per team, 2-5 minutes, 1080p, screen recording with voiceover (talking head optional). Structure: intro 30s, the problem without memory 30s, live demo showing retain/recall and the before/after 2-3 min, takeaway 30s. Post publicly on YouTube with a Nano Banana thumbnail.
- The content contest needs every member to submit an article and a post, plus one team video.

## 3. Why Cognify (idea selection)
- First pick was an Incident Response agent, rejected after research. At least 8 public Hindsight projects already did it (SentinelAI, RecallOps, HindsightOps, Pulse, IncidentRecall, OpsMind and others), and PagerDuty sells an SRE agent with memory. That would score badly on innovation.
- Also already done: Accounts Payable (the "Finley" invoice agent) and insurance claims (Hindsight's own ClaimsIQ cookbook demo).
- Chosen: **field service technician agent** (HVAC, elevators, generators, medical equipment). It's not on the PDF list, and no Hindsight project doing it was found.
- Business case: every repeat visit costs technician time, fuel, an SLA penalty or customer trust. Knowledge sits in job cards, WhatsApp and senior techs' heads, and leaves when they do. Buyers are service contractors, for example Indian AC/elevator service firms. Pricing idea: about Rs 4,000 ($50) per technician per month.
- Key innovation: **it learns from FAILED fixes as well as successful ones** (that is the "hindsight" idea). It warns "reset didn't work last time" before the tech repeats it.

## 4. Product (what judges see)
- Technician view (phone frame): job, then a memory briefing (likely cause, DON'T REPEAT, DO FIRST, BRING parts, site notes), a "What Hindsight recalled" panel, and a "Log this visit" form that retains to memory.
- "Memory off vs on" side-by-side view for the same job (this is the proof for the 25% memory score).
- Manager dashboard: first-time-fix rate, repeat visits, attempts that keep failing, machine history timeline.
- Band AI: technicians can ask Cognify in a Band chat (still to build).

## 5. Demo story (60-90s)
1. Problem: "Meet Ravi, a new technician (joined Oct 2026). Repeat visits cost time, fuel and angry customers."
2. J-1201, Orion Tech Park Bay 3, Daikin VRV IV M-07. Memory OFF gives generic checks.
3. Memory ON: "Reset failed on 12 Mar and 19 Aug. Contactor burnt both times (voltage dips ~190V). Carry DK-CTR-24V. Gate code 4471. Call Priya before 10am." Fixed in one visit.
4. Learning: J-1202 is a new site with no history, but the agent still warns via the same model at other sites. Log a failed attempt, re-brief, and your own visit is now in memory.
5. Close: "Every visit makes Cognify smarter. Knowledge stays when technicians leave."
Rehearse at least 3 times; the local fallback mode is a backup if the Wi-Fi fails.

## 6. Accounts and keys
- Groq key and Hindsight Cloud key are in `../.env` (never commit or print them). The Hindsight endpoint is https://api.hindsight.vectorize.io. Credit is $5; promo code MEMHACK99 had expired.
- Band AI: free plan (1 user, up to 20 remote agents, 250 chat rooms). That is enough.
- Rotate the Groq key after the event (it was shared in a chat).

## 7. Team roles (suggested, 4 people)
- Lead / backend: keys, runs backend, fixes errors
- Frontend tester: UI and demo flow
- Data person: makes the synthetic data look real
- Presenter / content: demo rehearsal, video, posts

## 8. Team brief doc
https://claude.ai/artifact/Mrk5rjy7VrPj3ptquD3ENd (the shareable explainer for teammates)
