"""Kelsey's drive: a human-corrected ETA along I-5 and the SVG chart that shows it.

No maps API. A static baseline (miles and no-traffic minutes at each city) plus an
append-only log of taps from phones on the LAN:
  {"at": iso, "by": "Ross", "kind": "depart",   "time": iso}
  {"at": iso, "by": "Ross", "kind": "waypoint", "time": iso, "miles": 106, "label": "Portland"}
  {"at": iso, "by": "Ross", "kind": "eta",      "eta": iso}      her phone's ETA
  {"at": iso, "by": "Ross", "kind": "stop",     "minutes": 20}
  {"at": iso, "by": "Ross", "kind": "arrive",   "time": iso}
Undo is popping the last event; everything else is derived. Pure functions, stdlib only.
"""
from __future__ import annotations

import base64
import datetime as dt
import html
from dataclasses import dataclass, field
from pathlib import Path

# I-5 northbound, cumulative miles from Eugene (OR exit numbers == OR mileposts: Eugene 194,
# Albany 234, Salem 253, Portland ~300, WA line 308; WA restarts at 0: Vancouver 1, Kelso 39,
# Centralia 82, Olympia 105, Tacoma 133, Seattle 165). Minutes = no-traffic baseline
# (~65 mph OR, ~70 rural WA, slower through Portland/Tacoma/Seattle). Estimates; the
# first tap corrects position and a typed ETA corrects pace.
DEFAULT_ROUTE = [
    ("Eugene", 0, 0), ("Albany", 40, 38), ("Salem", 59, 56), ("Portland", 106, 105),
    ("Vancouver", 115, 118), ("Kelso", 153, 155), ("Centralia", 196, 194),
    ("Olympia", 219, 216), ("Tacoma", 247, 246), ("Seattle", 279, 285),
]
MIN = dt.timedelta(minutes=1)


@dataclass(frozen=True)
class Route:
    points: tuple[tuple[str, float, float], ...]      # (label, miles, baseline minutes); last = Home

    @classmethod
    def default(cls, home_label="Home", home_miles=291.0, home_minutes=305.0) -> Route:
        pts = [p for p in DEFAULT_ROUTE if p[1] < home_miles - 3]      # a home before Seattle just truncates
        return cls(tuple(pts + [(home_label, float(home_miles), float(home_minutes))]))

    @property
    def home_miles(self) -> float:
        return self.points[-1][1]

    @property
    def home_minutes(self) -> float:
        return self.points[-1][2]

    @property
    def cities(self) -> list[tuple[str, float]]:
        """Tappable waypoints: everything but Eugene and Home."""
        return [(label, m) for label, m, _ in self.points[1:-1]]

    def minutes_at(self, miles: float) -> float:
        return _interp(miles, [(m, t) for _, m, t in self.points])

    def miles_at(self, minutes: float) -> float:
        return _interp(minutes, [(t, m) for _, m, t in self.points])

    def where(self, miles: float) -> str:
        for label, m, _ in self.points:
            if abs(m - miles) <= 6:
                return f"near {label}" if label != self.points[-1][0] else "almost home"
        prev = max((p for p in self.points if p[1] <= miles), key=lambda p: p[1])
        nxt = min((p for p in self.points if p[1] > miles), key=lambda p: p[1])
        return f"between {prev[0]} and {nxt[0]}"


def _interp(x: float, pts: list[tuple[float, float]]) -> float:
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


@dataclass
class Schedule:
    status: str = "pending"                 # pending | driving | arrived
    t0: dt.datetime | None = None           # anchor: at time t0 she was at m0 miles ...
    m0: float = 0.0
    pace: float = 1.0                       # ... and covers the baseline at 1/pace speed
    held_eta: dt.datetime | None = None     # an ETA typed from her phone is shown as-is
    departed_at: dt.datetime | None = None
    arrived_at: dt.datetime | None = None
    last_fix_at: dt.datetime | None = None
    last_by: str = ""
    last_kind: str = ""
    fixes: list[tuple[dt.datetime, float]] = field(default_factory=list)

    def miles_at(self, route: Route, t: dt.datetime) -> float:
        if self.status == "pending" or self.t0 is None:
            return 0.0
        if self.status == "arrived":
            return route.home_miles
        elapsed = max(0.0, (t - self.t0).total_seconds() / 60)
        return min(route.home_miles, route.miles_at(route.minutes_at(self.m0) + elapsed / self.pace))

    def eta(self, route: Route) -> dt.datetime | None:
        if self.held_eta is not None:
            return self.held_eta
        if self.t0 is None:
            return None
        remaining = (route.home_minutes - route.minutes_at(self.m0)) * self.pace
        return self.t0 + dt.timedelta(minutes=remaining)


