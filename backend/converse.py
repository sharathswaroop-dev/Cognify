"""The conversation layer: what kind of message is this, and what would a good colleague say back?

Plain rules on purpose. It has to work with no language model, it has to be instant, and a wrong guess is cheap because the reply always says what it did.
The company memory is only asked when there is a real question about equipment; greetings, thanks, a vague "I have a problem", a correction or something
worth remembering are each handled the way a person would.
"""
from __future__ import annotations

import random
import re

import chatintent

MACHINE = re.compile(r"\bM-\d{1,3}\b", re.I)

_THANKS = re.compile(r"^\s*(thanks|thank you|thank u|thx|ty|cheers|much appreciated|appreciate (it|that)|great,? thanks|perfect,? thanks|awesome,? thanks)\b", re.I)
_GREET = re.compile(r"^\s*(hi+|hello+|hey+|yo|howdy|hola|namaste|good (morning|afternoon|evening)|greetings)\b[\s!.,]*(there|team|cognify|everyone)?[\s!.]*$", re.I)
_BYE = re.compile(r"^\s*(bye|goodbye|see you|see ya|good night|talk later|catch you later|that'?s all|that is all)\b", re.I)
_HOW = re.compile(r"^\s*(how are you|how r u|how'?s it going|how do you do|what'?s up|sup|how have you been)\b", re.I)
_ABOUT = re.compile(r"^\s*(who are you|what are you|what can you do|what do you do|how do you work|how does this work|help|what is this|introduce yourself)\W*$", re.I)
_OKAY = re.compile(r"^\s*(ok(ay)?|cool|nice|great|got it|alright|fine|sure|good|understood|makes sense|i see)\W*$", re.I)

_VAGUE = re.compile(r"(problem|issue|trouble|broken|broke|not working|doesn'?t work|isn'?t working|something('s| is| has) (wrong|off)|need (some )?help|help me|can you help|"
                    r"stuck|failing|failed|acting up|misbehaving|faulty)", re.I)
_SPECIFIC = re.compile(r"(\bM-\d{1,3}\b|\b[A-Z]\d{1,2}\b error|\berror (code )?[A-Z]?\d|\balarm\b|\bcode\b|trip|leak|noise|noisy|vibrat|not cooling|warm air|"
                       r"high (head )?pressure|low pressure|compressor|chiller|vrv|split|ahu|cassette|ductable|condenser|inverter|contactor|fan|drain|refrigerant|"
                       r"overcurrent|overheat|frozen|ice|smell|tripping|communication|offline)", re.I)
_LIVE = re.compile(r"\b(my|our|the|this|that)\b.*\b(is|are|keeps?|has|have|won'?t|isn'?t|not|started)\b", re.I)

_CORRECT = re.compile(r"^\s*(no[,.!]?\s|nope\b|that'?s (not|wrong|incorrect)|that is (not|wrong|incorrect)|wrong\b|incorrect\b|not (right|correct|true)\b|"
                      r"actually\b|it was actually|it'?s actually|you'?re wrong|you are wrong|that'?s not what happened|not quite)", re.I)
_CORRECT_ANY = re.compile(r"(the real cause (was|is)|was actually|should (have )?(been|be)|it was not|it wasn'?t|that fix (did not|didn'?t) work|didn'?t fix it|did not fix it)", re.I)

HELLOS = ["Hi! What's going on with your equipment today?", "Hello! Tell me what's happening, or ask what the team has learned before.",
          "Hey there. What can I look up for you?"]
WELCOMES = ["You're welcome. Anything else you want to check?", "Happy to help. I'll be here if something else comes up.",
            "Anytime. Tell me if the fix works out and I'll remember it for the next person."]
BYES = ["Take care. If the fix works or fails, tell me and I'll remember it.", "Goodbye. Come back any time something trips."]
HOWS = ["Doing well, thanks for asking. What are we looking at today?", "All good here. What's the problem you're working on?"]
OKS = ["Got it. Anything else?", "Okay. Tell me if you want me to dig into anything."]
ABOUT = ("I'm Cognify. I remember every repair your team has done, including the ones that failed, and I check my own advice against the raw records. "
         "Tell me a symptom or a machine id and I'll tell you what has worked before and how sure I am. If you fixed something, tell me and I'll remember it for the next person.")
CLARIFY = ["Sorry to hear that. What is it doing, and which machine or site? An alarm code helps too.",
           "Let's sort it out. Which unit is it, and what are you seeing (an alarm code, a noise, no cooling, a leak)?",
           "I can help. Tell me the machine id if you have it, and what it's doing right now."]
CHIPS = ["It's tripping on an alarm", "It isn't cooling", "There's a water leak", "It's making a strange noise"]
ASK_FIX = ["Thanks for flagging that. What was the right answer? Tell me what actually fixed it and I'll remember it.",
           "Good catch. What actually happened? Give me the real cause or the fix that worked and I'll keep it."]


def _pick(options: list[str]) -> str:
    return random.choice(options)


