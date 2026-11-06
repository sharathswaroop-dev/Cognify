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
    def __init__(self) -> None:
        self.model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
        self.fallback_model = os.getenv("GROQ_FALLBACK_MODEL", "qwen/qwen3-32b")
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

    def json_chat(self, system: str, user: str, required: tuple[str, ...] = (), attempts: int = 3) -> dict | None:
        if not self.client:
            return None
        models = [self.model] * (attempts - 1) + [self.fallback_model]
        for i, model in enumerate(models):
            try:
                resp = self.client.chat.completions.create(
                    model=model,
                    temperature=0.2,
                    max_tokens=1800,
                    response_format={"type": "json_object"},
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                )
                data = _extract_json(resp.choices[0].message.content or "")
                if data is not None and all(k in data for k in required):
                    return data
                log.warning("LLM attempt %d (%s): invalid JSON / missing keys", i + 1, model)
            except Exception as exc:
                log.warning("LLM attempt %d (%s) failed: %s", i + 1, model, str(exc)[:200])
            time.sleep(0.6 * (i + 1))
        return None