def _t(s: str, tz) -> dt.datetime:
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=tz)


def apply(events: list[dict], route: Route, tz) -> Schedule:
    s = Schedule()
    for e in events:
        at = _t(e["at"], tz)
        when = _t(e.get("time") or e["at"], tz)
        k = e["kind"]
        if k == "depart":
            s = Schedule(status="driving", t0=when, m0=0.0, pace=1.0, departed_at=when, last_fix_at=at, fixes=[(when, 0.0)])
        elif k == "waypoint":
            if s.status != "driving":
                s.status, s.departed_at = "driving", s.departed_at or when
                s.fixes = s.fixes or [(when, 0.0)]
            s.t0, s.m0, s.held_eta = when, float(e["miles"]), None
            s.last_fix_at = at
            s.fixes.append((when, s.m0))
        elif k == "eta":
            if s.status != "driving":
                s.status, s.departed_at, s.fixes = "driving", s.departed_at or at, s.fixes or [(at, 0.0)]
            m_now = s.miles_at(route, at)
            remaining_base = route.home_minutes - route.minutes_at(m_now)
            eta = _t(e["eta"], tz)
            actual = (eta - at).total_seconds() / 60
            if remaining_base >= 5 and actual > 0:
                s.pace = min(2.5, max(0.6, actual / remaining_base))
            s.t0, s.m0, s.held_eta = at, m_now, eta
            s.last_fix_at = at
        elif k == "stop":
            if s.status == "driving":
                m_now = s.miles_at(route, at)
                s.t0, s.m0 = at + dt.timedelta(minutes=float(e["minutes"])), m_now
                if s.held_eta:
                    s.held_eta += dt.timedelta(minutes=float(e["minutes"]))
                s.last_fix_at = at
        elif k == "arrive":
            s.status, s.arrived_at, s.last_fix_at = "arrived", when, at
            s.fixes.append((when, route.home_miles))
        s.last_by, s.last_kind = e.get("by", ""), k
    return s


@dataclass
class Estimate:
    status: str                 # pending | driving | stopped | overdue | arrived
    miles: float
    eta: dt.datetime | None
    where: str
    remaining_miles: float
    minutes_since_fix: float | None
    headline: str
    sub: str
    urgent: bool = False


def estimate(s: Schedule, route: Route, now: dt.datetime, name="Kelsey",
             plan_depart: dt.datetime | None = None) -> Estimate:
    since = None if s.last_fix_at is None else (now - s.last_fix_at).total_seconds() / 60
    if s.status == "pending":
        if plan_depart:
            eta = plan_depart + dt.timedelta(minutes=route.home_minutes)
            head = f"leaves ~{fmt(plan_depart)}" if now < plan_depart else "leaving soon…"
            return Estimate("pending", 0, eta, route.points[0][0], route.home_miles, None, head,
                            f"plan: here about {fmt(eta)} if she leaves at {fmt(plan_depart)}")
        return Estimate("pending", 0, None, route.points[0][0], route.home_miles, None,
                        "not on the road yet", "tap 'On the road!' when she leaves")
    if s.status == "arrived":
        mins = (now - s.arrived_at).total_seconds() / 60
        return Estimate("arrived", route.home_miles, s.arrived_at, "home", 0, since,
                        f"{name} is here! 🎉", f"arrived {fmt(s.arrived_at)}", urgent=mins < 10)
    miles = s.miles_at(route, now)
    eta = s.eta(route)
    remaining = route.home_miles - miles
    if s.t0 and now < s.t0 and s.m0 > 0:
        return Estimate("stopped", miles, eta, route.where(miles), remaining, since,
                        f"ETA {fmt(eta)}", f"☕ stopped {route.where(miles)} until {fmt(s.t0)}")
    if eta and now > eta + 5 * MIN:
        late = int((now - eta).total_seconds() / 60)
        return Estimate("overdue", route.home_miles - 1, eta, "almost home", 1, since,
                        "Any minute now…", f"expected {fmt(eta)} ({late} min ago) · tap 'She's here!' when she arrives",
                        urgent=True)
    stale = since is not None and since > 90
    head = f"ETA {'~' if stale else ''}{fmt(eta)}"
    sub = f"{route.where(miles)} · {remaining:.0f} mi to go"
    if since is not None:
        sub += f" · updated {ago(since)}" + (f" by {s.last_by}" if s.last_by else "")
    if stale:
        sub += " · a guess by now, got news?"
    urgent = eta is not None and (eta - now) <= 10 * MIN
    return Estimate("driving", miles, eta, route.where(miles), remaining, since, head, sub, urgent=urgent)


