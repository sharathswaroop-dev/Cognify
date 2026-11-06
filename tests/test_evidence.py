import evidence as ev


def v(job, inc, day, machine="M-1", fault="f", outcome="resolved", res="worked", action="Replaced compressor contactor", no=1):
    return {"job_id": job, "incident_id": inc, "visit_no": no, "date": day, "machine_id": machine, "fault_class": fault, "outcome": outcome,
            "actions": [{"action": action, "result": res, "detail": ""}]}


M = lambda mid: {"id": mid, "model_family": "Fam", "installed": 2020}


def test_levels_climb_with_time_and_only_with_time():
    fixed = v("J1", "I1", "2026-01-10")
    assert ev.visit_levels([fixed], "2026-01-20")["J1"]["level"] == "fixed_at_visit"
    assert ev.visit_levels([fixed], "2026-02-15")["J1"]["level"] == "stable_30d"
    assert ev.visit_levels([fixed], "2026-06-01")["J1"]["level"] == "stable_90d"


def test_a_visit_that_fixed_nothing_stays_suspected():
    bad = v("J1", "I1", "2026-01-10", outcome="revisit_needed", res="failed")
    assert ev.visit_levels([bad], "2026-09-01")["J1"]["level"] == "suspected"


def test_recurrence_within_30_days_means_it_never_counts_as_fixed():
    a, b = v("J1", "I1", "2026-01-10"), v("J2", "I2", "2026-01-31")  # same machine, same fault, 21 days later
    info = ev.visit_levels([a, b], "2026-09-01")["J1"]
    assert info["recurred"] and info["recurred_after_days"] == 21 and info["level"] == "fixed_at_visit" and not ev.is_verified(info)


def test_recurrence_after_30_days_still_leaves_the_30_day_level_earned():
    a, b = v("J1", "I1", "2026-01-10"), v("J2", "I2", "2026-03-01")  # 50 days later
    info = ev.visit_levels([a, b], "2026-09-01")["J1"]
    assert info["level"] == "stable_30d" and not info["recurred"]


def test_a_different_machine_or_fault_is_not_a_recurrence():
    a = v("J1", "I1", "2026-01-10")
    for other in (v("J2", "I2", "2026-01-20", machine="M-2"), v("J3", "I3", "2026-01-20", fault="other")):
        assert not ev.visit_levels([a, other], "2026-09-01")["J1"]["recurred"]


def test_levels_never_see_the_future():
    a, b = v("J1", "I1", "2026-01-10"), v("J2", "I2", "2026-01-31")
    lv = ev.visit_levels([a, b], "2026-01-25")   # the recurrence has not happened yet on this date
    assert "J2" not in lv and not lv["J1"]["recurred"] and lv["J1"]["level"] == "fixed_at_visit"


def test_attempt_outcomes_separate_verified_provisional_and_failed():
    vs = [v("J1", "I1", "2026-01-01"), v("J2", "I2", "2026-02-01", machine="M-2"),
          v("J3", "I3", "2026-03-01", machine="M-3", res="failed", outcome="revisit_needed"),
          v("J4", "I4", "2026-10-30", machine="M-4")]   # fixed a week ago: provisional
    att = ev.attempts(vs, M, "2026-11-07")["Fam"]["replaced compressor contactor"]
    assert [a["result"] for a in att] == ["verified", "verified", "failed", "provisional"]
    s = ev.fix_stats(att)
    assert (s["n"], s["verified"], s["provisional"], s["failed"]) == (4, 2, 1, 1) and s["weak"]  # n < 5 is a weak signal


def test_confidence_is_earned_by_verified_outcomes_only():
    strong = {"n": 9, "verified": 8, "provisional": 0, "failed": 1, "rate": 0.889, "weak": False}
    assert ev.confidence(strong) == "high"
    assert ev.confidence({**strong, "verified": 3, "provisional": 5, "rate": 0.333}) == "low"  # fixed-at-visit does not count
    assert ev.confidence({**strong, "n": 4, "weak": True}) == "weak"


def test_wilson_interval_is_honest_about_small_samples():
    lo, hi = ev.wilson(4, 4)
    assert lo < 0.6 and hi == 1.0           # 4 of 4 is not certainty
    lo2, _ = ev.wilson(40, 40)
    assert lo2 > 0.9
    assert ev.wilson(0, 0) == (0.0, 1.0)
