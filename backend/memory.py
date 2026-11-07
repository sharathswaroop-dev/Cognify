"""Memory layer for SiteMemory.

Two backends with the same interface:
  * HindsightMemory - the real thing (Hindsight Cloud or self-hosted), used when HINDSIGHT_API_KEY
    or HINDSIGHT_BASE_URL is set.
  * LocalMemory     - an in-process fallback so the app still runs offline / before keys exist.

What gets stored:
  * One memory per technician visit (symptom, what was tried, what failed, what worked, parts, notes).
  * One memory per site with access rules and customer preferences.
Every memory is tagged so we can recall at three levels:
  machine:<id>   - this exact unit's history
  family:<slug>  - the same model family at other sites (cross-site learning)
  site:<id>      - site access rules, contacts, quirks
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("sitememory.memory")
DATA_DIR = Path(__file__).resolve().parent / "data"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


@dataclass
class Memory:
    text: str
    tags: list[str] = field(default_factory=list)
    date: str | None = None
    score: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "tags": self.tags, "date": self.date,
                "score": round(self.score, 3), "meta": self.meta}

    def ref(self) -> str:
        """The source record this memory came from (e.g. J-0949), so agents can cite it."""
        m = self.meta or {}
        doc = str(m.get("document_id") or "")
        return str(m.get("job_id") or m.get("alarm_id") or (doc.split("-", 1)[1] if "-" in doc else ""))

    def cited(self) -> str:
        r = self.ref()
        return f"[source {r}{', ' + self.date if self.date else ''}] {self.text}" if r else self.text


# ---------------------------------------------------------------- formatting

def visit_to_text(visit: dict, machine: dict, site: dict, tech: dict) -> str:
    """Turn a structured visit record into the natural-language memory we retain."""
    lines = [
        f"Job {visit['job_id']}: on {visit['date']}, technician {tech['name']} visited {site['name']} ({site['area']}) "
        f"for machine {machine['id']}, a {machine['model']} {machine['type']} at {machine['location']}.",
        f"Reported symptom: {visit['symptom']}.",
    ]
    for a in visit.get("actions", []):
        verdict = "DID NOT FIX IT" if a["result"] == "failed" else "FIXED IT" if a["result"] == "worked" else "partly helped"
        lines.append(f"Tried: {a['action']} -> {verdict}. {a.get('detail', '')}".strip())
    if visit.get("root_cause"):
        lines.append(f"Root cause found: {visit['root_cause']}")
    if visit.get("parts_used"):
        lines.append(f"Parts used: {', '.join(visit['parts_used'])}.")
    if visit.get("outcome") == "revisit_needed":
        lines.append("Outcome: NOT resolved on this visit; a second visit was needed.")
    else:
        lines.append(f"Outcome: resolved on visit {visit.get('visit_no', 1)}.")
    if visit.get("recommendation"):
        lines.append(f"Recommendation: {visit['recommendation']}")
    if visit.get("notes"):
        lines.append(f"Technician note: {visit['notes']}")
    return "\n".join(lines)


def site_to_text(site: dict) -> str:
    notes = " ".join(f"- {n}" for n in site.get("notes", []))
    return (f"Site profile for {site['name']} ({site['area']}). Contact: {site['contact']}. "
            f"Access rules and preferences: {notes}")


def visit_tags(visit: dict, machine: dict) -> list[str]:
    return [f"machine:{machine['id']}", f"site:{machine['site_id']}",
            f"family:{slug(machine['model_family'])}", "kind:visit"]


# ---------------------------------------------------------------- local fallback

_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("a an the of on at for to in and or is was it this that with by from after before".split())


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1}


class LocalMemory:
    """Keyword-overlap memory persisted to a JSON file. Good enough to demo offline."""

    name = "local"

    def __init__(self, path: Path | None = None):
        self.path = path or DATA_DIR / "local_memory.json"
        self._lock = threading.Lock()
        self.items: list[dict] = []
        if self.path.exists():
            try:
                self.items = json.loads(self.path.read_text())
            except json.JSONDecodeError:
                log.warning("local memory file corrupt; starting empty")

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.items, indent=1, ensure_ascii=False))

    def retain(self, text: str, tags: list[str], date: str | None, doc_id: str, meta: dict | None = None) -> None:
        with self._lock:
            self.items = [i for i in self.items if i["doc_id"] != doc_id]  # idempotent upsert
            self.items.append({"doc_id": doc_id, "text": text, "tags": tags, "date": date, "meta": meta or {}})
            self._save()

    def retain_many(self, records: list[dict]) -> None:
        with self._lock:
            ids = {r["doc_id"] for r in records}
            self.items = [i for i in self.items if i["doc_id"] not in ids] + records
            self._save()

    def _index(self):
        """BM25 statistics over the whole corpus, rebuilt only when the memory changes."""
        if getattr(self, "_idx_n", -1) != len(self.items):
            import math
            from collections import Counter
            docs = [Counter(_WORD.findall(i["text"].lower())) for i in self.items]
            df = Counter(t for d in docs for t in d)
            n = max(1, len(docs))
            self._docs, self._len = docs, [sum(d.values()) or 1 for d in docs]
            self._avg = sum(self._len) / n
            self._idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
            self._idx_n = len(self.items)

    def recall(self, query: str, tags: list[str], limit: int = 6, match: str = "any") -> list[Memory]:
        """Plain BM25 keyword search (k1=1.5, b=0.75) over memories that carry one of the tags: the 'basic search' baseline."""
        self._index()
        q = [t for t in _WORD.findall(query.lower()) if t not in _STOP and len(t) > 1]
        out = []
        for idx, i in enumerate(self.items):
            if tags and not (set(tags) <= set(i["tags"]) if match == "all" else set(tags) & set(i["tags"])):
                continue
            d, dl = self._docs[idx], self._len[idx]
            score = sum(self._idf.get(t, 0) * d[t] * 2.5 / (d[t] + 1.5 * (0.25 + 0.75 * dl / self._avg)) for t in set(q) if t in d)
            out.append(Memory(i["text"], i["tags"], i["date"], score, i.get("meta", {})))
        out.sort(key=lambda m: (m.score, m.date or ""), reverse=True)
        return out[:limit]

    def pool(self, tags: list[str], match: str = "any") -> int:
        """How many stored records the tag filter lets through (the candidate pool a search ranks)."""
        if not tags:
            return len(self.items)
        return sum(1 for i in self.items if (set(tags) <= set(i["tags"]) if match == "all" else set(tags) & set(i["tags"])))

    def reflect(self, query: str, tags: list[str]) -> str | None:
        """Heuristic 'reflect': tally what failed and what worked across matching visits."""
        rel = [i for i in self.items if set(tags) & set(i["tags"]) and "kind:visit" in i["tags"]]
        if not rel:
            return None
        failed, worked, causes = {}, {}, {}
        for i in rel:
            for a in i.get("meta", {}).get("actions", []):
                bucket = failed if a["result"] == "failed" else worked if a["result"] == "worked" else None
                if bucket is not None:
                    bucket[a["action"]] = bucket.get(a["action"], 0) + 1
            rc = i.get("meta", {}).get("root_cause")
            if rc:
                causes[rc] = causes.get(rc, 0) + 1
        parts = [f"Across {len(rel)} past visits on matching equipment:"]
        if worked:
            parts.append("Fixes that worked: " + "; ".join(f"{k} ({v}x)" for k, v in sorted(worked.items(), key=lambda x: -x[1])[:3]) + ".")
        if failed:
            parts.append("Attempts that did NOT fix it: " + "; ".join(f"{k} ({v}x)" for k, v in sorted(failed.items(), key=lambda x: -x[1])[:3]) + ".")
        if causes:
            top = max(causes.items(), key=lambda x: x[1])
            parts.append(f"Most common root cause ({top[1]}x): {top[0]}")
        return " ".join(parts)

    def count(self) -> int:
        return len(self.items)

    def reset(self) -> None:
        with self._lock:
            self.items = []
            self._save()


# ---------------------------------------------------------------- Hindsight

class _LoopThread:
    """One long-lived event loop on a daemon thread.

    The Hindsight client is async (aiohttp). Its sync wrappers break when called from FastAPI's worker
    threads ("Timeout context manager should be used inside a task"), so every call goes through the
    async API on this single loop and the calling thread just waits for the result.
    """

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, name="hindsight-loop", daemon=True).start()

    def run(self, coro, timeout: float = 90.0):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)


class HindsightMemory:
    """Thin wrapper over the official hindsight-client (retain / recall / reflect)."""

    name = "hindsight"

    def __init__(self, base_url: str, api_key: str | None, bank_id: str, mission: str | None = None,
                 label: str = "field service"):
        from hindsight_client import Hindsight  # imported lazily so local mode needs no package

        self._io = _LoopThread()
        self.client = Hindsight(base_url=base_url, api_key=api_key, timeout=60.0)
        self.bank_id = bank_id
        self._retained = 0
        try:
            self._io.run(self.client.acreate_bank(
                bank_id,
                name=f"SiteMemory - {label}",
                mission=mission or ("Remember every HVAC service visit: symptoms, what was tried, what failed, what fixed it, "
                                    "parts, and each customer site's access rules, so the next technician fixes it first time."),
            ))
            log.info("created Hindsight bank %s", bank_id)
        except Exception as exc:  # bank already exists or create not permitted - both fine
            log.info("create_bank skipped (%s)", str(exc)[:120])

    def retain(self, text: str, tags: list[str], date: str | None, doc_id: str, meta: dict | None = None) -> None:
        self._io.run(self.client.aretain(
            self.bank_id, text, timestamp=date, context="field service visit log",
            document_id=doc_id, tags=tags,
            metadata={k: str(v) for k, v in (meta or {}).items() if isinstance(v, (str, int, float))}))
        self._retained += 1

    def retain_many(self, records: list[dict], wait: bool = False) -> None:
        """wait=True: return only when Hindsight has finished ingesting (the replay evaluation needs this, or it would query a half-built bank)."""
        items = [{"content": r["text"], "timestamp": r.get("date"), "context": "field service visit log",
                  "document_id": r["doc_id"], "tags": r["tags"],
                  "metadata": {k: str(v) for k, v in (r.get("meta") or {}).items() if isinstance(v, (str, int, float))}}
                 for r in records]
        for start in range(0, len(items), 20):  # keep requests small
            self._io.run(self.client.aretain_batch(self.bank_id, items[start:start + 20], retain_async=not wait), timeout=900 if wait else 90)
        self._retained += len(items)

    def recall(self, query: str, tags: list[str], limit: int = 6, match: str = "any") -> list[Memory]:
        resp = self._io.run(self.client.arecall(
            self.bank_id, query, tags=tags or None, tags_match=match, budget="mid", max_tokens=2048))
        out = []
        for r in (resp.results or [])[:limit]:
            date = str(r.occurred_start or r.mentioned_at or "")[:10] or None
            meta = dict(r.metadata or {})
            if getattr(r, "document_id", None):
                meta["document_id"] = r.document_id
            out.append(Memory(r.text, list(r.tags or []), date, 0.0, meta))
        return out

    def reflect(self, query: str, tags: list[str]) -> str | None:
        resp = self._io.run(self.client.areflect(
            self.bank_id, query, tags=tags or None, tags_match="any", budget="low"))
        return (resp.text or "").strip() or None

    def count(self) -> int:
        try:
            res = self._io.run(self.client.alist_memories(self.bank_id, limit=1))
            total = getattr(res, "total", None)
            return int(total) if total is not None else self._retained
        except Exception:
            return self._retained

    def reset(self) -> None:
        raise RuntimeError("Reset is disabled for Hindsight Cloud. Delete or recreate the bank in the Hindsight UI.")


# ---------------------------------------------------------------- factory

def bank_prefix() -> str:
    return os.getenv("HINDSIGHT_BANK_PREFIX", "sitememory-v2").strip()


def build_memory(role: str = "field", bank_id: str | None = None, mission: str | None = None):
    """One memory per agent role. Each role gets its own Hindsight bank (or its own local file)."""
    key = os.getenv("HINDSIGHT_API_KEY", "").strip()
    url = os.getenv("HINDSIGHT_BASE_URL", "").strip()
    bank = bank_id or (os.getenv("HINDSIGHT_BANK_ID", "").strip() if role == "field" else "") or f"{bank_prefix()}-{role}"
    if key or url:
        try:
            return HindsightMemory(url or "https://api.hindsight.vectorize.io", key or None, bank,
                                   mission=mission, label=f"{role} agent")
        except Exception as exc:
            log.error("Hindsight unavailable (%s); falling back to local memory", exc)
    log.warning("No Hindsight credentials set - using LOCAL fallback memory for %s", role)
    return LocalMemory(DATA_DIR / f"local_memory_{role}.json")


# ---------------------------------------------------------------- resilience

class FallbackMemory:
    """Hindsight first, local keyword memory if Hindsight fails (no credits, outage, bad key).

    The first failure opens a circuit: from then on everything is served by the local memory and `reason` says why, so the UI can
    show it instead of pretending. Every retain also goes to the local memory so the two stay in step."""

    def __init__(self, primary, secondary):
        self.primary, self.secondary = primary, secondary
        self.degraded, self.reason = False, ""
        self.bank_id = getattr(primary, "bank_id", "local")

    @property
    def name(self) -> str:
        return "local (Hindsight unavailable)" if self.degraded else self.primary.name

    def _trip(self, op: str, exc: Exception) -> None:
        if not self.degraded:
            self.degraded = True
            self.reason = f"{op} failed: {str(exc)[:200]}"
            log.error("Hindsight unavailable, switching to the local memory. %s", self.reason)

    def pool(self, tags: list[str], match: str = "any") -> int:
        # Only the local index can say how many records pass a tag filter; Hindsight ranks server-side, so while it is the primary we do not claim a number.
        return self.secondary.pool(tags, match) if self.degraded else None

    def recall(self, query: str, tags: list[str], limit: int = 6, match: str = "any") -> list[Memory]:
        if not self.degraded:
            try:
                res = self.primary.recall(query, tags, limit=limit, match=match)
                if res:
                    return res
                # Hindsight answered, but with nothing. Right after a retain it may still be processing (it ingests in the background, and not at all
                # without credit), so a record we hold locally would be missed. Use the local copy, but only for a real keyword match.
                near = [m for m in self.secondary.recall(query, tags, limit=limit, match=match) if m.score > 0]
                if near:
                    self.gap_fills = getattr(self, "gap_fills", 0) + 1
                return near
            except Exception as exc:
                self._trip("recall", exc)
        return self.secondary.recall(query, tags, limit=limit, match=match)

    def reflect(self, query: str, tags: list[str]):
        if not self.degraded:
            try:
                return self.primary.reflect(query, tags)
            except Exception as exc:
                self._trip("reflect", exc)
        return self.secondary.reflect(query, tags)

    def retain(self, text: str, tags: list[str], date: str | None, doc_id: str, meta: dict | None = None) -> None:
        self.secondary.retain(text, tags, date, doc_id, meta)
        if not self.degraded:
            try:
                self.primary.retain(text, tags, date, doc_id, meta)
            except Exception as exc:
                self._trip("retain", exc)

    def retain_many(self, records: list[dict]) -> None:
        self.secondary.retain_many(records)
        if not self.degraded:
            try:
                self.primary.retain_many(records)
            except Exception as exc:
                self._trip("retain_many", exc)

    def count(self) -> int:
        return self.secondary.count() if self.degraded else self.primary.count()

    def reset(self) -> None:
        self.secondary.reset()
