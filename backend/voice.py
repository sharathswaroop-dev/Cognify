"""Voice logging: a technician speaks the visit report; Groq Whisper transcribes it; the LLM turns it into
the same structured visit the form produces. The result is shown for confirmation before anything is retained."""
from __future__ import annotations

import logging
import re
import time

log = logging.getLogger("sitememory.voice")
STT_MODEL = "whisper-large-v3"
MAX_BYTES = 24 * 1024 * 1024  # Groq's upload limit is 25 MB
MIN_BYTES = 1500              # anything smaller cannot hold a spoken sentence
RESULTS = ("worked", "failed", "partial")


class VoiceError(Exception):
    """A problem with the audio or the transcription, phrased so the technician knows what to do next."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _get(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def transcribe(client, data: bytes, filename: str = "report.webm", attempts: int = 2) -> dict:
    if client is None:
        raise VoiceError("no_stt", "Voice logging needs a Groq API key. Type the report instead.")
    if not data:
        raise VoiceError("empty", "No audio was received. Check the microphone and try again.")
    if len(data) > MAX_BYTES:
        raise VoiceError("too_large", "That recording is too long. Keep it under a few minutes, or split it in two.")
    if len(data) < MIN_BYTES:
        raise VoiceError("too_short", "That recording was too short. Hold the button and describe the visit.")
    resp, last = None, None
    for i in range(attempts):
        try:
            resp = client.audio.transcriptions.create(file=(filename, data), model=STT_MODEL, response_format="verbose_json",
                                                      language="en", temperature=0.0)
            break
        except Exception as exc:  # network blips and 5xx are retried; bad audio is reported
            last = exc
            log.warning("whisper attempt %d failed: %s", i + 1, str(exc)[:160])
            time.sleep(0.8 * (i + 1))
    if resp is None:
        msg = str(last or "")
        if any(k in msg.lower() for k in ("could not process", "invalid", "unsupported", "decode", "400")):
            raise VoiceError("bad_audio", "I couldn't read that audio file. Try recording again.")
        raise VoiceError("stt_failed", "Transcription is unavailable right now. Type the report instead.")
    text = (_get(resp, "text", "") or "").strip()
    segs = _get(resp, "segments", None) or []
    silent = [float(_get(s, "no_speech_prob", 0) or 0) for s in segs]
    # Whisper tends to invent words ("Thank you.") on silence: reject when every segment looks like non-speech.
    if not text or len(text.split()) < 3 or (silent and min(silent) > 0.6):
        raise VoiceError("no_speech", "I couldn't hear a spoken report. Move closer to the phone and try again.")
    return {"text": text, "duration": _get(resp, "duration", None), "words": len(text.split())}


EXTRACT_PROMPT = """You turn a field technician's spoken visit report into structured data for a service log.
Use ONLY what the technician said. Never invent attempts, parts or causes.
Return ONLY JSON with keys:
actions: array (1-8) of {"action": short imperative-past description e.g. "Replaced compressor contactor",
  "result": "worked" | "failed" | "partial", "detail": string}. "result" is "failed" if they said it did not help / tripped again / came back;
  "worked" if it fixed the problem; "partial" if unclear or only helped for a while.
outcome: "resolved" if the fault is fixed and the unit is running, "revisit_needed" if they said they must return or it is not fixed.
root_cause: string ("" if not stated).
parts_used: array of strings (part names/numbers actually fitted; [] if none).
notes: string (anything useful for the next technician: site quirks, follow-ups; "" if none).
uncertain: array of field names you had to guess (e.g. "outcome")."""


def _clip(s, n):
    return str(s or "").strip()[:n]


def normalise(d: dict, transcript: str) -> dict:
    acts = []
    for a in (d.get("actions") or [])[:8]:
        if isinstance(a, dict) and len(str(a.get("action", "")).strip()) >= 2:
            r = str(a.get("result", "partial")).lower()
            acts.append({"action": _clip(a["action"], 300), "result": r if r in RESULTS else "partial", "detail": _clip(a.get("detail"), 500)})
    outcome = str(d.get("outcome") or "").lower()
    if outcome not in ("resolved", "revisit_needed"):
        outcome = "resolved" if any(a["result"] == "worked" for a in acts) else "revisit_needed"
    return {"actions": acts, "outcome": outcome, "root_cause": _clip(d.get("root_cause"), 500),
            "parts_used": [_clip(p, 120) for p in (d.get("parts_used") or []) if str(p).strip()][:10],
            "notes": _clip(d.get("notes"), 800), "uncertain": [str(u) for u in (d.get("uncertain") or [])][:5]}


def extract_visit(llm, transcript: str, job: dict | None = None) -> tuple[dict, list[str]]:
    """Returns (structured visit, warnings). Never raises: on any failure the form is returned empty with the transcript in notes."""
    warnings: list[str] = []
    ctx = f"Job ticket: {job['symptom']}\n\n" if job else ""
    d = None
    try:
        d = llm.json_chat(EXTRACT_PROMPT, f"{ctx}SPOKEN REPORT:\n{transcript}", required=("actions", "outcome")) if llm else None
    except Exception as exc:
        log.warning("visit extraction failed: %s", str(exc)[:160])
    if not d:
        warnings.append("I couldn't structure that automatically. The transcript is in the notes: fill in the attempts below.")
        return ({"actions": [], "outcome": "revisit_needed", "root_cause": "", "parts_used": [], "notes": _clip(transcript, 800), "uncertain": ["all"]},
                warnings)
    out = normalise(d, transcript)
    if not out["actions"]:
        warnings.append("I didn't hear any repair attempt. Add what was tried before saving.")
        out["notes"] = out["notes"] or _clip(transcript, 800)
    if out["uncertain"]:
        warnings.append("Please check: " + ", ".join(out["uncertain"]).replace("_", " ") + ".")
    return out, warnings
