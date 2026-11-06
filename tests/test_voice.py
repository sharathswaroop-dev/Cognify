import types

import pytest

import voice
from conftest import FakeLLM


class Segs:
    def __init__(self, text, no_speech=0.01, duration=7.2, raises=None):
        self.text, self.duration = text, duration
        self.segments = [{"no_speech_prob": no_speech}]
        self.raises = list(raises or [])

    @property
    def audio(self):
        return types.SimpleNamespace(transcriptions=types.SimpleNamespace(create=self._create))

    def _create(self, **kw):
        assert kw["model"] == "whisper-large-v3" and kw["file"][1]
        if self.raises:
            raise self.raises.pop(0)
        return self


GOOD = b"x" * 5000


def err(code, **kw):
    with pytest.raises(voice.VoiceError) as e:
        voice.transcribe(**kw)
    assert e.value.code == code
    return e.value.message


def test_no_client_empty_tiny_and_huge_audio_are_explained():
    err("no_stt", client=None, data=GOOD)
    assert "microphone" in err("empty", client=Segs("x"), data=b"")
    err("too_short", client=Segs("x"), data=b"x" * 100)
    err("too_large", client=Segs("x"), data=b"x" * (voice.MAX_BYTES + 1))


def test_silence_that_whisper_hallucinates_over_is_rejected():
    assert "couldn't hear" in err("no_speech", client=Segs("Thank you.", no_speech=0.93), data=GOOD)
    err("no_speech", client=Segs("", no_speech=0.1), data=GOOD)
    err("no_speech", client=Segs("ok yes", no_speech=0.1), data=GOOD)  # fewer than three words


def test_good_audio_returns_transcript():
    r = voice.transcribe(Segs("Replaced the contactor and it still tripped"), GOOD)
    assert r["text"].startswith("Replaced") and r["words"] == 7 and r["duration"] == 7.2


def test_transient_failure_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr(voice.time, "sleep", lambda s: None)
    r = voice.transcribe(Segs("Replaced the contactor today", raises=[RuntimeError("503 upstream")]), GOOD)
    assert r["text"]


def test_persistent_failure_and_unreadable_files_have_distinct_messages(monkeypatch):
    monkeypatch.setattr(voice.time, "sleep", lambda s: None)
    err("stt_failed", client=Segs("x", raises=[RuntimeError("timeout")] * 2), data=GOOD)
    err("bad_audio", client=Segs("x", raises=[RuntimeError("400 could not process file")] * 2), data=GOOD)


def llm(reply):
    return FakeLLM({"spoken visit report": reply})


SPOKEN = "Reset the breaker, that did not help. Then I replaced the compressor contactor and it ran fine."


def test_extraction_normalises_what_the_llm_returns():
    out, warn = voice.extract_visit(llm({
        "actions": [{"action": "Reset outdoor unit breaker", "result": "FAILED", "detail": "tripped again"},
                    {"action": "Replaced compressor contactor", "result": "fixed", "detail": ""},
                    {"action": "", "result": "worked"}],
        "outcome": "weird", "root_cause": "burnt coil", "parts_used": ["DK-CTR-24V", " "], "notes": "", "uncertain": ["outcome"]}), SPOKEN)
    assert [a["result"] for a in out["actions"]] == ["failed", "partial"]  # unknown 'fixed' becomes partial, blank action dropped
    assert out["outcome"] == "revisit_needed"  # no 'worked' action, so we do not claim it was resolved
    assert out["parts_used"] == ["DK-CTR-24V"] and any("outcome" in w for w in warn)


def test_outcome_is_inferred_when_a_fix_worked():
    out, _ = voice.extract_visit(llm({"actions": [{"action": "Replaced contactor", "result": "worked"}], "outcome": ""}), SPOKEN)
    assert out["outcome"] == "resolved"


def test_extraction_failure_keeps_the_transcript_instead_of_losing_it():
    out, warn = voice.extract_visit(FakeLLM({}), SPOKEN)  # LLM returns nothing
    assert out["actions"] == [] and out["notes"] == SPOKEN and warn
    boom = types.SimpleNamespace(json_chat=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    out, warn = voice.extract_visit(boom, SPOKEN)
    assert out["notes"] == SPOKEN


def test_report_with_no_repair_attempt_warns():
    out, warn = voice.extract_visit(llm({"actions": [], "outcome": "revisit_needed"}), "I looked at the unit and left")
    assert out["actions"] == [] and any("didn't hear any repair" in w for w in warn)


def test_output_respects_the_visit_log_limits():
    out, _ = voice.extract_visit(llm({"actions": [{"action": "x" * 900, "result": "worked", "detail": "d" * 900}] * 12, "outcome": "resolved",
                                      "root_cause": "r" * 900, "parts_used": ["p"] * 20, "notes": "n" * 2000}), SPOKEN)
    assert len(out["actions"]) == 8 and len(out["actions"][0]["action"]) == 300 and len(out["parts_used"]) == 10
    assert len(out["root_cause"]) == 500 and len(out["notes"]) == 800
