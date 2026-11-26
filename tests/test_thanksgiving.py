"""Cooking timeline engine: USDA roast table, the default plan, anchoring and re-flow."""
import copy
import datetime as dt

from familydash import thanksgiving as tg
from tests.conftest import TZ

PLAN = tg.load_plan()
T = dt.datetime(2026, 11, 26, 16, 0, tzinfo=TZ)


def at(h, m=0):
    return dt.datetime(2026, 11, 26, h, m, tzinfo=TZ)


def iso(h, m=0):
    return at(h, m).isoformat()


def test_roast_table_interpolates_usda_upper_bounds():
    for lb, want in [(8, 165), (10, 170), (12, 180), (13, 200), (14, 225), (16, 240), (18, 255), (20, 270), (24, 300), (26, 325)]:
        assert tg.roast_minutes(lb) == want, lb
    assert tg.roast_minutes(14, convection=True) == 170


def test_default_plan_14lb_dinner_at_4():
    steps = tg.schedule(PLAN, T, {"turkey_lb": 14}, now=at(9))
    b = tg.by_id(steps)
    assert (b["turkey_out_fridge"].start, b["turkey_prep"].start, b["turkey_roast"].start) == (at(9, 50), at(10, 55), at(11, 15))
    assert b["turkey_roast"].end == at(15, 0) and b["turkey_rest"].end == at(15, 40)
    assert b["turkey_carve"].start == at(15, 40) and b["turkey_carve"].end == at(15, 55)
    assert b["stuffing_bake"].start == at(15, 0) and b["gravy_fresh"].start == at(15, 5)
    assert b["potato_boil"].start == at(14, 45) and b["potato_mash"].start == at(15, 20) and b["potato_warm"].end == T
    assert b["biscuits_bake"].temp == 350 and b["biscuits_bake"].end == at(15, 55)
    assert b["salad_toss"].end == T and b["dinner"].start == T
    assert b["table_set"].who == "Hannah & Elliott"
    assert tg.resource_conflicts(steps) == []
    assert {d["id"] for d in PLAN["dishes"]} >= {"turkey", "potatoes", "salad", "boxgravy", "gravy", "stuffing", "biscuits"}


def test_statuses_mid_roast():
    done = {"turkey_out_fridge": iso(9, 52), "oven_preheat": iso(10, 50), "turkey_prep": iso(11, 20)}
    steps = tg.schedule(PLAN, T, {"turkey_lb": 14, "done": done}, now=at(14, 50))
    b = tg.by_id(steps)
    assert b["turkey_roast"].status == "now"
    assert b["turkey_roast"].start == at(11, 20) and b["turkey_roast"].end == at(15, 5)     # follows the real in-time
    assert b["turkey_temp_check"].start == at(11, 20) + dt.timedelta(minutes=round(225 * .75))
    assert b["potato_boil"].status == "now" and b["potato_peel"].status == "late" and b["table_set"].status == "later"
    bd = tg.board(steps, at(14, 50), T)
    assert bd["next"][0].id == "stuffing_bake" and len({s.dish_id for s in bd["next"]}) == len(bd["next"])


def test_late_turkey_makes_dependents_wait_not_late():
    steps = tg.schedule(PLAN, T, {"turkey_lb": 14, "done": {"turkey_prep": iso(11, 15)}}, now=at(15, 10))
    b = tg.by_id(steps)
    assert b["turkey_roast"].status == "late"
    assert b["gravy_fresh"].status == "waiting" and b["gravy_fresh"].waiting_on == "turkey_roast"
    assert b["stuffing_bake"].status == "waiting" and b["stuffing_bake"].start == at(15, 10)
    assert tg.board(steps, at(15, 10), T)["behind_minutes"] == 5


def test_turkey_out_late_reflows_everything_downstream():
    done = {"turkey_prep": iso(11, 15), "turkey_roast": iso(15, 20)}
    b = tg.by_id(tg.schedule(PLAN, T, {"turkey_lb": 14, "done": done}, now=at(15, 25)))
    assert b["gravy_fresh"].start == at(15, 25) and b["stuffing_bake"].end == at(16, 5)
    assert b["turkey_rest"].end == at(16, 0) and b["turkey_carve"].start == at(16, 0)


def test_early_turkey_never_carves_before_t_minus_20():
    done = {"turkey_prep": iso(11, 15), "turkey_roast": iso(14, 40)}
    b = tg.by_id(tg.schedule(PLAN, T, {"turkey_lb": 14, "done": done}, now=at(14, 45)))
    assert b["turkey_rest"].end == at(15, 20) and b["turkey_carve"].start == at(15, 40)
    assert b["stuffing_bake"].start == at(14, 40) and b["gravy_fresh"].start == at(14, 45)


def test_dinner_time_and_weight_move_the_whole_plan():
    b = tg.by_id(tg.schedule(PLAN, dt.datetime(2026, 11, 26, 16, 30, tzinfo=TZ), {"turkey_lb": 20}))
    assert b["turkey_roast"].start == at(11, 0) and b["turkey_roast"].end == at(15, 30)
    assert b["turkey_out_fridge"].start == at(9, 35)


def test_oven_temperature_conflict_is_reported():
    bad = copy.deepcopy(PLAN)
    for d in bad["dishes"]:
        for st in d["steps"]:
            if st["id"] == "stuffing_bake":
                st["start"] = -90
    conf = tg.resource_conflicts(tg.schedule(bad, T, {"turkey_lb": 14}))
    assert any(c["kind"] == "temperature" for c in conf)


def test_lanes_and_window():
    steps = tg.schedule(PLAN, T, {"turkey_lb": 14, "done": {"turkey_prep": iso(11, 15)}}, now=at(13))
    ws, we = tg.timeline_window(steps, T)
    assert (ws, we) == (at(9), at(17))
    lanes = tg.lanes(steps, ws, we)
    assert lanes[0]["dish"] == "Turkey" and len(lanes) == 8
    roast = next(x for x in lanes[0]["blocks"] if x["id"] == "turkey_roast")
    assert abs(roast["left"] - 100 * 2.25 / 8) < 1e-6 and abs(roast["width"] - 100 * 3.75 / 8) < 1e-6
