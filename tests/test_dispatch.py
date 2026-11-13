"""Dispatch: ranking the open problems, matching a technician, and the layer-by-layer offer flow, all on a fake clock so nothing waits."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from dispatch import OFFER_TTL, WINDOW, Dispatch  # noqa: E402
from store import Store  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture
def world(tmp_path):
    clock = Clock()
    d = Dispatch(Store(), tmp_path / "state.json", clock=clock)
    reporter = d.register("Priya Nair", "reporter", "S-01")
    return d, clock, reporter


def connect(d, clock, *tids):
    for t in tids:
        d.state["techs"][t]["last_seen"] = clock()        # a real phone is connected, so the technician is not simulated


def wave(rep, n=1):
    return [o for o in rep["offers"] if o["wave"] == n]


def test_the_ranking_weighs_experience_not_just_distance(world):
    d, _, _ = world
    # M-42 is a Mitsubishi cassette on MG Road. Arjun (a VRV specialist) is closer, but Farhan has fixed far more of this kind of fault, including this very unit.
    rank = d.rank("S-05", "M-42")
    by = {r["tech_id"]: r for r in rank}
    assert by["T-01"]["distance_km"] < by["T-04"]["distance_km"]                         # Arjun is nearer
    assert by["T-04"]["points"]["experience"] > by["T-01"]["points"]["experience"]       # but Farhan has the verified experience
    assert by["T-04"]["points"]["skill"] > by["T-01"]["points"]["skill"]
    assert rank[0]["tech_id"] == "T-04"
    assert all(abs(sum(r["points"].values()) - r["total"]) < 0.2 for r in rank)


def test_distance_still_matters_a_far_expert_does_not_beat_a_close_one_with_experience(world):
    d, _, _ = world
    assert d.rank("S-01", "M-07")[0]["tech_id"] == "T-05"        # Deepak is 1 km away and has fixed 4 of these faults


def test_a_busy_technician_is_ranked_below_an_equal_free_one(world):
    d, _, _ = world
    by = {r["tech_id"]: r for r in d.rank("S-08", "M-12")}            # Hebbal: Meena (T-03) is parked there but busy
    assert not by["T-03"]["available"] and by["T-03"]["points"]["availability"] < by["T-02"]["points"]["availability"]


def test_the_most_urgent_critical_problem_goes_to_the_top_of_the_board(world):
    d, clock, rep = world
    calm = d.create_report(rep["id"], "S-08", None, "Slight noise from one apartment unit", "normal")
    clock.advance(30)
    hot = d.create_report(rep["id"], "S-02", None, "Hospital ward AC is down and patients are waiting", "urgent")
    board = d.board()
    assert [r["id"] for r in board[:2]] == [hot["id"], calm["id"]]
    assert board[0]["priority"]["score"] > board[1]["priority"]["score"]
    assert any("critical site" in x for x in board[0]["priority"]["reasons"])


def test_a_layer_notifies_everyone_inside_it_at_once(world):
    d, _, rep = world
    r = d.create_report(rep["id"], "S-05", "M-42", "Cassette dripping water and not cooling the banquet hall", "urgent")
    first = wave(r)
    assert {o["tech_id"] for o in first} == {"T-04", "T-01", "T-06"}          # nobody within 3 km, so the 8 km layer: all three free technicians in it
    assert all(o["result"] == "pending" and o["ring"] == 2 for o in first)
    assert any("notifying 3 technicians" in e["text"] for e in r["events"])


def test_simulated_technicians_answer_and_the_best_accepting_match_wins(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-05", "M-42", "Cassette dripping water and not cooling the banquet hall", "urgent")
    for _ in range(40):
        clock.advance(1)
        d.tick()
        if d.get(r["id"])["status"] != "offered":
            break
    final = d.get(r["id"])
    assert final["status"] in ("en_route", "offered")
    results = {o["result"] for o in wave(final)}
    assert results & {"won", "declined", "timeout", "accepted", "lost"}
    if final["status"] == "en_route":
        winner = next(o for o in wave(final) if o["result"] == "won")
        assert winner["total"] == max(o["total"] for o in wave(final) if o["result"] in ("won", "lost"))


def test_when_several_accept_the_best_match_gets_it_after_the_window(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-05", "M-42", "Cassette dripping water and not cooling the banquet hall", "urgent")
    connect(d, clock, "T-04", "T-01", "T-06")
    d.respond(r["id"], "T-01", "accept")                  # Arjun is quick, but he is not the best match
    assert d.get(r["id"])["status"] == "offered"          # the layer is still open: others may answer
    clock.advance(1)
    connect(d, clock, "T-04", "T-01", "T-06")
    d.respond(r["id"], "T-04", "accept")                  # Farhan accepts a second later
    clock.advance(WINDOW + 0.5)
    connect(d, clock, "T-04", "T-01", "T-06")
    d.tick()
    final = d.get(r["id"])
    assert final["status"] == "en_route" and final["assigned"] == "T-04"
    by = {o["tech_id"]: o["result"] for o in wave(final)}
    assert by["T-04"] == "won" and by["T-01"] == "lost" and by["T-06"] == "lost"
    assert any("better match took it" in e["text"] for e in final["events"])


def test_when_everyone_in_a_layer_declines_the_next_layer_opens(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping and the floor is warm", "high")
    assert [o["tech_id"] for o in wave(r)] == ["T-05"]                  # only Deepak is inside 3 km
    connect(d, clock, "T-05")
    d.respond(r["id"], "T-05", "decline")
    again = d.get(r["id"])
    second = wave(again, 2)
    assert second and all(o["ring"] > 1 for o in second) and again["status"] == "offered"
    assert any("Widening the search" in e["text"] for e in again["events"])


def test_an_unanswered_layer_times_out_and_the_next_opens(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Unit tripped twice this morning", "high")
    connect(d, clock, "T-05")
    clock.advance(OFFER_TTL + 1)
    connect(d, clock, "T-05")
    d.tick()
    again = d.get(r["id"])
    assert wave(again, 1)[0]["result"] == "timeout" and len(wave(again, 2)) >= 1


def test_accepting_creates_a_job_the_agents_can_brief_on_and_logging_the_visit_closes_it(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high")
    connect(d, clock, "T-05")
    d.respond(r["id"], "T-05", "accept")                 # the only one in the layer: decided at once
    rr = d.get(r["id"])
    assert rr["status"] == "en_route" and rr["assigned"] == "T-05" and rr["job_id"]
    job = d.store.job(rr["job_id"])
    assert job["technician_id"] == "T-05" and job["machine_id"] == "M-07"
    assert rr["scenario_id"] and d.store.scenario(rr["scenario_id"])["machine_id"] == "M-07"
    d.set_status(r["id"], "T-05", "on_site")
    assert d.get(r["id"])["status"] == "on_site"
    d.on_visit_logged(rr["job_id"], True)                       # logging before the OTP does not close the request
    assert d.get(r["id"])["status"] == "on_site"
    d.start_work(r["id"], "T-05", d.get(r["id"])["otp"])
    d.on_visit_logged(rr["job_id"], True)
    assert d.get(r["id"])["status"] == "resolved" and d.state["techs"]["T-05"]["status"] == "available"


def test_only_the_assigned_technician_can_update_a_job(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high")
    connect(d, clock, "T-05")
    d.respond(r["id"], "T-05", "accept")
    with pytest.raises(ValueError):
        d.set_status(r["id"], "T-02", "resolved")


def test_an_offer_that_is_no_longer_open_is_refused(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high")
    connect(d, clock, "T-05")
    d.respond(r["id"], "T-05", "accept")
    with pytest.raises(ValueError):
        d.respond(r["id"], "T-05", "accept")


def test_registering_a_new_technician_adds_them_to_the_pool(world):
    d, _, _ = world
    before = len(d.rank("S-01", "M-07"))
    u = d.register("Kiran Rao", "technician", speciality="VRV / VRF systems", area="Indiranagar")
    assert u["tech_id"] and len(d.rank("S-01", "M-07")) == before + 1
    new = next(r for r in d.rank("S-01", "M-07") if r["tech_id"] == u["tech_id"])
    assert new["points"]["experience"] == 0 and new["points"]["skill"] > 0


def test_bad_input_is_refused(world):
    d, _, rep = world
    with pytest.raises(ValueError):
        d.create_report(rep["id"], "S-01", "M-07", "x", "high")
    with pytest.raises(ValueError):
        d.create_report(rep["id"], "S-01", "M-113", "The cassette is not working at all", "high")   # M-113 is at a different site


def test_state_survives_a_restart(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high")
    d2 = Dispatch(Store(), d.path, clock=clock)
    assert any(x["id"] == r["id"] for x in d2.state["reports"])


def test_nobody_close_means_the_search_widens_before_anyone_is_notified(world):
    d, _, rep = world
    r = d.create_report(rep["id"], "S-04", None, "Data hall unit is down and not cooling at all", "urgent")      # Electronic City: nobody within 8 km
    texts = [e["text"] for e in r["events"]]
    assert any("Searching within 3 km: nobody free" in t for t in texts) and any("Searching within 8 km: nobody free" in t for t in texts)
    assert wave(r)[0]["ring"] == 3 and r["ladder"][0]["free"] == 0 and r["ladder"][2]["free"] >= 1


def test_if_everyone_is_busy_the_soonest_free_technician_is_asked(world):
    d, clock, rep = world
    for tid, st in d.state["techs"].items():
        st["status"], st["busy_until"] = "busy", clock() + (10 + int(tid[-1])) * 60
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping and the floor is warm", "high")
    assert wave(r)[0]["free"] is False
    assert any("Nobody is free anywhere" in e["text"] for e in r["events"]) or any("busy technician" in e["text"] for e in r["events"])


def test_if_nobody_at_all_takes_it_a_manager_is_asked(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping and the floor is warm", "high")
    for _ in range(12):
        clock.advance(OFFER_TTL + 1)
        for t in d.state["techs"]:
            connect(d, clock, t)                          # every phone is connected and nobody answers
        d.tick()
        if d.get(r["id"])["status"] == "unassigned":
            break
    assert d.get(r["id"])["status"] == "unassigned"
    assert any("service manager" in e["text"] for e in d.get(r["id"])["events"])


def test_the_view_exposes_the_layers_for_the_live_map(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high")
    v = d.view(d.get(r["id"]))
    states = {l["ring"]: l["state"] for l in v["layers"]}
    assert states[1] == "active" and states[2] == "idle" and v["offer"]["count"] == 1
    connect(d, clock, "T-05")
    d.respond(r["id"], "T-05", "decline")
    v = d.view(d.get(r["id"]))
    states = {l["ring"]: l["state"] for l in v["layers"]}
    assert states[1] == "failed" and any(s == "active" for s in states.values())


def test_the_ladder_is_exposed_for_the_explainer(world):
    d, _, _ = world
    ex = d.explain("S-05", "M-42", "high")
    assert ex["rings"] == [3, 8, 15, 30] and ex["ladder"][1]["free"] == 3 and ex["queue"][0]["name"] == "Farhan Sheikh"


def arrived(d, clock, rep_id, tid="T-05"):
    d.respond(rep_id, tid, "accept")
    d.set_status(rep_id, tid, "on_site")


def test_the_otp_starts_the_work_and_only_the_customer_can_see_it(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high")
    connect(d, clock, "T-05")
    d.respond(r["id"], "T-05", "accept")
    rr = d.get(r["id"])
    assert len(rr["otp"]) == 4 and rr["otp"].isdigit()
    assert d.view(rr, viewer=rep["id"])["otp"] == rr["otp"]                 # the reporter sees the code
    assert d.view(rr)["otp"] is None and d.view(rr, viewer="U-999")["otp"] is None     # the technician and strangers do not
    assert d.view(rr, viewer="demo")["otp"] is None                         # the presenter sees it only in the manual demo mode
    with pytest.raises(ValueError):
        d.start_work(r["id"], "T-05", rr["otp"])                            # not on site yet
    d.set_status(r["id"], "T-05", "on_site")
    with pytest.raises(ValueError):
        d.start_work(r["id"], "T-05", "0000" if rr["otp"] != "0000" else "1111")
    assert d.get(r["id"])["status"] == "on_site"
    d.start_work(r["id"], "T-05", rr["otp"])
    done = d.get(r["id"])
    assert done["status"] == "working" and d.view(done, viewer=rep["id"])["otp"] is None and d.view(done)["otp_verified"] is True
    assert any("OTP verified" in e["text"] for e in done["events"])
    with pytest.raises(ValueError):
        d.set_status(r["id"], "T-02", "resolved")                           # nobody else can close it
    d.set_status(r["id"], "T-05", "resolved")
    assert d.get(r["id"])["status"] == "resolved"


def test_closing_a_job_before_the_otp_is_refused(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high")
    connect(d, clock, "T-05")
    arrived(d, clock, r["id"])
    with pytest.raises(ValueError):
        d.set_status(r["id"], "T-05", "resolved")


def test_too_many_wrong_otps_lock_the_job(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high")
    connect(d, clock, "T-05")
    arrived(d, clock, r["id"])
    good = d.get(r["id"])["otp"]
    bad = "1111" if good != "1111" else "2222"
    for _ in range(5):
        with pytest.raises(ValueError):
            d.start_work(r["id"], "T-05", bad)
    with pytest.raises(ValueError, match="Too many"):
        d.start_work(r["id"], "T-05", good)
    assert d.get(r["id"])["status"] == "on_site"


def test_a_simulated_customer_reads_out_the_otp_and_the_job_finishes_on_its_own(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high")
    seen = set()
    for _ in range(200):
        clock.advance(1)
        d.tick()
        seen.add(d.get(r["id"])["status"])
        if d.get(r["id"])["status"] == "resolved":
            break
    assert {"en_route", "on_site", "working", "resolved"} <= seen
    assert any("OTP verified" in e["text"] for e in d.get(r["id"])["events"])


def test_an_offline_technician_is_not_notified_and_cannot_go_offline_mid_job(world):
    d, clock, rep = world
    d.set_duty("T-05", False)                                                # Deepak is the only one inside 3 km, but he is offline
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high")
    assert "T-05" not in {o["tech_id"] for o in r["offers"]}
    assert wave(r)[0]["ring"] > 1                                            # so the search went straight to a wider layer
    assert d.positions()["technicians"][4]["status"] == "off_duty"
    d.set_duty("T-05", True)
    r2 = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping again", "high")
    assert "T-05" in {o["tech_id"] for o in r2["offers"]}
    connect(d, clock, "T-05")
    d.respond(r2["id"], "T-05", "accept")
    with pytest.raises(ValueError):
        d.set_duty("T-05", False)                                            # he is on a job now


def test_an_offline_technician_is_not_asked_even_as_the_last_resort(world):
    d, clock, rep = world
    for tid in d.state["techs"]:
        d.set_duty(tid, False)
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high")
    assert r["status"] == "unassigned" and not r["offers"]


def test_only_the_notified_technicians_see_an_offer(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high")     # only Deepak (T-05) is inside 3 km
    assert d.inbox("T-05")["offer"]["id"] == r["id"]
    assert d.inbox("T-01")["offer"] is None and d.inbox("T-04")["offer"] is None             # the others are outside the layer and see nothing


def test_manual_mode_waits_for_the_presenter_and_a_reject_opens_the_next_layer(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high", manual=True)
    for _ in range(20):
        clock.advance(2)
        d.tick()
    assert d.get(r["id"])["status"] == "offered" and wave(d.get(r["id"]))[0]["result"] == "pending"      # nobody answers by themselves
    d.respond(r["id"], "T-05", "decline", demo=True)
    again = d.get(r["id"])
    assert wave(again, 2) and any("Widening the search" in e["text"] for e in again["events"])
    assert d.state["techs"]["T-05"]["last_seen"] == 0                         # the presenter's click does not pretend a phone is connected
    first = [o["tech_id"] for o in wave(again, 2)]
    d.respond(r["id"], first[0], "accept", demo=True)
    assert d.get(r["id"])["assigned"] == first[0] or d.get(r["id"])["status"] == "offered"
    clock.advance(5)
    d.tick()
    rr = d.get(r["id"])
    assert rr["status"] in ("en_route", "offered") and (rr["status"] != "en_route" or rr["assigned"] in first)
    if rr["status"] == "en_route":
        for _ in range(60):
            clock.advance(1)
            d.tick()
        assert d.get(r["id"])["status"] == "on_site"                         # in manual mode the customer's OTP is entered by the presenter, not automatically
        assert d.view(d.get(r["id"]), viewer="demo")["otp"]
        d.start_work(r["id"], rr["assigned"], d.get(r["id"])["otp"], demo=True)
        assert d.get(r["id"])["status"] == "working"


def test_a_phone_in_demo_mode_is_played_by_the_simulation_end_to_end(world):
    d, clock, rep = world
    d.set_mode("T-05", "demo")
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high")
    seen = set()
    for _ in range(200):
        clock.advance(1)
        connect(d, clock, "T-05")                                           # the phone is connected, but in demo mode nobody has to tap anything
        d.tick()
        seen.add(d.get(r["id"])["status"])
        if d.get(r["id"])["status"] == "resolved":
            break
    assert {"en_route", "on_site", "working", "resolved"} <= seen and d.get(r["id"])["assigned"] == "T-05"


def test_a_phone_in_manual_mode_waits_for_its_person(world):
    d, clock, rep = world
    assert d.set_mode("T-05", "manual")["mode"] == "manual"
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high")
    for _ in range(30):
        clock.advance(1)
        connect(d, clock, "T-05")
        d.tick()
    assert d.get(r["id"])["status"] == "offered" and wave(d.get(r["id"]))[0]["result"] == "pending"
    assert d.inbox("T-05")["technician"]["mode"] == "manual"
    with pytest.raises(ValueError):
        d.set_mode("T-05", "turbo")


def test_a_technician_on_a_job_is_never_offered_or_given_a_second_one(world):
    d, clock, rep = world
    r1 = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high")
    connect(d, clock, "T-05")
    d.respond(r1["id"], "T-05", "accept")                                    # Deepak is now on the first job
    assert d.get(r1["id"])["assigned"] == "T-05"
    r2 = d.create_report(rep["id"], "S-01", "M-07", "Another unit is down at the same site", "urgent")
    assert "T-05" not in {o["tech_id"] for o in r2["offers"]}                # not notified in the layer
    for _ in range(12):                                                      # and not asked as the last resort either
        clock.advance(OFFER_TTL + 1)
        for t in d.state["techs"]:
            connect(d, clock, t)
        d.tick()
    assert "T-05" not in {o["tech_id"] for o in d.get(r2["id"])["offers"]}
    # even if an offer were somehow pending, accepting is refused
    rr = d.get(r2["id"])
    rr["status"], rr["wave"] = "offered", 99
    rr["offers"].append({"tech_id": "T-05", "wave": 99, "at": clock(), "expires": clock() + 40, "result": "pending", "ring": 1, "free": True, "total": 50})
    with pytest.raises(ValueError, match="already on another job"):
        d.respond(r2["id"], "T-05", "accept")


def test_a_request_remembers_where_it_came_from(world):
    d, _, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Outdoor unit keeps tripping", "high", source="app")
    assert d.view(r)["source"] == "app"
    assert d.view(d.demo_report())["source"] == "demo"


def _run(d, clock, rid, steps=60):
    for _ in range(steps):
        clock.advance(2)
        d.tick()
    return d.state["reports"][-1] if rid is None else next(r for r in d.state["reports"] if r["id"] == rid)


def test_accept_after_zero_means_the_first_to_answer_accepts(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Not cooling", "high", accept_after=0)
    r = _run(d, clock, r["id"])
    assert r["status"] != "unassigned"
    assert r["declined_n"] == 0


def test_accept_after_seven_brings_in_the_city_fleet_and_seven_decline_first(world):
    d, clock, rep = world
    assert len(d._fleet()) == 6
    r = d.create_report(rep["id"], "S-01", "M-07", "Not cooling", "high", accept_after=7)
    assert len(d._fleet()) == 30
    r = _run(d, clock, r["id"], 120)
    assert r["declined_n"] == 7
    v = d.view(r)
    assert v["counts"]["declined"] == 7 and v["counts"]["accepted"] >= 1
    assert v["counts"]["notified"] == len(r["offers"])
    assert sum(w["notified"] for w in v["waves"]) == v["counts"]["notified"]


def test_accept_after_minus_one_means_nobody_accepts(world):
    d, clock, rep = world
    r = d.create_report(rep["id"], "S-01", "M-07", "Not cooling", "high", accept_after=-1)
    r = _run(d, clock, r["id"], 150)
    assert r["status"] == "unassigned"
    assert r["declined_n"] > 0


def test_a_report_can_carry_an_optional_photo_but_the_board_only_flags_it(world):
    d, _, rep = world
    pic = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
    r = d.create_report(rep["id"], "S-01", "M-07", "Not cooling at all", "high", photo=pic)
    assert d.view(r)["photo"] == pic
    row = next(x for x in d.board() if x["id"] == r["id"])
    assert row["has_photo"] is True and "photo" not in row
    with pytest.raises(ValueError):
        d.create_report(rep["id"], "S-01", "M-07", "Not cooling at all", "high", photo="http://evil/x.png")
    assert d.view(d.create_report(rep["id"], "S-02", None, "Noisy compressor", "normal"))["photo"] is None


def test_the_acceptance_is_confirmed_and_the_work_ends_done_or_not_done(world):
    d, clock, rep = world
    connect(d, clock, "T-04")
    r = d.create_report(rep["id"], "S-05", "M-42", "Not cooling at all", "high", manual=True)
    d.respond(r["id"], "T-04", "accept")
    clock.advance(WINDOW + 1)
    d.tick()
    v = d.view(r)
    assert v["confirmed"] and v["confirmed_via"] == "phone" and v["assigned"]["phone"] is True
    assert any(e["text"].startswith("CONFIRMED") for e in r["events"])
    d.set_status(r["id"], "T-04", "on_site")
    d.start_work(r["id"], "T-04", r["otp"])
    d.set_status(r["id"], "T-04", "resolved", done=False)
    assert d.view(r)["outcome"] == "not_done" and r["status"] == "resolved"
