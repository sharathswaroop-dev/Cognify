"""Groq LLM wrapper with retries and strict JSON output.

The recommended Groq models can return malformed tool/JSON output,
so every call is retried and validated, and callers always get either a dict or None (never a crash).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

log = logging.getLogger("sitememory.llm")

_THINK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def _extract_json(text: str) -> dict | None:
    text = _FENCE.sub("", _THINK.sub("", text or "")).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


class LLM:
    """Groq with failover. Each model has its own daily token budget, so a rate limit moves straight on to the next model."""

    def __init__(self) -> None:
        self.model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
        chain = os.getenv("GROQ_MODELS", f"{self.model},openai/gpt-oss-20b,qwen/qwen3.8-27b")
        self.models = list(dict.fromkeys(m.strip() for m in chain.split(",") if m.strip()))
        self.used: dict[str, int] = {}
        key = os.getenv("GROQ_API_KEY", "").strip()
        self.client = None
        if key:
            try:
                from groq import Groq
                self.client = Groq(api_key=key, timeout=30.0)
            except Exception as exc:
                log.error("Groq client init failed: %s", exc)

    @property
    def available(self) -> bool:
        return self.client is not None

    @staticmethod
    def _retry_after(msg: str) -> float | None:
        """Seconds Groq says to wait ('try again in 6.5s' / '1m2.4s'); None if it is not a wait we can ride out."""
        m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", msg)
        if not m:
            return None
        h, mi, sec = (float(m.group(1) or 0), float(m.group(2) or 0), float(m.group(3) or 0))
        return h * 3600 + mi * 60 + sec

    def json_chat(self, system: str, user: str, required: tuple[str, ...] = (), attempts: int = 2, passes: int = 3) -> dict | None:
        """Try each model in turn. A per-minute rate limit is waited out (up to ~25s) and the chain retried; a daily limit moves on."""
        if not self.client:
            return None
        for _ in range(passes):
            waits = []
            for model in self.models:
                for i in range(attempts):
                    try:
                        resp = self.client.chat.completions.create(
                            model=model, temperature=0.2, max_tokens=1800, response_format={"type": "json_object"},
                            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
                        data = _extract_json(resp.choices[0].message.content or "")
                        if data is not None and all(k in data for k in required):
                            self.used[model] = self.used.get(model, 0) + 1
                            return data
                        log.warning("LLM %s attempt %d: invalid JSON / missing keys", model, i + 1)
                    except Exception as exc:
                        msg = str(exc)
                        if "429" in msg or "model_not_found" in msg or "404" in msg:   # out of budget or not available: try the next model now
                            w = self._retry_after(msg) if "429" in msg else None
                            if w is not None:
                                waits.append(w)
                            log.warning("LLM %s unavailable (%s); trying the next model", model, msg[:80])
                            break
                        log.warning("LLM %s attempt %d failed: %s", model, i + 1, msg[:160])
                        time.sleep(0.6 * (i + 1))
            short = [w for w in waits if w <= 25]
            if not short:
                break
            time.sleep(min(short) + 0.5)
        return None
