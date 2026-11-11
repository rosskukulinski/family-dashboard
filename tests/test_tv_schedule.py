import datetime as dt

import pytest

from familydash.tv_schedule import DASH_APP, Scheduler, parse_state
from tests.conftest import at, make_cfg


class FakeTV:
    def __init__(self, **state):
        self.s, self.calls = state, []

    def state(self):
        return dict(self.s)

    def post(self, path):
        self.calls.append(path)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def sched(tv, clock=None):
    s = Scheduler(make_cfg(), tv, clock=clock or Clock(), sleep=lambda _: None, log=lambda _: None)
    s.powered_on_for = dt.date(2026, 11, 9)       # morning already done unless a test resets it
    return s


ON = dict(power="PowerOn", screensaver=None, playing=False)


def test_morning_waits_after_power_on_then_relaunches_once():
    tv, clock = FakeTV(power="Ready"), Clock()
    s = sched(tv, clock)
    s.powered_on_for = None
    slept = []
    s.sleep = slept.append
    s.tick(at(7))
    assert tv.calls == ["keypress/PowerOn", "keypress/Home", f"launch/{DASH_APP}"] and 60 in slept
    tv.s, tv.calls = dict(ON, app=DASH_APP), []
    clock.t += 60
    s.tick(at(7, 1))
    assert tv.calls == []
    clock.t += 130
    s.tick(at(7, 3))
    assert tv.calls == ["keypress/Home", f"launch/{DASH_APP}"]           # safety relaunch
    tv.calls = []
    s.tick(at(7, 4))
    assert tv.calls == []


def test_manual_off_during_day_stays_off():
    tv = FakeTV(power="Ready")
    sched(tv).tick(at(12))
    assert tv.calls == []


@pytest.mark.parametrize("screensaver", ["dev", "other"])
def test_any_screensaver_over_dashboard_is_dismissed(screensaver):
    tv = FakeTV(**dict(ON, app=DASH_APP, screensaver=screensaver))
    sched(tv).tick(at(12))
    assert tv.calls == ["keypress/Lit_a"]


def test_home_screen_reopens_dashboard_after_idle():
    tv, clock = FakeTV(**dict(ON, app="home")), Clock()
    s = sched(tv, clock)
    s.tick(at(12))
    assert tv.calls == []
    clock.t += 6 * 60
    s.tick(at(12, 6))
    assert tv.calls == [f"launch/{DASH_APP}"]


def test_other_apps_are_never_interrupted_in_the_day():
    tv = FakeTV(**dict(ON, app="12"))
    sched(tv).tick(at(12))
    assert tv.calls == []


@pytest.mark.parametrize("app", [DASH_APP, "home"])
def test_evening_powers_off_dashboard_or_home(app):
    tv = FakeTV(**dict(ON, app=app))
    sched(tv).tick(at(20))
    assert tv.calls == ["keypress/PowerOff"]


def test_evening_waits_for_idle_in_other_apps_and_ignores_inputs():
    clock = Clock()
    playing = FakeTV(**dict(ON, app="12", playing=True))
    sched(playing, clock).tick(at(21))
    assert playing.calls == []
    hdmi = FakeTV(**dict(ON, app="tvinput.hdmi1"))
    s = sched(hdmi, clock)
    s.tick(at(21))
    clock.t += 3600
    s.tick(at(22))
    assert hdmi.calls == []
    paused = FakeTV(**dict(ON, app="12"))
    s = sched(paused, clock)
    s.tick(at(21))
    clock.t += 16 * 60
    s.tick(at(21, 16))
    assert paused.calls == ["keypress/PowerOff"]


def test_parse_state():
    info = "<power-mode>PowerOn</power-mode>"
    st = parse_state(info, lambda: '<app id="dev" type="appl">D</app><screensaver id="dev" type="ssvr">D</screensaver>',
                     lambda: '<player state="play">')
    assert st == {"power": "PowerOn", "app": "dev", "screensaver": "dev", "playing": True}
    assert parse_state(info, lambda: "<app>Roku</app>", lambda: "")["app"] == "home"
    assert parse_state("<power-mode>Ready</power-mode>", None, None) == {"power": "Ready"}