def machine_in(text: str) -> str | None:
    m = MACHINE.search(text)
    return m.group(0).upper() if m else None


def history_machine(history: list[dict]) -> str | None:
    for h in reversed(history):
        if h.get("role") == "user":
            mid = machine_in(h.get("content", ""))
            if mid:
                return mid
    return None


def last_question(history: list[dict]) -> str | None:
    """The person's most recent real question, so a short follow-up ('and for older units?') or a correction knows what it refers to."""
    for h in reversed(history):
        if h.get("role") == "user" and h.get("kind", "answer") in ("answer", "clarify", None) and len(h.get("content", "").split()) >= 3:
            return h["content"]
    return None


def last_assistant(history: list[dict]) -> dict | None:
    for h in reversed(history):
        if h.get("role") == "assistant":
            return h
    return None


def plan(message: str, history: list[dict] | None = None) -> dict:
    """{"act": ..., "reply": text for acts that need no memory lookup, "machine": id or None, "query": the question for the memory}"""
    history = [h for h in (history or []) if isinstance(h, dict)][-10:]
    m = " ".join(message.strip().split())
    low = m.lower()
    machine = machine_in(m) or history_machine(history)
    prev = last_assistant(history)

    # the person is answering "what was the right answer?"
    if prev and prev.get("kind") == "correct_ask" and len(m.split()) >= 3:
        return {"act": "correct", "machine": machine, "correction": m, "about": last_question(history)}
    if _THANKS.match(m):
        return {"act": "thanks", "reply": _pick(WELCOMES)}
    if _GREET.match(m):
        return {"act": "greet", "reply": _pick(HELLOS)}
    if _BYE.match(m):
        return {"act": "bye", "reply": _pick(BYES)}
    if _HOW.match(m):
        return {"act": "smalltalk", "reply": _pick(HOWS)}
    if _ABOUT.match(m):
        return {"act": "about", "reply": ABOUT}
    if _OKAY.match(m):
        return {"act": "smalltalk", "reply": _pick(OKS)}
    # a correction of the last answer
    if prev and prev.get("role") == "assistant" and prev.get("kind") in ("answer", "chat") and (_CORRECT.match(m) or _CORRECT_ANY.search(m)):
        body = re.sub(_CORRECT, "", m).strip(" ,.-") if _CORRECT.match(m) else m
        if len(body.split()) >= 3:
            return {"act": "correct", "machine": machine, "correction": m, "about": last_question(history)}
        return {"act": "correct_ask", "reply": _pick(ASK_FIX)}
    # something the person wants remembered
    if chatintent.intent(m) == "share" and not m.endswith("?"):
        return {"act": "share", "machine": machine}
    # a problem with no detail: ask, like a person would
    words = len(m.split())
    if _VAGUE.search(m) and not _SPECIFIC.search(m) and not machine_in(m) and words <= 12:
        return {"act": "clarify", "reply": _pick(CLARIFY), "chips": CHIPS}
    # a real question: ask the memory, with the earlier question folded in when this is a short follow-up
    query = m
    if words < 6 and (q := last_question(history)) and q.lower() != low:
        query = f"{q} {m}"
    needs_unit = bool(_LIVE.search(m)) and _SPECIFIC.search(m) is not None and not machine and not m.endswith("?")
    return {"act": "answer", "machine": machine, "query": query, "ask_unit": needs_unit}


_MD = re.compile(r"(\*\*|__|`{1,3}|^#{1,6}\s*|^\s*[-*•]\s+|\|)", re.M)


def plain(text: str, limit: int = 900) -> str:
    """Chat-sized plain text: no markdown headings, bullets or tables, cut at a sentence."""
    t = _MD.sub("", text or "")
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]+", " ", t).strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[:end + 1] if end > limit * 0.5 else cut.rstrip() + "…")


HUMANIZE_SYS = ("You are Cognify, talking to a field technician like a helpful senior colleague. Rewrite the answer so it is short, warm and plain: under 90 words, "
                "no headings, no bullet points, no tables, no markdown. Keep every fact, machine id, date and number exactly as given and keep the [n] source markers. "
                "Lead with what matters most, say what failed before as well as what worked, and say how sure the records make us. Never add facts.")


def humanize(answer: str, llm) -> str:
    """The memory writes thorough answers; a chat reply should read like a colleague. Model rewrite when one is reachable, plain-text cut otherwise."""
    if not answer:
        return answer
    heavy = len(answer) > 520 or bool(_MD.search(answer))
    if heavy and llm is not None and getattr(llm, "available", False):
        out = llm.text_chat(HUMANIZE_SYS, answer[:3000], max_tokens=260)
        if out and len(out) > 20:
            return plain(out, 700)
    return plain(answer, 700)


def follow_up(machine: str | None, ask_unit: bool, found: bool) -> str:
    if ask_unit and not machine:
        return "\n\nWhich unit is it? Give me the machine id (for example M-22) and I'll check its own history and tell you what to try first."
    if machine and found:
        return f"\n\nWant me to run the four agents on {machine} and brief the technician?"
    return ""
