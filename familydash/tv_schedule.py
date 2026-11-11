"""TV on/off schedule + dashboard keep-alive, via the Roku External Control Protocol
(ECP, port 8060).

  * tv_on_at (07:00): power the TV on and open the dashboard, once per day. The launch
    waits tv_wake_settle seconds after PowerOn - launching while the TV is still waking
    leaves the app "pended without render" (stuck on its loading text) - and is repeated
    once a few minutes later as a safety net.
  * Daytime: if the TV sits on the Roku home screen for tv_home_idle_min minutes, reopen
    the dashboard. Any screensaver over the dashboard is dismissed (it's pointless there).
    Other apps and inputs are never interrupted.
  * From tv_off_at (20:00) until tv_on_at: power off when showing the dashboard or the home
    screen. In another app, power off only after nothing has played for tv_off_idle_min
    minutes. HDMI / antenna inputs are left alone (can't tell if a console is in use).

Requires on the TV: Settings > System > Advanced system settings > Control by mobile
apps > Network access = Permissive, and Power > Fast TV start = on.
"""
from __future__ import annotations

import datetime as dt
import re
import time
import traceback
import urllib.request
from collections.abc import Callable

from .config import Config

DASH_APP = "dev"        # a side-loaded Roku app always has the id "dev"
POLL = 15               # seconds; cheap local queries, keeps glitches short
SAFETY_RELAUNCH = 180   # seconds after the morning launch


class Roku:
    """Tiny ECP client."""

    def __init__(self, ip: str, timeout: float = 5):
        self.base, self.timeout = f"http://{ip}:8060", timeout

    def get(self, path: str) -> str:
        with urllib.request.urlopen(f"{self.base}/{path}", timeout=self.timeout) as r:
            return r.read().decode("utf-8", "replace")

    def post(self, path: str) -> None:
        req = urllib.request.Request(f"{self.base}/{path}", data=b"", method="POST")
        urllib.request.urlopen(req, timeout=self.timeout).close()

    def state(self) -> dict:
        return parse_state(self.get("query/device-info"),
                           lambda: self.get("query/active-app"),
                           lambda: self.get("query/media-player"))


def parse_state(device_info: str, active_app: Callable[[], str], media_player: Callable[[], str]) -> dict:
    power = (re.search(r"<power-mode>([^<]+)", device_info) or [None, "?"])[1]
    if power != "PowerOn":
        return {"power": power}
    app = active_app()
    m = re.search(r'<app id="([^"]+)"', app)
    ss = re.search(r'<screensaver id="([^"]+)"', app)
    return {
        "power": power,
        "app": m.group(1) if m else "home",          # no id = Roku home screen
        "screensaver": ss.group(1) if ss else ("other" if "<screensaver" in app else None),
        "playing": 'state="play"' in media_player(),
    }


def is_input(app: str) -> bool:
    return app.startswith("tvinput.")               # HDMI / antenna / AV


class Scheduler:
    def __init__(self, cfg: Config, tv, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, log: Callable[[str], None] = print):
        self.cfg, self.tv, self.clock, self.sleep, self.log = cfg, tv, clock, sleep, log
        self.powered_on_for: dt.date | None = None
        self.home_since: float | None = None
        self.idle_since: float | None = None
        self.relaunch_at: float | None = None

    def fresh_launch(self) -> None:
        """Back out to Home first so the dashboard starts from scratch, then open it."""
        self.log("open dashboard (fresh)")
        self.tv.post("keypress/Home")
        self.sleep(4)
        self.tv.post(f"launch/{DASH_APP}")

    def tick(self, now: dt.datetime) -> None:
        c = self.cfg
        daytime = c.tv_on_at <= now.time() < c.tv_off_at
        s = self.tv.state()
        on = s["power"] == "PowerOn"

        if daytime and self.powered_on_for != now.date():
            self.powered_on_for = now.date()      # once per day, even if it fails
            if not on:
                self.log(f"morning: power on (was {s['power']})")
                self.tv.post("keypress/PowerOn")
                self.sleep(c.tv_wake_settle)
            self.fresh_launch()
            self.relaunch_at = self.clock() + SAFETY_RELAUNCH
            return

        if self.relaunch_at and self.clock() >= self.relaunch_at:
            self.relaunch_at = None
            if on and s.get("app") == DASH_APP:
                self.log("morning: safety relaunch")
                self.fresh_launch()
            return

        if not on:
            self.home_since = self.idle_since = None
            return
        app = s["app"]

        if daytime:
            self.idle_since = None
            if app == DASH_APP and s["screensaver"]:
                self.log(f"screensaver {s['screensaver']} over dashboard: dismiss")
                self.tv.post("keypress/Lit_a")       # harmless key the dashboard ignores
            if app == "home":
                self.home_since = self.home_since or self.clock()
                if self.clock() - self.home_since >= c.tv_home_idle_min * 60:
                    self.log(f"home screen idle {c.tv_home_idle_min}m: reopen dashboard")
                    self.tv.post(f"launch/{DASH_APP}")
                    self.home_since = None
            else:
                self.home_since = None
            return

        # evening / night
        self.home_since = None
        if app in (DASH_APP, "home"):
            self.log(f"evening: power off (on {app})")
            self.tv.post("keypress/PowerOff")
            self.idle_since = None
        elif is_input(app) or s["playing"]:
            self.idle_since = None
        else:
            self.idle_since = self.idle_since or self.clock()
            if self.clock() - self.idle_since >= c.tv_off_idle_min * 60:
                self.log(f"evening: nothing playing in {app} for {c.tv_off_idle_min}m: power off")
                self.tv.post("keypress/PowerOff")
                self.idle_since = None


def run_forever(cfg: Config) -> None:
    def log(msg: str) -> None:
        print(f"{dt.datetime.now(cfg.tz):%H:%M:%S} tv: {msg}", flush=True)

    sched = Scheduler(cfg, Roku(cfg.roku_ip), log=log)
    now = dt.datetime.now(cfg.tz)
    if now.time() >= cfg.tv_on_at:
        sched.powered_on_for = now.date()        # don't fire "morning" on a mid-day restart
    log(f"schedule: on {cfg.tv_on_at:%H:%M}, off {cfg.tv_off_at:%H:%M} (TV {cfg.roku_ip})")
    while True:
        try:
            sched.tick(dt.datetime.now(cfg.tz))
        except Exception as e:
            log(f"error: {e!r}")
            if not isinstance(e, OSError):
                traceback.print_exc()
        time.sleep(POLL)
