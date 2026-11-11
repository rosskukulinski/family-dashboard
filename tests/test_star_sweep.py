import datetime as dt

import pytest

from familydash.star_sweep import due, sweep


class FakeSky:
    def __init__(self, ada, max_, fam, fail_family=0):
        self.bal = {"10": ada, "11": max_, "12": fam}
        self.fail = fail_family

    def get(self, path):
        if path.endswith("categories"):
            return {"data": [{"id": i, "attributes": {"label": n}} for i, n in (("10", "Ada"), ("11", "Max"), ("12", "family"))]}
        return [{"category_id": int(k), "current_point_balance": v} for k, v in self.bal.items()]

    def add_points(self, cid, n):
        if cid == "12" and self.fail:
            self.fail -= 1
            raise RuntimeError("boom")
        self.bal[cid] += n


def run(sky):
    return sweep(sky, ["Ada", "Max"], "family", sleep=lambda _: None, log=lambda _: None)


def test_moves_everything_to_family():
    r = run(FakeSky(4, 5, 18))
    assert r["moved"] == {"Ada": 4, "Max": 5} and r["ok"]
    assert r["after"] == {"Ada": 0, "Max": 0, "family": 27}


def test_kid_with_nothing_is_skipped():
    r = run(FakeSky(3, 0, 0))
    assert r["moved"] == {"Ada": 3} and r["after"]["family"] == 3


def test_family_add_is_retried():
    assert run(FakeSky(2, 2, 0, fail_family=1))["after"]["family"] == 4


def test_failure_never_creates_stars_and_is_reported():
    r = run(FakeSky(2, 2, 0, fail_family=3))
    assert not r["ok"] and r["family_added"] == 0 and r["after"] == {"Ada": 0, "Max": 0, "family": 0}


def test_missing_profile_raises():
    with pytest.raises(RuntimeError):
        sweep(FakeSky(1, 1, 1), ["Ada", "Zed"], "family")


def test_due_once_per_day():
    t = dt.time(22, 0)
    assert not due(dt.datetime(2026, 11, 9, 21, 59), t, None)
    assert due(dt.datetime(2026, 11, 9, 22, 0), t, None)
    assert not due(dt.datetime(2026, 11, 9, 23, 0), t, "2026-11-09")
    assert due(dt.datetime(2026, 11, 10, 22, 30), t, "2026-11-09")