def fmt(t: dt.datetime | None) -> str:
    return "" if t is None else t.strftime("%-I:%M%p").lower()


def ago(minutes: float) -> str:
    m = int(minutes)
    return "just now" if m < 1 else f"{m} min ago" if m < 90 else f"{m // 60}h {m % 60:02d}m ago"


# ---- SVG chart: time of day across, miles up; plan dashed, actual solid, car at now ----

def chart_svg(s: Schedule, route: Route, est: Estimate, now: dt.datetime, name="Kelsey", photo: str | None = None,
              plan_depart: dt.datetime | None = None, w: int = 780, h: int = 540, compact: bool = False) -> str:
    pl, pr, pt, pb = 150, 40, 100, 60
    dep = s.departed_at or plan_depart or now.replace(hour=7, minute=0, second=0, microsecond=0)
    plan_eta = dep + dt.timedelta(minutes=route.home_minutes)
    t_start = (dep - dt.timedelta(minutes=15)).replace(minute=0, second=0, microsecond=0)
    t_end = max(x for x in (est.eta, plan_eta, now, s.arrived_at) if x) + dt.timedelta(minutes=45)
    t_end = (t_end + dt.timedelta(minutes=59)).replace(minute=0, second=0, microsecond=0)

    def X(t: dt.datetime) -> float:
        return pl + (w - pl - pr) * (t - t_start).total_seconds() / max(1, (t_end - t_start).total_seconds())

    def Y(miles: float) -> float:
        return pt + (h - pt - pb) * (1 - miles / route.home_miles)

    o = [f'<svg viewBox="0 0 {w} {h}" width="100%" xmlns="http://www.w3.org/2000/svg" '
         'xmlns:xlink="http://www.w3.org/1999/xlink" font-family="Inter, Noto Sans, DejaVu Sans, sans-serif">']
    # city gridlines; labels by priority (Home, then big cities), skipping any that would collide
    priority = {route.points[-1][0]: 0, "Portland": 1, "Tacoma": 1, "Olympia": 2, "Salem": 2, "Eugene": 1,
                "Kelso": 3, "Centralia": 3, "Albany": 4, "Vancouver": 5, "Seattle": 4}
    drawn: list[float] = []
    for label, m, _ in sorted(route.points, key=lambda p: priority.get(p[0], 9)):
        y = Y(m)
        last = label == route.points[-1][0]
        o.append(f'<line x1="{pl}" y1="{y:.1f}" x2="{w - pr}" y2="{y:.1f}" '
                 f'stroke="rgba(255,255,255,{0.25 if last else 0.09})" stroke-width="{2 if last else 1}"/>')
        if all(abs(y - d) >= 30 for d in drawn):
            drawn.append(y)
            o.append(f'<text x="{pl - 14}" y="{y + 9:.1f}" text-anchor="end" font-size="{28 if last else 25}" '
                     f'font-weight="{800 if last else 500}" fill="{"#fde68a" if last else "#94a3b8"}">'
                     f'{html.escape(label)}</text>')
    hours = max(1, round((t_end - t_start).total_seconds() / 3600))
    step_h = 1 if hours <= 8 else 2
    t = t_start
    while t <= t_end:
        x = X(t)
        o.append(f'<line x1="{x:.1f}" y1="{pt}" x2="{x:.1f}" y2="{h - pb}" stroke="rgba(255,255,255,0.07)"/>')
        o.append(f'<text x="{x:.1f}" y="{h - pb + 34}" text-anchor="middle" font-size="24" fill="#94a3b8">'
                 f'{fmt(t).replace(":00", "")}</text>')
        t += dt.timedelta(hours=step_h)
    plan = " ".join(f"{X(dep + dt.timedelta(minutes=b)):.1f},{Y(m):.1f}" for _, m, b in route.points)
    o.append(f'<polyline points="{plan}" fill="none" stroke="#94a3b8" stroke-width="4" stroke-dasharray="12 10" opacity="0.8"/>')
    if s.status != "pending":
        pts = s.fixes + ([(now, est.miles)] if s.status != "arrived" else [])
        actual = " ".join(f"{X(t):.1f},{Y(m):.1f}" for t, m in pts)
        o.append(f'<polyline points="{actual}" fill="none" stroke="#fde68a" stroke-width="6" '
                 'stroke-linejoin="round" stroke-linecap="round"/>')
        for t, m in s.fixes:
            o.append(f'<circle cx="{X(t):.1f}" cy="{Y(m):.1f}" r="9" fill="#0d1324" stroke="#fde68a" stroke-width="4"/>')
        if s.status != "arrived" and est.eta and est.eta > now:
            o.append(f'<line x1="{X(now):.1f}" y1="{Y(est.miles):.1f}" x2="{X(est.eta):.1f}" y2="{Y(route.home_miles):.1f}" '
                     'stroke="#fde68a" stroke-width="3" stroke-dasharray="4 8" opacity="0.8"/>')
            xe = X(est.eta)
            o.append(f'<line x1="{xe:.1f}" y1="{pt}" x2="{xe:.1f}" y2="{h - pb}" stroke="#fde68a" stroke-width="2" '
                     'stroke-dasharray="6 6"/>')
            o.append(f'<text x="{min(xe, w - pr - 70):.1f}" y="{h - pb - 12}" text-anchor="middle" font-size="24" '
                     f'font-weight="800" fill="#fde68a">{fmt(est.eta)}</text>')
    xn = X(now)
    o.append(f'<line x1="{xn:.1f}" y1="{pt}" x2="{xn:.1f}" y2="{h - pb}" stroke="#60a5fa" stroke-width="2" opacity="0.7"/>')
    car_x = X(s.arrived_at) if s.status == "arrived" else X(dep) if s.status == "pending" else X(now)
    o.append(car(car_x, Y(est.miles), name, photo, s.status, scale=1.6 if not compact else 1.2))
    o.append("</svg>")
    return "\n".join(o)


