"""Decide what a chat message is: a question for the company memory, or something the person is telling it to remember.

Plain rules, on purpose: it has to work with no language model, and a wrong guess is cheap because the reply always says which one it did."""
from __future__ import annotations

import re

_Q_START = ("what", "how", "why", "which", "when", "where", "who", "can ", "could ", "should ", "would ", "does ", "do ", "did ", "is ", "are ", "was ", "were ",
            "tell me", "explain", "show me", "give me", "any ", "has ", "have ", "list ",
            "summarize", "summarise", "write ", "draft ", "analyse", "analyze", "brief ", "check ", "find ", "compare", "create ", "prepare", "describe", "outline",
            "review", "suggest", "recommend", "diagnose", "solve", "fix ", "help ", "translate", "rewrite")
_SHARE_START = ("remember", "note that", "note:", "note ", "for the record", "fyi", "tip:", "tip ", "lesson", "learned", "i fixed", "i replaced", "i found", "i learned", "we fixed",
                "we replaced", "we found", "what worked", "this worked", "that worked", "it worked", "didn't work", "did not work", "never ", "always ", "make sure", "watch out", "save this")
_SHARE_ANYWHERE = ("i fixed", "i replaced", "we fixed", "we replaced", "what worked", "it worked", "did not work", "didn't work", "failed every time", "the real cause", "root cause was")
MACHINE = re.compile(r"\bM-\d{1,3}\b", re.I)


def intent(message: str) -> str:
    """'ask' or 'share'. A question mark always means ask."""
    m = " ".join(message.strip().lower().split())
    if not m:
        return "ask"
    if m.endswith("?"):
        return "ask"
    if m.startswith(_SHARE_START):
        return "share"
    if m.startswith(_Q_START):
        return "ask"
    if any(c in m for c in _SHARE_ANYWHERE):
        return "share"
    return "share" if len(m.split()) >= 14 else "ask"


def machine_in(message: str) -> str | None:
    m = MACHINE.search(message)
    return m.group(0).upper() if m else None


def strip_cue(message: str) -> str:
    """'Remember that the key is at the desk' -> 'the key is at the desk'; anything else is kept as written."""
    return re.sub(r"^\s*(remember( that)?|note( that)?:?|for the record,?|fyi:?|tip:|save this:?)\s*", "", message, flags=re.I).strip() or message.strip()
