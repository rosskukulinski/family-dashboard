"""Thanksgiving cooking timeline engine. Pure functions, stdlib only.

A *plan* (JSON, see thanksgiving_plan.json) lists dishes -> steps. Each step's timing is
given by any two of start / end / duration:
  * a number                                   minutes relative to dinner time T (negative = before)
  * {"var": "roast", "scale": s, "plus": p}    minutes relative to T, computed from a variable
  * {"ref": step_id, "edge": "start"|"end", "delta": n}   relative to another step
  * {"max": [spec, spec]}                      the later of several
A step whose start follows another step's *end* is "anchored": once that step is checked
off, the anchored step re-flows from the actual time instead of the plan (so one tap,
"Turkey is OUT", re-times the rest, the gravy, the stuffing and the carving).
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

MIN = dt.timedelta(minutes=1)
PLAN_PATH = Path(__file__).parent / "thanksgiving_plan.json"

# USDA/FSIS chart for an UNSTUFFED turkey at 325°F (upper bound of each range, so the
# plan errs toward "done early, rest longer" rather than "late"):
#   8-12 lb 2¾-3h · 12-14 3-3¾h · 14-18 3¾-4¼h · 18-20 4¼-4½h · 20-24 4½-5h
ROAST_TABLE = [(8, 165), (12, 180), (14, 225), (18, 255), (20, 270), (24, 300)]
LATE_GRACE = 5 * MIN     # how far past a step's end before we nag
SOON_LEAD = 15 * MIN     # "starting soon" window


def load_plan(path: Path = PLAN_PATH) -> dict:
    return json.loads(path.read_text())


def roast_minutes(turkey_lb: float, convection: bool = False) -> int:
    """Planned oven time for an unstuffed bird at 325°F, interpolated on the USDA chart.
    Convection ovens run ~25% faster."""
    lb = max(6.0, float(turkey_lb))
    if lb <= ROAST_TABLE[0][0]:
        mins = ROAST_TABLE[0][1] * lb / ROAST_TABLE[0][0]
    elif lb >= ROAST_TABLE[-1][0]:
        mins = ROAST_TABLE[-1][1] + (lb - ROAST_TABLE[-1][0]) * 12.5
    else:
        for (lb0, m0), (lb1, m1) in zip(ROAST_TABLE, ROAST_TABLE[1:], strict=False):
            if lb0 <= lb <= lb1:
                mins = m0 + (m1 - m0) * (lb - lb0) / (lb1 - lb0)
                break
    if convection:
        mins *= 0.75
    return int(round(mins / 5.0) * 5)


@dataclass
class Step:
    id: str
    dish_id: str
    dish: str
    emoji: str
    color: str
    label: str
    check_label: str
    kind: str                      # active | passive | milestone
    resource: str                  # oven | stovetop | counter | none
    temp: int | None
    notes: str
    optional: bool
    who: str
    after_guest: bool
    start: dt.datetime
    end: dt.datetime
    anchored_to: str | None        # step id whose actual completion re-flows this one
    done_at: dt.datetime | None = None
    status: str = "later"          # done | late | missed (optional) | now | waiting | soon | later; passive: running/past/later
    waiting_on: str | None = None

    @property
    def duration(self) -> dt.timedelta:
        return self.end - self.start

    @property
    def checkable(self) -> bool:
        return self.kind != "passive"


def _vars(params: dict) -> dict:
    return {"roast": roast_minutes(params.get("turkey_lb", 14), params.get("convection", False)),
            "turkey_lb": float(params.get("turkey_lb", 14))}


def _minutes(spec, variables: dict) -> int:
    """Whole minutes (a schedule that says 2:03:45 helps nobody)."""
    if isinstance(spec, dict):
        return round(variables[spec["var"]] * spec.get("scale", 1) + spec.get("plus", 0))
    return round(float(spec))


def _parse(s: str, tz) -> dt.datetime:
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=tz)


def _refs(spec) -> list[dict]:
    """Every {"ref": ...} inside a timing spec."""
    if not isinstance(spec, dict):
        return []
    if "ref" in spec:
        return [spec]
    return [r for s in spec.get("max", []) for r in _refs(s)]


def steps_in_plan(plan: dict) -> list[tuple[dict, dict]]:
    return [(d, s) for d in plan["dishes"] for s in d["steps"]]


def schedule(plan: dict, dinner_at: dt.datetime, state: dict | None = None,
             now: dt.datetime | None = None) -> list[Step]:
    """Absolute times for every step, re-flowed by what has actually been checked off.

    state = {"turkey_lb": 14, "convection": false, "done": {step_id: iso_time}}
    An anchored step whose anchor isn't done yet never starts before `now` (it is
    "waiting", not "late"); the anchor itself is what goes late.
    """
    state = state or {}
    params = {**plan.get("params", {}), **{k: v for k, v in state.items() if k in ("turkey_lb", "convection")}}
    variables = _vars(params)
    tz = dinner_at.tzinfo
    done = {k: _parse(v, tz) for k, v in (state.get("done") or {}).items()}
    # a check made before the day (trying it out the night before) still counts as done,
    # but must not pull tomorrow's anchored steps into tonight
    day_start = dinner_at.replace(hour=0, minute=0, second=0, microsecond=0)
    anchors = {k: v for k, v in done.items() if v >= day_start}
    raw: dict[str, dict] = {}
    dishes: dict[str, dict] = {}
    for d, s in steps_in_plan(plan):
        raw[s["id"]] = s
        dishes[s["id"]] = d
    memo: dict[tuple[str, str], dt.datetime] = {}
    visiting: set[tuple[str, str]] = set()

    def value(spec, sid: str, which: str) -> dt.datetime:
        if not isinstance(spec, dict) or "var" in spec and "ref" not in spec and "max" not in spec:
            return dinner_at + _minutes(spec, variables) * MIN
        if "max" in spec:
            return max(value(s, sid, which) for s in spec["max"])
        ref_edge = spec.get("edge", "end")
        base = edge(spec["ref"], ref_edge)
        if which == "start" and ref_edge == "end":     # anchored: follow reality
            if spec["ref"] in anchors:
                base = anchors[spec["ref"]]
            elif spec["ref"] not in done and now is not None and sid not in done:
                base = max(base, now)
        return base + _minutes(spec.get("delta", 0), variables) * MIN

    def edge(sid: str, which: str) -> dt.datetime:
        key = (sid, which)
        if key in memo:
            return memo[key]
        if key in visiting:
            raise ValueError(f"cycle in plan at {sid}.{which}")
        visiting.add(key)
        s = raw[sid]
        spec = s.get(which)
        if spec is None:                                   # derive from the other edge + duration
            other = edge(sid, "end" if which == "start" else "start")
            dur = _minutes(s.get("duration", 0), variables) * MIN
            val = other - dur if which == "start" else other + dur
        else:
            val = value(spec, sid, which)
        visiting.discard(key)
        memo[key] = val
        return val

    steps = []
    for sid, s in raw.items():
        d = dishes[sid]
        start, end = edge(sid, "start"), edge(sid, "end")
        if end < start:                                    # passive gap that closed (e.g. anchor was late)
            end = start
        anchored = next((r["ref"] for r in _refs(s.get("start")) if r.get("edge", "end") == "end"), None)
        steps.append(Step(
            id=sid, dish_id=d["id"], dish=d["name"], emoji=d.get("emoji", ""), color=d.get("color", "#94a3b8"),
            label=s["label"], check_label=s.get("check_label", "Done"), kind=s.get("kind", "active"),
            resource=s.get("resource", "none"), temp=s.get("temp"), notes=s.get("notes", ""),
            optional=bool(s.get("optional") or d.get("optional")), who=s.get("who", ""),
            after_guest=bool(s.get("after_guest")), start=start, end=end,
            anchored_to=anchored, done_at=done.get(sid)))
    steps.sort(key=lambda s: (s.start, s.end))
    if now is not None:
        annotate(steps, now, done)
    return steps


def annotate(steps: list[Step], now: dt.datetime, done: dict) -> None:
    by = {s.id: s for s in steps}
    for s in steps:
        if s.done_at:
            s.status = "done"
        elif not s.checkable:
            s.status = "running" if s.start <= now < s.end else "past" if now >= s.end else "later"
        elif s.anchored_to and s.anchored_to not in done and by[s.anchored_to].end <= now:
            s.status, s.waiting_on = "waiting", s.anchored_to
        elif now > s.end + LATE_GRACE or (s.kind == "milestone" and now > s.start + LATE_GRACE):
            s.status = "missed" if s.optional else "late"
        elif s.start <= now:
            s.status = "now"
        elif s.start - SOON_LEAD <= now:
            s.status = "soon"
        else:
            s.status = "later"


def board(steps: list[Step], now: dt.datetime, dinner_at: dt.datetime, next_n: int = 4) -> dict:
    """What the TV and phone headline: overdue, in progress, next up, and whether dinner is slipping."""
    active = [s for s in steps if s.checkable]
    late = sorted((s for s in active if s.status == "late"), key=lambda s: s.end, reverse=True)
    current = [s for s in active if s.status in ("now", "waiting")]
    upcoming, seen = [], set()                      # earliest upcoming step of each dish, so the panel stays varied
    for s in sorted((s for s in active if s.status in ("soon", "later")), key=lambda s: s.start):
        if s.dish_id not in seen:
            upcoming.append(s)
            seen.add(s.dish_id)
    upcoming = upcoming[:next_n]
    open_required = [s for s in active if s.status != "done" and not s.optional and s.kind != "milestone"]
    projected = max([dinner_at] + [s.end for s in open_required])
    done_n = sum(1 for s in active if s.status == "done")
    dinner = by_id(steps).get("dinner")
    return {"late": late, "now": current, "next": upcoming, "projected_dinner_at": projected,
            "behind_minutes": int((projected - dinner_at) / MIN), "done": done_n, "total": len(active),
            "finished": dinner is not None and dinner.status == "done"}


def by_id(steps: list[Step]) -> dict[str, Step]:
    return {s.id: s for s in steps}


def resource_conflicts(steps: list[Step], capacity: dict[str, int] | None = None) -> list[dict]:
    """Oven: overlapping steps at different temperatures, or more than `ovens` racks at once.
    Stovetop: more simultaneous pans than burners. Done steps are ignored."""
    cap = {"oven": 2, "stovetop": 4, **(capacity or {})}
    out = []
    for res, n in cap.items():
        rs = [s for s in steps if s.resource == res and not s.done_at and s.end > s.start]
        for i, a in enumerate(rs):
            for b in rs[i + 1:]:
                lo, hi = max(a.start, b.start), min(a.end, b.end)
                if lo < hi and res == "oven" and a.temp and b.temp and a.temp != b.temp:
                    out.append({"resource": res, "kind": "temperature", "steps": (a.id, b.id), "from": lo, "to": hi,
                                "msg": f"{a.label} ({a.temp}°F) and {b.label} ({b.temp}°F) both want the oven "
                                       f"{lo:%-I:%M}-{hi:%-I:%M}"})
        events = sorted([(s.start, 1, s) for s in rs] + [(s.end, -1, s) for s in rs], key=lambda e: (e[0], e[1]))
        live: list[Step] = []
        for t, kind, s in events:
            if kind < 0:
                live.remove(s)
            else:
                live.append(s)
                if len(live) > n:
                    out.append({"resource": res, "kind": "capacity", "steps": tuple(x.id for x in live), "from": t,
                                "to": min(x.end for x in live),
                                "msg": f"{len(live)} things on the {res} at {t:%-I:%M} (have {n}): "
                                       + ", ".join(x.label for x in live)})
    return out


def timeline_window(steps: list[Step], dinner_at: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """Whole hours that contain every step plus a little air after dinner."""
    first = min(s.start for s in steps) - 10 * MIN
    last = max([dinner_at + 20 * MIN] + [s.end for s in steps])
    ws = first.replace(minute=0, second=0, microsecond=0)
    we = last.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
    return ws, we


def pct(t: dt.datetime, ws: dt.datetime, we: dt.datetime) -> float:
    return max(0.0, min(100.0, 100 * (t - ws) / (we - ws)))


def lanes(steps: list[Step], ws: dt.datetime, we: dt.datetime, order: list[str] | None = None) -> list[dict]:
    """Per dish (in plan order when given), blocks positioned as percentages of the
    timeline width (for the TV)."""
    out: dict[str, dict] = {}
    if order:
        steps = sorted(steps, key=lambda s: order.index(s.dish_id) if s.dish_id in order else len(order))
    for s in steps:
        lane = out.setdefault(s.dish_id, {"dish": s.dish, "emoji": s.emoji, "color": s.color, "blocks": []})
        lane["blocks"].append({"id": s.id, "label": s.label, "kind": s.kind, "status": s.status, "temp": s.temp,
                               "left": pct(s.start, ws, we), "width": pct(s.end, ws, we) - pct(s.start, ws, we),
                               "minutes": int(s.duration / MIN), "start": s.start, "end": s.end})
    return list(out.values())


def hour_ticks(ws: dt.datetime, we: dt.datetime) -> list[tuple[float, str]]:
    t, out = ws, []
    while t <= we:
        out.append((pct(t, ws, we), t.strftime("%-I%p").lower().replace("m", "")))
        t += dt.timedelta(hours=1)
    return out
