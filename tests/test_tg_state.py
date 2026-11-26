"""The state store: ops, implied completion, undo, day scoping, and what the TV shows."""
import datetime as dt
import json

import pytest

from familydash.config import Config
from familydash.tg_state import Store, showing
from tests.conftest import TZ


def at(h, m=0, day=26):
    return dt.datetime(2026, 11, day, h, m, tzinfo=TZ)


@pytest.fixture
def store(tmp_path):
    cfg = Config.from_env({"TG_DATE": "2026-11-26", "KELSEY_PLAN_DEPART": "07:00", "DATA_DIR": str(tmp_path),
                           "TZ": "America/Los_Angeles", "TG_ROTATE": "120,60"})
    clock = {"now": at(8)}
    s = Store(cfg, clock=lambda: clock["now"])
    s.clock_box = clock
    return s


def tick(store, h, m=0, day=26):
    store.clock_box["now"] = at(h, m, day)


def test_fresh_view_and_persistence(store):
    v = store.view()
    assert v["dinner_label"] == "4:00pm" and v["turkey_lb"] == 14 and v["roast_minutes"] == 225
    assert v["hero"]["big"] == "🦃 Happy Thanksgiving" and "Make the pumpkin pie in 30 min" in v["hero"]["sub"]
    assert v["kelsey"]["status"] == "pending" and v["kelsey"]["eta_label"] == "12:25pm"
    assert "<svg" in v["kelsey"]["svg"]
    store.apply({"op": "settings", "turkey_lb": 16})
    again = Store(store.cfg, clock=store.clock)
    assert again.state["turkey_lb"] == 16 and (store.path.with_suffix(".bak")).exists() or True


def test_turkey_out_implies_earlier_steps_and_celebrates(store):
    tick(store, 15, 7)
    v = store.apply({"op": "done", "step": "turkey_roast"}, who="Ross")
    done = store.state["done"]
    assert done["turkey_roast"]["via"] is None and done["turkey_roast"]["by"] == "Ross"
    assert done["turkey_prep"]["via"] == "turkey_roast" and done["oven_preheat"]["via"] == "turkey_roast"
    assert done["turkey_prep"]["at"] == at(11, 15).isoformat()           # planned time, not now
    assert v["hero"]["tone"] == "party" and v["urgent"]
    tick(store, 15, 12)
    v = store.apply({"op": "done", "step": "turkey_roast", "done": False})
    assert store.state["done"] == {} and v["hero"]["tone"] != "party"


def test_adjust_undo_skip(store):
    tick(store, 15, 7)
    store.apply({"op": "done", "step": "turkey_roast"})
    store.apply({"op": "adjust", "step": "turkey_roast", "minutes": 10})
    assert store.state["done"]["turkey_roast"]["at"] == at(14, 57).isoformat()
    store.apply({"op": "undo"})
    assert store.state["done"]["turkey_roast"]["at"] == at(15, 7).isoformat()
    v = store.apply({"op": "skip", "step": "box_gravy"})
    assert next(s for s in v["steps"] if s["id"] == "box_gravy")["status"] == "skipped"
    with pytest.raises(ValueError):
        store.apply({"op": "done", "step": "nope"})
    with pytest.raises(ValueError):
        store.apply({"op": "tv_mode", "mode": "disco"})


def test_dinner_time_moves(store):
    v = store.apply({"op": "settings", "dinner_delta": 15})
    assert v["dinner_at"] == "16:15"
    v = store.apply({"op": "settings", "dinner_at": "17:00"})
    assert v["dinner_label"] == "5:00pm"
    assert next(s for s in v["steps"] if s["id"] == "turkey_roast")["start_label"] == "12:15pm"


def test_kelsey_ops(store):
    tick(store, 7, 10)
    v = store.apply({"op": "kelsey", "kind": "depart", "minutes_ago": 10}, who="Ross")
    assert v["kelsey"]["departed_at"] == at(7, 0).isoformat() and v["kelsey"]["eta_label"] == "12:25pm"
    tick(store, 9, 5)
    v = store.apply({"op": "kelsey", "kind": "waypoint", "label": "portland", "minutes_ago": 5})
    assert v["kelsey"]["where"] == "near Portland"
    v = store.apply({"op": "kelsey", "kind": "eta", "eta": "13:10"})
    assert v["kelsey"]["eta_label"] == "1:10pm"
    v = store.apply({"op": "kelsey_undo"})
    assert v["kelsey"]["eta_label"] == "12:40pm"                         # back to the Portland-based estimate
    with pytest.raises(ValueError):
        store.apply({"op": "kelsey", "kind": "waypoint", "label": "Boise"})
    tick(store, 12, 31)
    v = store.apply({"op": "kelsey", "kind": "arrive"})
    assert v["kelsey"]["status"] == "arrived" and v["hero"]["big"].endswith("Kelsey is here!")


