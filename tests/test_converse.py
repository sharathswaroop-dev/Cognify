"""The conversation layer: what a good colleague would say to each kind of message."""
import converse


def act(msg, history=None):
    return converse.plan(msg, history or [])["act"]


def test_pleasantries_are_answered_like_a_person_without_touching_the_memory():
    assert act("hello") == "greet"
    assert act("Hi there!") == "greet"
    assert act("thank you") == "thanks"
    assert act("thanks a lot") == "thanks"
    assert act("bye") == "bye"
    assert act("how are you") == "smalltalk"
    assert act("who are you") == "about"
    assert converse.plan("thank you")["reply"]


def test_a_vague_problem_gets_a_question_not_a_report():
    t = converse.plan("i have a problem")
    assert t["act"] == "clarify" and t["chips"] and any(w in t["reply"].lower() for w in ("machine", "unit"))
    assert act("something is wrong") == "clarify"
    assert act("can you help me") == "clarify"


def test_a_specific_problem_goes_to_the_memory_and_asks_for_the_unit_when_missing():
    t = converse.plan("my chiller keeps tripping on high pressure")
    assert t["act"] == "answer" and t["ask_unit"] is True
    t = converse.plan("M-07 shows E3 and trips")
    assert t["act"] == "answer" and t["machine"] == "M-07" and t["ask_unit"] is False


def test_a_short_follow_up_carries_the_earlier_question():
    hist = [{"role": "user", "content": "M-91 trips on L8 overcurrent", "kind": "answer"}, {"role": "assistant", "content": "It is the inverter board.", "kind": "answer"}]
    t = converse.plan("and for older units?", hist)
    assert t["act"] == "answer" and "M-91" in t["query"] and "older units" in t["query"]
    assert t["machine"] == "M-91"


def test_a_correction_is_recognised_and_a_bare_no_asks_for_the_right_answer():
    hist = [{"role": "user", "content": "M-91 trips on L8", "kind": "answer"}, {"role": "assistant", "content": "Replace the contactor.", "kind": "answer"}]
    t = converse.plan("no, it was actually the inverter board on that unit", hist)
    assert t["act"] == "correct" and t["machine"] == "M-91"
    t = converse.plan("no that's wrong", hist)
    assert t["act"] == "correct_ask"
    hist2 = hist + [{"role": "user", "content": "no that's wrong"}, {"role": "assistant", "content": "What was the right answer?", "kind": "correct_ask"}]
    t = converse.plan("it was the inverter board, we replaced it", hist2)
    assert t["act"] == "correct" and "inverter board" in t["correction"]


def test_something_learned_is_saved_not_searched():
    assert act("Remember that on M-91 the L8 trips are the inverter board") == "share"
    assert act("we replaced the inverter board on M-64 and it fixed the trips for good") == "share"


def test_plain_strips_markdown_and_cuts_at_a_sentence():
    t = converse.plain("### Alarm History\n* **M-07** tripped.\n| a | b |\n" + "Sentence here. " * 80, 200)
    assert "#" not in t and "**" not in t and "|" not in t and len(t) <= 201
    assert t.endswith(".") or t.endswith("…")
