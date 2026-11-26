"""Thanksgiving day state: one JSON file on the data volume, edited by small explicit
ops from phones, read by the TV render. Everything shown is derived in view()."""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
from pathlib import Path

from . import kelsey as kz
from . import thanksgiving as tg
from .config import Config

UNDO_DEPTH = 20
MODES = ("rotate", "thanksgiving", "family")


def _iso(t: dt.datetime) -> str:
    return t.replace(microsecond=0).isoformat()


def fresh_state(cfg: Config, today: dt.date) -> dict:
    return {"day": (cfg.tg_date or today).isoformat(), "dinner_at": cfg.tg_dinner_at.strftime("%H:%M"),
            "turkey_lb": cfg.tg_turkey_lb, "convection": False, "tv_mode": "rotate", "done": {}, "skipped": [],
            "kelsey": {"events": []}, "celebrate": None, "undo": []}


class Store:
    """Lock-serialised state with atomic writes, a .bak, an undo stack and day scoping
    (test taps from the night before vanish on Thanksgiving morning)."""

    def __init__(self, cfg: Config, plan: dict | None = None, clock=None):
        self.cfg = cfg
        self.plan = plan or tg.load_plan()
        self.path = Path(cfg.data_dir) / "thanksgiving.json"
        self.lock = threading.Lock()
        self.changed = threading.Event()
        self.clock = clock or (lambda: dt.datetime.now(cfg.tz))
        self.state = self._load()
        self._photo: tuple[float, str | None] = (0.0, None)

    def photo(self) -> str | None:
        """Kelsey's face as a data: URI (KELSEY_PHOTO, else <data_dir>/kelsey.jpg|png), cached by mtime."""
        candidates = [Path(self.cfg.kelsey_photo)] if self.cfg.kelsey_photo else \
            [Path(self.cfg.data_dir) / n for n in ("kelsey.jpg", "kelsey.jpeg", "kelsey.png")]
        path = next((p for p in candidates if p.exists()), None)
        mtime = path.stat().st_mtime if path else 0.0
        if mtime != self._photo[0]:
            self._photo = (mtime, kz.photo_uri(path))
        return self._photo[1]

    # -- persistence ---------------------------------------------------------------
    def _load(self) -> dict:
        for p in (self.path, self.path.with_suffix(".bak")):
            try:
                if p.exists():
                    s = json.loads(p.read_text())
                    if isinstance(s, dict) and "done" in s:
                        return s
            except Exception:
                pass
        return fresh_state(self.cfg, self.clock().date())

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1))
        if self.path.exists():
            try:
                os.replace(self.path, self.path.with_suffix(".bak"))
            except OSError:
                pass
        os.replace(tmp, self.path)

    def day(self, now: dt.datetime) -> dt.date:
        """The day the meal is planned for: TG_DATE (so the night before shows tomorrow's
        plan, not a day-late one), else today."""
        return self.cfg.tg_date or now.date()

    def _roll_day(self, now: dt.datetime) -> None:
        """Settings survive; taps and TV pins do not: a changed TG_DATE starts fresh, and
        anything tapped while trying it out the night before vanishes on the morning."""
        day = self.day(now)
        wipe = self.state.get("day") != day.isoformat()
        if self.state.get("prepped_early") and now.date() >= day:
            wipe = True
        if wipe:
            keep = {k: self.state.get(k) for k in ("dinner_at", "turkey_lb", "convection")}
            self.state = {**fresh_state(self.cfg, now.date()), **{k: v for k, v in keep.items() if v is not None}}
            self._save()

    # -- ops -----------------------------------------------------------------------
    def apply(self, op: dict, who: str = "") -> dict:
        now = self.clock()
        with self.lock:
            self._roll_day(now)
            before = json.dumps({k: v for k, v in self.state.items() if k != "undo"})
            try:
                self._apply(op, now, who)
            except (KeyError, ValueError, TypeError) as e:
                raise ValueError(f"bad op: {e}") from e
            if op.get("op") not in ("undo", "tv_mode"):
                self.state.setdefault("undo", []).append(before)
                self.state["undo"] = self.state["undo"][-UNDO_DEPTH:]
            if now.date() < self.day(now) and op.get("op") not in ("settings", "undo", "reset"):
                self.state["prepped_early"] = True
            self._save()
        self.changed.set()
        return self.view(now)

    def _steps(self, now: dt.datetime) -> list[tg.Step]:
        done = {k: v["at"] for k, v in self.state["done"].items()}
        return tg.schedule(self.plan, self.dinner_at(now), {**self.state, "done": done}, now=now)

    def dinner_at(self, now: dt.datetime) -> dt.datetime:
        h, m = (int(x) for x in self.state["dinner_at"].split(":"))
        return dt.datetime.combine(self.day(now), dt.time(h, m), tzinfo=now.tzinfo)

    def _apply(self, op: dict, now: dt.datetime, who: str) -> None:
        s, kind = self.state, op["op"]
        if kind == "done":
            sid = op["step"]
            steps = tg.by_id(self._steps(now))
            if sid not in steps or not steps[sid].checkable:
                raise ValueError(f"unknown step {sid}")
            if op.get("done", True):
                at = _parse_when(op.get("at"), now, self.day(now)) if op.get("at") else now
                s["done"][sid] = {"at": _iso(at), "via": None, "by": who}
                # implied completion: earlier required steps of the same dish, at their planned time
                for other in sorted(steps.values(), key=lambda x: x.start):
                    if (other.dish_id == steps[sid].dish_id and other.id != sid and other.checkable and not other.optional
                            and other.start <= steps[sid].start and other.id not in s["done"]):
                        s["done"][other.id] = {"at": _iso(min(other.end, at)), "via": sid, "by": who}
                s["skipped"] = [x for x in s["skipped"] if x != sid]
                if sid in ("turkey_prep", "turkey_roast", "dinner"):
                    s["celebrate"] = {"kind": sid, "at": _iso(now)}
            else:
                s["done"].pop(sid, None)
                for k in [k for k, v in s["done"].items() if v.get("via") == sid]:
                    s["done"].pop(k, None)
                if s.get("celebrate", {}) and s["celebrate"].get("kind") == sid:
                    s["celebrate"] = None
        elif kind == "adjust":                                   # nudge a done time earlier (tap landed late)
            sid, minutes = op["step"], int(op["minutes"])
            if sid in s["done"]:
                at = dt.datetime.fromisoformat(s["done"][sid]["at"]) - dt.timedelta(minutes=minutes)
                s["done"][sid]["at"] = _iso(at)
        elif kind == "skip":
            sid = op["step"]
            if op.get("skipped", True):
                if sid not in s["skipped"]:
                    s["skipped"].append(sid)
            else:
                s["skipped"] = [x for x in s["skipped"] if x != sid]
        elif kind == "settings":
            if "dinner_at" in op:
                dt.time.fromisoformat(op["dinner_at"])
                s["dinner_at"] = op["dinner_at"][:5]
            if "dinner_delta" in op:
                t = self.dinner_at(now) + dt.timedelta(minutes=int(op["dinner_delta"]))
                s["dinner_at"] = t.strftime("%H:%M")
            if "turkey_lb" in op:
                s["turkey_lb"] = max(6.0, min(30.0, float(op["turkey_lb"])))
            if "convection" in op:
                s["convection"] = bool(op["convection"])
        elif kind == "kelsey":
            ev = {"at": _iso(now), "by": who, "kind": op["kind"]}
            when = now - dt.timedelta(minutes=int(op.get("minutes_ago") or 0))
            if op["kind"] in ("depart", "arrive"):
                ev["time"] = _iso(_parse_when(op.get("time"), now, self.day(now)) if op.get("time") else when)
            elif op["kind"] == "waypoint":
                route = self.route()
                label = op["label"]
                miles = next((m for lbl, m in route.cities if lbl.lower() == label.lower()), None)
                if miles is None:
                    raise ValueError(f"unknown waypoint {label}")
                ev.update(time=_iso(when), miles=miles, label=label)
            elif op["kind"] == "eta":
                ev["eta"] = _iso(_parse_when(op["eta"], now, self.day(now)))
            elif op["kind"] == "stop":
                ev["minutes"] = max(1, min(180, int(op["minutes"])))
            else:
                raise ValueError(f"unknown kelsey event {op['kind']}")
            s["kelsey"]["events"].append(ev)
            if op["kind"] == "arrive":
                s["celebrate"] = {"kind": "kelsey", "at": _iso(now)}
        elif kind == "kelsey_undo":
            if s["kelsey"]["events"]:
                s["kelsey"]["events"].pop()
        elif kind == "undo":
            if s.get("undo"):
                prev = json.loads(s["undo"].pop())
                prev["undo"] = s["undo"]
                self.state = prev
        elif kind == "tv_mode":
            if op["mode"] not in MODES:
                raise ValueError("mode")
            s["tv_mode"] = op["mode"]
        elif kind == "reset":
            if op.get("confirm") != "RESET":
                raise ValueError("confirm")
            self.state = fresh_state(self.cfg, now.date())
        else:
            raise ValueError(f"unknown op {kind}")

    # -- derived -------------------------------------------------------------------
    def route(self) -> kz.Route:
        return kz.Route.default("Home", self.cfg.kelsey_home_miles, self.cfg.kelsey_home_minutes)

    def plan_depart(self, now: dt.datetime) -> dt.datetime | None:
        t = self.cfg.kelsey_plan_depart
        return dt.datetime.combine(self.day(now), t, tzinfo=now.tzinfo) if t else None

    def view(self, now: dt.datetime | None = None) -> dict:
        now = now or self.clock()
        with self.lock:
            self._roll_day(now)
            st = json.loads(json.dumps(self.state))
        done_simple = {k: v["at"] for k, v in st["done"].items()}
        dinner = self.dinner_at(now)
        steps = tg.schedule(self.plan, dinner, {**st, "done": done_simple}, now=now)
        skipped = set(st["skipped"])
        for s in steps:
            if s.id in skipped and s.status != "done":
                s.status = "skipped"
        bd = tg.board(steps, now, dinner)
        route = self.route()
        sched = kz.apply(st["kelsey"]["events"], route, self.cfg.tz)
        est = kz.estimate(sched, route, now, self.cfg.kelsey_name, self.plan_depart(now))
        celebrate = st.get("celebrate")
        if celebrate and (now - dt.datetime.fromisoformat(celebrate["at"])) > dt.timedelta(minutes=4):
            celebrate = None
        hero = self.hero(bd, steps, now, dinner, celebrate, est)
        due_soon = any(0 <= (s.start - now).total_seconds() <= 180 for s in steps if s.checkable and s.status == "soon")
        overdue = any(s.status == "late" and (now - s.end) < dt.timedelta(minutes=10) for s in steps)
        urgent = bool(due_soon or overdue or est.urgent or celebrate)
        proj = bd["projected_dinner_at"]
        proj = proj if (proj - dinner) > dt.timedelta(minutes=5) else None
        if proj:
            proj = proj + dt.timedelta(minutes=(-proj.minute) % 5)
        return {
            "now": _iso(now), "day": st["day"], "dinner_at": st["dinner_at"], "dinner_label": kz.fmt(dinner),
            "projected_dinner_at": proj.strftime("%H:%M") if proj else None,
            "projected_label": kz.fmt(proj) if proj else None,
            "behind_minutes": bd["behind_minutes"], "turkey_lb": st["turkey_lb"], "convection": st["convection"],
            "roast_minutes": tg.roast_minutes(st["turkey_lb"], st["convection"]),
            "finished": bd["finished"], "hero": hero, "celebrate": celebrate,
            "steps": [step_dict(s, now, st["done"].get(s.id)) for s in steps],
            "board": {k: [s.id for s in bd[k]] for k in ("late", "now", "next")},
            "progress": {"done": bd["done"], "total": bd["total"]},
            "conflicts": [c["msg"] for c in tg.resource_conflicts(steps)],
            "kelsey": {"name": self.cfg.kelsey_name, "status": est.status, "eta": _iso(est.eta) if est.eta else None,
                       "eta_label": kz.fmt(est.eta), "miles": round(est.miles), "remaining_miles": round(est.remaining_miles),
                       "where": est.where, "headline": est.headline, "sub": est.sub, "urgent": est.urgent,
                       "cities": [c[0] for c in route.cities], "events": st["kelsey"]["events"][-6:],
                       "departed_at": _iso(sched.departed_at) if sched.departed_at else None,
                       "arrived_at": _iso(sched.arrived_at) if sched.arrived_at else None,
                       "plan_depart": kz.fmt(self.plan_depart(now)) if self.plan_depart(now) else None,
                       "svg": kz.chart_svg(sched, route, est, now, self.cfg.kelsey_name, self.photo(), self.plan_depart(now),
                                           w=780, h=440, compact=True)},
            "urgent": urgent,
            "tv": {"mode": st["tv_mode"]},
            "undo_depth": len(st.get("undo", [])),
            "_steps": steps, "_sched": sched, "_est": est, "_route": route, "_dinner": dinner,
            "_plan_depart": self.plan_depart(now),
        }

    def hero(self, bd: dict, steps: list, now: dt.datetime, dinner: dt.datetime, celebrate, est) -> dict:
        """The one big line on the TV, plus a sub-line."""
        by = tg.by_id(steps)
        if celebrate:
            msgs = {"turkey_prep": ("🦃 Turkey's in the oven!", f"out around {kz.fmt(by['turkey_roast'].end)}"),
                    "turkey_roast": ("🦃 Turkey is OUT!", "tent it with foil · stuffing in · gravy time"),
                    "kelsey": (f"🎉 {self.cfg.kelsey_name} is here!", "go say hi"),
                    "dinner": ("🍽️ Dinner is served!", "Happy Thanksgiving")}
            if celebrate["kind"] in msgs:
                return {"big": msgs[celebrate["kind"]][0], "sub": msgs[celebrate["kind"]][1], "tone": "party"}
        if bd["finished"]:
            served = by["dinner"].done_at
            return {"big": f"🍽️ Dinner was served at {kz.fmt(served)}", "sub": "Happy Thanksgiving · thanks, everyone",
                    "tone": "done"}
        if bd["late"]:
            s = max(bd["late"], key=lambda x: x.end)          # the most recent miss is the actionable one
            mins = int((now - s.end).total_seconds() // 60)
            late = f"{mins} min ago" if mins < 90 else f"{mins // 60}h {mins % 60:02d}m ago"
            who = f" · {s.who}" if s.who else ""
            return {"big": f"{s.emoji} {s.label}", "sub": f"was due {kz.fmt(s.end)} · {late}{who}", "tone": "late"}
        roast = by.get("turkey_roast")
        if roast and roast.done_at and not by["turkey_carve"].done_at:
            carve = by["turkey_carve"]
            mins = max(0, int((carve.start - now).total_seconds() // 60))
            return {"big": "🦃 Turkey is resting", "sub": f"carve at {kz.fmt(carve.start)} · in {mins} min", "tone": "calm"}
        if bd["now"]:
            s = bd["now"][0]
            if s.status == "waiting":
                return {"big": f"{s.emoji} {s.label}", "sub": f"as soon as the {by[s.waiting_on].dish.lower()} is done",
                        "tone": "calm"}
            left = max(0, int((s.end - now).total_seconds() // 60))
            return {"big": f"{s.emoji} {s.label}", "sub": f"{left} min left" + (f" · {s.who}" if s.who else ""), "tone": "now"}
        if bd["next"]:
            s = bd["next"][0]
            mins = int((s.start - now).total_seconds() // 60)
            when = f"in {mins} min" if mins < 90 else f"at {kz.fmt(s.start)}"
            if now.date() < dinner.date():
                return {"big": f"🦃 {dinner:%A}'s plan",
                        "sub": f"dinner at {kz.fmt(dinner)} · first: {s.label} at {kz.fmt(s.start)}", "tone": "calm"}
            return {"big": "🦃 Happy Thanksgiving",
                    "sub": f"dinner at {kz.fmt(dinner)} · next: {s.label} {when}", "tone": "calm"}
        return {"big": "🦃 Happy Thanksgiving", "sub": f"dinner at {kz.fmt(dinner)}", "tone": "calm"}


def step_dict(s: tg.Step, now: dt.datetime, done: dict | None) -> dict:
    return {"id": s.id, "dish": s.dish, "dish_id": s.dish_id, "emoji": s.emoji, "color": s.color, "label": s.label,
            "check_label": s.check_label, "kind": s.kind, "resource": s.resource, "temp": s.temp, "notes": s.notes,
            "optional": s.optional, "who": s.who, "start": _iso(s.start), "end": _iso(s.end),
            "start_label": kz.fmt(s.start), "end_label": kz.fmt(s.end), "minutes": int(s.duration / tg.MIN),
            "status": s.status, "waiting_on": s.waiting_on, "done_at": done and done.get("at"),
            "done_label": kz.fmt(dt.datetime.fromisoformat(done["at"])) if done else None,
            "via": done and done.get("via"), "by": done and done.get("by"),
            "minutes_to_start": int((s.start - now).total_seconds() // 60)}


def _parse_when(value: str, now: dt.datetime, day: dt.date | None = None) -> dt.datetime:
    """'15:15' (on the plan day, local) or a full ISO time."""
    if len(value) <= 5:
        return dt.datetime.combine(day or now.date(), dt.time.fromisoformat(value), tzinfo=now.tzinfo)
    d = dt.datetime.fromisoformat(value)
    return d if d.tzinfo else d.replace(tzinfo=now.tzinfo)


def showing(now: dt.datetime, cfg: Config, store: Store | None, view: dict | None) -> str:
    """Which image the TV gets for /dashboard.jpg: 'family' or 'thanksgiving'."""
    if store is None or not cfg.tg_enabled or view is None:
        return "family"
    mode = view["tv"]["mode"]
    if mode == "family":
        return "family"
    if mode == "thanksgiving":
        return "thanksgiving"
    if now.date() != cfg.tg_date:
        return "family"
    ts = int(now.timestamp())
    if cfg.tg_pin_from and now.time() >= cfg.tg_pin_from:
        return "thanksgiving"                                          # pinned (TG_PIN_FROM=00:00 = all day)
    if view.get("finished"):
        return "family" if ts % 600 >= 120 else "thanksgiving"       # after dinner: mostly the family screen
    if ts % 600 < 60:
        return "family"                                                # the kids' stars always come back
    if view.get("urgent"):
        return "thanksgiving"
    a, b = cfg.tg_rotate
    return "thanksgiving" if ts % (a + b) < a else "family"