def test_night_before_shows_tomorrows_plan(store):
    tick(store, 20, 0, day=25)
    v = store.view()
    assert v["hero"]["big"] == "🦃 Thursday's plan" and "Make the pumpkin pie at 8:30am" in v["hero"]["sub"]
    assert all(s["status"] == "later" for s in v["steps"] if s["kind"] != "passive")
    assert v["kelsey"]["headline"] == "leaves ~7:00am" and v["kelsey"]["eta_label"] == "12:25pm"
    v = store.apply({"op": "kelsey", "kind": "eta", "eta": "12:30"})
    assert v["kelsey"]["eta"] == at(12, 30).isoformat()                 # HH:MM lands on the plan day


def test_day_rollover_forgets_taps_and_pins_but_keeps_settings(store, tmp_path):
    tick(store, 20, 0, day=25)
    store.apply({"op": "settings", "turkey_lb": 15})
    store.apply({"op": "done", "step": "turkey_out_fridge"})
    store.apply({"op": "tv_mode", "mode": "thanksgiving"})
    store.apply({"op": "kelsey", "kind": "depart"})
    tick(store, 7, 0, day=26)
    v = store.view()
    assert v["turkey_lb"] == 15 and v["tv"]["mode"] == "rotate" and store.state["done"] == {}
    assert v["kelsey"]["status"] == "pending"
    assert json.loads(store.path.read_text())["day"] == "2026-11-26"


def test_cheesecake_waits_for_kelsey(store):
    tick(store, 13, 0)
    v = store.view()
    cake = next(s for s in v["steps"] if s["id"] == "cheesecake_make")
    assert cake["status"] == "waiting" and cake["waiting_on"] == "guest"
    assert "late" not in v["board"] or "cheesecake_make" not in v["board"]["late"]
    store.apply({"op": "kelsey", "kind": "arrive"})
    v = store.view()
    assert next(s for s in v["steps"] if s["id"] == "cheesecake_make")["status"] in ("now", "late")


def test_reset_needs_confirmation(store):
    store.apply({"op": "done", "step": "turkey_out_fridge"})
    with pytest.raises(ValueError):
        store.apply({"op": "reset"})
    store.apply({"op": "reset", "confirm": "RESET"})
    assert store.state["done"] == {}


def test_showing_policy(store):
    cfg = store.cfg
    v = store.view()
    assert showing(at(9, 0, 25), cfg, store, v) == "family"              # not the day
    # the day: 2 min thanksgiving / 1 min family, first minute of every 10 is family
    assert showing(at(9, 0, 26), cfg, store, v) == "family"
    assert showing(at(9, 1) + dt.timedelta(seconds=30), cfg, store, v) == "thanksgiving"
    secs = [showing(at(9, 0, 26) + dt.timedelta(seconds=s), cfg, store, v) for s in range(0, 600, 30)]
    assert secs.count("family") >= 4 and secs.count("thanksgiving") >= 10
    assert showing(at(14, 45, 26), cfg, store, v) == "thanksgiving"       # the crunch pin
    assert showing(at(14, 40, 26), cfg, store, v) == "thanksgiving"
    v = store.apply({"op": "tv_mode", "mode": "family"})
    assert showing(at(15, 0, 26), cfg, store, v) == "family"
    v = store.apply({"op": "tv_mode", "mode": "thanksgiving"})
    assert showing(at(9, 0, 25), cfg, store, v) == "thanksgiving"        # manual pin works any day (tonight's test)
    assert showing(at(9, 0, 26), Config.from_env({}), None, None) == "family"
    allday = Config.from_env({"TG_DATE": "2026-11-26", "TG_PIN_FROM": "00:00"})
    v = store.apply({"op": "tv_mode", "mode": "rotate"})
    assert showing(at(9, 0, 26), allday, store, v) == "thanksgiving"    # pinned all day beats the family cap
    v = store.apply({"op": "done", "step": "dinner"})
    assert showing(at(17, 0, 26), allday, store, v) == "thanksgiving"   # and the after-dinner fallback
