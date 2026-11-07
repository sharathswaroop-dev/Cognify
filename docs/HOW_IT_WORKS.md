# How Cognify answers: without and with memory

The same question takes two real paths through the code. This page is generated from the same data as the *How it works* page of the app (`/how-it-works#steps`), where both paths can also be run live.

## Memory OFF: a normal AI model

1. **Question arrives.** You type a question. The browser sends it with your signed token to the server, which checks the token and finds your company. (`app.py chat() · workspaces.py`)
2. **Query processing.** The message is sorted into a question, something to remember, or small talk. Small talk gets a short friendly reply and stops here. (`chatintent.py`)
3. **No memory is searched.** Nothing is sent to Hindsight. The model never sees your incidents, documents, notes or corrections. (`memory switched off`)
4. **The model gets only the question.** Groq receives the question and one rule: you have no access to this company's records, so never invent incidents, machines, dates or people. (`llm.py text_chat()`)
5. **General knowledge answers.** The model answers from what it learned in training. If one model is rate-limited the chain moves to the next (gpt-oss-120b → gpt-oss-20b → qwen). (`Groq`)
6. **A plain, uncited reply.** You get a sensible but generic answer, labelled normal AI response (in the chat: General guidance, not from your memory). It cites nothing and nothing is learned from it. It cannot know what failed on this fleet before. (`app.py compare()`)

## Memory ON: the company's own experience

1. **Question arrives, company selected.** Same token check, then your company's own Hindsight bank is chosen. Every company has a separate bank, so knowledge never crosses over. (`workspaces.py ws_memory()`)
2. **Query processing.** Intent is read, machine ids such as M-07 are pulled out, and a short follow-up like "and the parts?" is joined to your previous question so it still makes sense. (`chatintent.py`)
3. **Recall: search the memory store.** The question goes out to the store. Hindsight returns the best-matching records (up to 8), each with reference, date and tags: visits, alarms, colleague notes, document sections, corrections. If something was only just saved and Hindsight is still ingesting it, a real keyword match from the local copy fills the gap and is flagged. (`memory.py recall()`)
4. **Reflect: reason over what was found.** Hindsight reasons across the records and drafts an answer (the Thinking option uses a larger budget). If it says "nothing" although records were recalled, that is not trusted and the answer is written from the records instead. (`memory.py reflect()`)
5. **Context builder.** The top records are numbered [1], [2]…, trimmed, with any colleague correction first. The model is told: use only these, cite them, say what failed and what worked, and answer NO_MATCH if none relate. (`app.py _ask() · GROUND_SYS`)
6. **Groq writes a grounded answer.** Because the records are in the prompt, the answer can say things no generic model knows, such as "the relay board was replaced in 5 visits and fixed none; the contactor fixed 20", with citations. (`llm.py`)
7. **Evidence label.** Each record has a type: verified repair, note, document, correction or background. The answer is labelled Well supported (two or more proven repairs) or Partly supported (notes, documents or one repair). Weak support shows no label rather than a confident-looking one. (`provenance.py`)
8. **Reply with receipts.** The answer comes with the records it used (expand "records retrieved") and its label. A colleague's correction, if any, is shown first. (`app.py _ask()`)
9. **The loop closes.** A thumbs-down with the right answer is retained as a correction. "Remember …", uploaded files and logged visits are retained too, so the next answer can use them. (`app.py feedback() · retain()`)

## Side by side

| | Memory OFF | Memory ON |
| --- | --- | --- |
| Where the knowledge comes from | The model's training only | The company's own incidents, notes, documents and corrections, plus the model |
| Knows this machine's history | No | Yes: recalls visits on this machine, same model and same site |
| Knows what already failed | No. It may suggest a fix that never worked here | Yes. It lists failed attempts so they are not repeated |
| Shows its sources | No | Yes: every answer lists the records it used, with date and reference |
| Says how well supported it is | No | Yes: Well supported / Partly supported from the type of records |
| Uploaded PDF, files and photos | Cannot see them | Read, retained and analysed; later questions can cite them |
| Learns from feedback | No | Yes: corrections are retained and shown first next time |
| When it has nothing | Answers anyway, with no warning | Says nothing was found, then gives clearly labelled general guidance |
| Speed | About a second | A few seconds more, because it searches and reasons first |
| Risk | A confident but generic answer | Depends on what was written down; weak support is shown, not hidden |

## When you upload a file

1. **Choose a file.** PDF, text, markdown, csv, json or log. For a photo you write one sentence on what it shows, because the memory learns the description. (`index.html uploadFiles()`)
2. **Read it.** Text is extracted (PDFs with pypdf). A scanned PDF with no text is refused with a clear message instead of storing nothing. (`documents.py extract()`)
3. **Cut it into sections.** Paragraph-aware pieces of about 1,200 characters with a little overlap, up to 60 per file, so a long manual is searchable by section. (`documents.py chunks()`)
4. **Retain every section.** Each section is saved with the file name, "section 2 of 5", the author and the date, so an answer can point back to it. (`records.py document_record() · memory.py retain()`)
5. **Analyse straight away.** A summary request is sent automatically: recall finds the new sections, the context builder hands them to Groq, and you get key points, what failed, what worked and what to check first. (`app.py chat() · _ask()`)
6. **It stays in the Library.** The file appears in the Library and every later question can cite it, for you and for colleagues. (`workspaces.py library()`)

## A real example

Question: *Why does a Daikin VRV unit keep tripping with an E3 error?*

- **Memory OFF** answers with a generic list: low refrigerant charge, dirty filters, a faulty pressure sensor, compressor overload, and a reset-and-clean checklist. Reasonable, but it does not know this fleet.
- **Memory ON** answers that the compressor contactor is the most common cause here (scorched coil, pitted contacts), that low supply voltage under about 200 V triggers the trip, to measure the supply under load before touching the compressor, and not to replace the compressor relay board first, because it did not fix the fault in any recorded visit. It cites the records it used.

## What happens for an alarm (the agent mesh)

An alarm starts the same memory path with more actors: the Dispatcher routes it, the Diagnostician recalls and reflects, the Parts agent checks past fixes and stock, and the Verifier reads the raw records and can veto a diagnosis (up to three rounds) before the technician briefing is written.

When recent evidence contradicts an old lesson, the Verifier says so. On a newer Daikin unit it vetoed the contactor fix because that fix had worked 20 of 22 times on older units but failed 4 of 4 times since 2026-09-18 on units installed from 2023. The plan was revised to the inverter PCB and the briefing followed the revision.