def car(x: float, y: float, name: str, photo: str | None, status: str, scale: float = 1.6) -> str:
    """A little car with the face in a circle above the driver's seat. photo = data: URI or None."""
    face = (f'<image href="{photo}" x="-26" y="-60" width="52" height="52" clip-path="url(#face)" '
            'preserveAspectRatio="xMidYMid slice"/>'
            if photo else
            f'<circle cx="0" cy="-34" r="26" fill="#f472b6"/><text x="0" y="-24" text-anchor="middle" font-size="30" '
            f'font-weight="800" fill="#0d1324">{html.escape(name[:1])}</text>')
    return (f'<defs><clipPath id="face"><circle cx="0" cy="-34" r="26"/></clipPath></defs>'
            f'<g transform="translate({x:.1f},{y:.1f}) scale({scale})">'
            f'<rect x="-36" y="-14" width="72" height="26" rx="8" fill="#ef4444"/>'
            f'<path d="M-22,-14 L-14,-30 L18,-30 L28,-14 Z" fill="#fca5a5"/>'
            f'<circle cx="-20" cy="14" r="8" fill="#0d1324" stroke="#cbd5e1" stroke-width="3"/>'
            f'<circle cx="20" cy="14" r="8" fill="#0d1324" stroke="#cbd5e1" stroke-width="3"/>'
            f'<circle cx="0" cy="-34" r="28" fill="#0d1324"/>{face}'
            f'<circle cx="0" cy="-34" r="27" fill="none" stroke="#fde68a" stroke-width="3"/>'
            f'</g>')


def photo_uri(path: Path | None, max_bytes: int = 200_000) -> str | None:
    """Inline the photo (set_content has no base URL); skipped if missing or too big."""
    if not path or not path.exists() or path.stat().st_size > max_bytes:
        return None
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"
