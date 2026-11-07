"""Memory wrappers that report every operation, so the UI's memory panel can light up on each recall, reflect and retain,
and a 'no memory' stand-in for the baseline path."""
from __future__ import annotations

import time
from typing import Callable

from memory import Memory
from store import Store, UnknownMachine


def _brief(m: Memory) -> dict:
    return {"ref": m.ref(), "date": m.date, "text": m.text[:240], "tags": m.tags[:6], "score": round(m.score, 2) if m.score else None}


class TracedMemory:
    """Wraps the shared memory. emit(event) receives {op, who, bank, query, tags, hits, ms}."""

    def __init__(self, inner, emit: Callable[[dict], None], store: Store | None = None, who: str = ""):
        self.inner, self.emit, self.store, self.who = inner, emit, store, who
        self.name = inner.name
        self.bank_id = getattr(inner, "bank_id", "local")

    def as_(self, who: str) -> "TracedMemory":
        return TracedMemory(self.inner, self.emit, self.store, who)

    def _check(self, tags):
        if self.store:
            for t in tags or []:
                if t.startswith("machine:") and not self.store.has_machine(t.split(":", 1)[1]):
                    raise UnknownMachine(f"Refusing to use memory for unknown machine {t.split(':', 1)[1]!r}")

    def recall(self, query: str, tags: list[str], limit: int = 6, match: str = "any") -> list[Memory]:
        self._check(tags)
        t0 = time.time()
        res = self.inner.recall(query, tags, limit=limit, match=match)
        pool = getattr(self.inner, "pool", None)
        self.emit({"op": "recall", "who": self.who, "bank": self.bank_id, "query": query, "tags": tags, "hits": [_brief(m) for m in res],
                   "ms": int((time.time() - t0) * 1000), "match": match, "limit": limit, "pool": pool(tags, match) if pool else None})
        return res

    def reflect(self, query: str, tags: list[str]):
        self._check(tags)
        t0 = time.time()
        res = self.inner.reflect(query, tags)
        self.emit({"op": "reflect", "who": self.who, "bank": self.bank_id, "query": query, "tags": tags,
                   "hits": [{"ref": "", "date": None, "text": (res or "")[:240], "tags": []}] if res else [], "ms": int((time.time() - t0) * 1000)})
        return res

    def retain(self, text: str, tags: list[str], date: str | None, doc_id: str, meta: dict | None = None) -> None:
        self._check(tags)
        t0 = time.time()
        self.inner.retain(text, tags, date, doc_id, meta)
        self.emit({"op": "retain", "who": self.who, "bank": self.bank_id, "query": doc_id, "tags": tags,
                   "hits": [{"ref": doc_id, "date": date, "text": text[:240], "tags": tags[:5]}], "ms": int((time.time() - t0) * 1000)})

    def count(self) -> int:
        return self.inner.count()


class NullMemory:
    """The 'without memory' path: nothing is recalled, and the panel says so."""
    name = "none"
    bank_id = "(memory off)"

    def __init__(self, emit: Callable[[dict], None] | None = None, who: str = ""):
        self.emit, self.who = emit or (lambda e: None), who

    def as_(self, who: str) -> "NullMemory":
        return NullMemory(self.emit, who)

    def recall(self, query: str, tags: list[str], limit: int = 6, match: str = "any") -> list[Memory]:
        self.emit({"op": "recall", "who": self.who, "bank": self.bank_id, "query": query, "tags": tags, "hits": [], "ms": 0, "skipped": True, "match": match, "limit": limit, "pool": 0})
        return []

    def reflect(self, query: str, tags: list[str]):
        self.emit({"op": "reflect", "who": self.who, "bank": self.bank_id, "query": query, "tags": tags, "hits": [], "ms": 0, "skipped": True})
        return None

    def retain(self, *a, **k) -> None:
        return None

    def count(self) -> int:
        return 0
