"""Kelsey's drive: route baseline, taps -> position/ETA, and the chart."""
import datetime as dt

from familydash import kelsey as kz
from tests.conftest import TZ

ROUTE = kz.Route.default("Home", 291, 305)
PLAN = dt.datetime(2026, 11, 26, 7, 0, tzinfo=TZ)


def at(h, m=0):
    return dt.datetime(2026, 11, 26, h, m, tzinfo=TZ)


def ev(kind, h, m=0, **kw):
    return {"at": at(h, m).isoformat(), "by": "Ross", "kind": kind, **kw}


def test_route_baseline():
    assert ROUTE.points[0][0] == "Eugene" and ROUTE.points[-1] == ("Home", 291.0, 305.0)
    assert [c for c, _ in ROUTE.cities] == ["Albany", "Salem", "Portland", "Vancouver", "Kelso", "Centralia", "Olympia",
                                            "Tacoma", "Seattle"]
    assert ROUTE.minutes_at(106) == 105 and round(ROUTE.miles_at(105)) == 106
    assert ROUTE.where(108) == "near Portland" and ROUTE.where(130) == "between Vancouver and Kelso"
    assert kz.Route.default("Home", 255, 255).points[-2][0] == "Tacoma"    # a home before Seattle truncates


def test_pending_shows_the_plan():
    e = kz.estimate(kz.apply([], ROUTE, TZ), ROUTE, at(6, 30), plan_depart=PLAN)
    assert e.status == "pending" and e.eta == at(12, 5) and e.headline == "leaves ~7:00am"
    e = kz.estimate(kz.apply([], ROUTE, TZ), ROUTE, at(7, 20), plan_depart=PLAN)
    assert e.headline == "leaving soon…"


def test_depart_and_waypoint_keep_pace_but_move_the_anchor():
    s = kz.apply([ev("depart", 7, 5, time=at(7, 5).isoformat())], ROUTE, TZ)
    assert s.eta(ROUTE) == at(12, 10)
    s = kz.apply([ev("depart", 7, 5, time=at(7, 5).isoformat()),
                  ev("waypoint", 9, 12, time=at(9, 10).isoformat(), miles=106, label="Portland")], ROUTE, TZ)
    assert s.eta(ROUTE) == at(9, 10) + dt.timedelta(minutes=200)       # 20 min late to Portland = 20 min later home
    e = kz.estimate(s, ROUTE, at(10), ROUTE)
    assert e.status == "driving" and 140 < e.miles < 160 and "updated 48 min ago by Ross" in e.sub


def test_phone_eta_is_honoured_exactly():
    s = kz.apply([ev("depart", 7, 0, time=at(7, 0).isoformat()), ev("eta", 9, 0, eta=at(13, 0).isoformat())], ROUTE, TZ)
    assert s.eta(ROUTE) == at(13, 0) and s.pace > 1
    e = kz.estimate(s, ROUTE, at(12, 50))
    assert e.urgent and e.eta == at(13, 0)


def test_stop_overdue_and_arrival():
    s = kz.apply([ev("depart", 7, 0, time=at(7, 0).isoformat()), ev("stop", 9, 0, minutes=30)], ROUTE, TZ)
    assert kz.estimate(s, ROUTE, at(9, 10)).status == "stopped"
    assert s.eta(ROUTE) == at(12, 35)
    s = kz.apply([ev("depart", 7, 0, time=at(7, 0).isoformat()), ev("eta", 9, 0, eta=at(11, 30).isoformat())], ROUTE, TZ)
    e = kz.estimate(s, ROUTE, at(11, 50))
    assert e.status == "overdue" and e.headline == "Any minute now…" and e.urgent     # never auto-arrives
    s = kz.apply([ev("depart", 7, 0, time=at(7, 0).isoformat()), ev("arrive", 12, 1, time=at(12, 1).isoformat())], ROUTE, TZ)
    e = kz.estimate(s, ROUTE, at(12, 5))
    assert e.status == "arrived" and e.urgent and e.miles == 291


def test_stale_estimate_says_so():
    s = kz.apply([ev("depart", 7, 0, time=at(7, 0).isoformat())], ROUTE, TZ)
    e = kz.estimate(s, ROUTE, at(9, 0))
    assert e.headline.startswith("ETA ~") and "got news?" in e.sub


def test_chart_has_plan_actual_and_car_with_face():
    s = kz.apply([ev("depart", 7, 0, time=at(7, 0).isoformat()),
                  ev("waypoint", 9, 0, time=at(9, 0).isoformat(), miles=106, label="Portland")], ROUTE, TZ)
    e = kz.estimate(s, ROUTE, at(10))
    svg = kz.chart_svg(s, ROUTE, e, at(10), photo="data:image/png;base64,AAAA", plan_depart=PLAN)
    assert svg.count("<polyline") == 2 and '<image href="data:image/png;base64,AAAA"' in svg
    assert ">Home<" in svg and ">Portland<" in svg and ">Eugene<" in svg
    assert 'text-anchor="middle" font-size="24" font-weight="800" fill="#fde68a">' in svg      # the ETA label
    svg = kz.chart_svg(kz.apply([], ROUTE, TZ), ROUTE, kz.estimate(kz.apply([], ROUTE, TZ), ROUTE, at(6), plan_depart=PLAN),
                       at(6), photo=None, plan_depart=PLAN)
    assert ">K</text>" in svg and svg.count("<polyline") == 1


def test_photo_uri(tmp_path):
    p = tmp_path / "kelsey.jpg"
    p.write_bytes(b"\xff\xd8xx")
    assert kz.photo_uri(p).startswith("data:image/jpeg;base64,")
    assert kz.photo_uri(tmp_path / "nope.png") is None
    big = tmp_path / "big.png"
    big.write_bytes(b"0" * 300_000)
    assert kz.photo_uri(big) is None
