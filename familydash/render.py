"""Model -> 1920x1080 HTML page. Pure functions, plus FIT_JS which the browser runs
after layout to trim / grow content so everything fits on one screen."""
from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

from .config import Config

STYLE = (Path(__file__).parent / "style.css").read_text()
MAX_CHORES = 16   # hard cap; FIT_JS trims further to what fits

# Skylight routines have three time-of-day windows, stored as start_time 06:00 / 14:00 / 20:00.
GROUP_ENDS = {0: dt.time(12, 0), 1: dt.time(17, 0)}   # morning, afternoon drop off after these
GROUP_LABELS = {0: "☀️ Morning", 1: "🌤️ Afternoon", 2: "🌙 Evening", 3: "Anytime"}
NEUTRAL = "#a78bfa"
MEETING_HOSTS = (("zoom.us", "Zoom"), ("meet.google", "Google Meet"), ("teams.microsoft", "Teams"),
                 ("webex", "Webex"))


def parse_when(s: str, tz) -> dt.datetime:
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=tz)


def events_for(day: dt.date, events: list[dict], tz) -> list[dict]:
    out = []
    for e in events:
        start = parse_when(e["start"], tz).astimezone(tz)
        end = parse_when(e.get("end") or e["start"], tz).astimezone(tz)
        if e.get("all_day"):
            if start.date() <= day < max(end.date(), start.date() + dt.timedelta(days=1)):  # end exclusive
                out.append({**e, "_start": start, "_end": end})
        elif start.date() <= day <= end.date():
            out.append({**e, "_start": start, "_end": end})
    out.sort(key=lambda e: (not e.get("all_day"), e["_start"]))
    return out


def fmt_time(t: dt.datetime | dt.time) -> str:
    return t.strftime("%-I:%M%p").lower().replace(":00", "")


def place(location: str) -> str:
    """Short, TV-safe location: never show meeting links (they can carry passwords)."""
    low = location.lower()
    for host, label in MEETING_HOSTS:
        if host in low:
            return label
    if "://" in location or low.startswith("www."):
        return "Online"
    return location.split(",")[0]


def event_rows(cfg: Config, events: list[dict], now: dt.datetime, dim_past: bool) -> str:
    if not events:
        return '<div class="empty">Nothing scheduled</div>'
    rows = []
    for e in events:
        state = ""
        if e.get("all_day"):
            when = "All day"
        else:
            when = fmt_time(e["_start"])
            if dim_past and e["_end"] <= now:
                state = "past"
            elif dim_past and e["_start"] <= now < e["_end"]:
                state = "now"
        who = e.get("who") if e.get("who") in cfg.kids else None
        who = who or next((k for k in cfg.kids if k.lower() in e["title"].lower()), None)
        dot = f'<span class="dot" style="background:{cfg.kids[who]}"></span>' if who else '<span class="dot"></span>'
        loc = f'<div class="loc">{html.escape(place(e["location"]))}</div>' if e.get("location") else ""
        rows.append(f'<div class="ev {state}"><div class="when">{when}</div>{dot}'
                    f'<div class="what"><div class="title">{html.escape(e["title"])}</div>{loc}</div></div>')
    return "\n".join(rows)


def grabs_section(cfg: Config, grabs: list[dict] | None) -> str:
    if not grabs:
        return ""
    chips = []
    for g in grabs:
        color = cfg.kids.get(g.get("who") or "", "#94a3b8")
        icon = html.escape(g["emoji"]) + " " if g.get("emoji") else ""
        tail = (f'<span class="by" style="color:{color}">✓ {html.escape(g["who"])}</span>' if g.get("who") else
                '<span class="by">✓ done</span>' if g["done"] else
                star_tag(g["points"]))
        chips.append(f'<span class="chip{" done" if g["done"] else ""}">{icon}{html.escape(g["title"])}{tail}</span>')
    open_n = sum(1 for g in grabs if not g["done"])
    return (f'<div class="grabs"><h2 class="gh">Up for grabs <span>{open_n} left · {html.escape(cfg.grabs_note)}</span></h2>'
            f'<div class="chips" data-key="grabs">{"".join(chips)}</div></div>')


def family_card(cfg: Config, fam: dict | None, kids: list[dict] | None = None) -> str:
    """Family pot. With the nightly sweep on, the kids' stars are shown as 'on the way'."""
    if not fam:
        return ""
    kids = kids or []
    stars, goal = fam.get("stars") or 0, fam.get("goal")
    pending = sum((k.get("stars") or 0) for k in kids) if cfg.star_sweep else 0
    coming = (f'<div class="coming">+{pending} ★ from {" & ".join(html.escape(k["name"]) for k in kids)}'
              f' at {fmt_time(cfg.star_sweep_at)}</div>' if pending else "")
    bar = ""
    if goal and goal["points"]:
        g = goal["points"]
        pct = min(100, round(100 * stars / g))
        pct_pending = min(100 - pct, round(100 * pending / g))
        emoji, name = html.escape(goal["emoji"]), html.escape(goal["name"])
        if stars >= g:
            msg = f'{emoji} <b>{name}</b> unlocked!'
        elif stars + pending >= g:
            msg = f'{emoji}&nbsp;<b>{name}</b> unlocks tonight!'
        else:
            msg = f'<b>{g - stars - pending}</b> more to {emoji}&nbsp;<b>{name}</b>'
        bar = (f'<div class="bar"><div class="fill" style="width:{pct}%"></div>'
               f'<div class="pending" style="width:{pct_pending}%"></div></div>'
               f'<div class="goal"><span class="msg">{msg}</span><span class="count">{stars} / {g}</span></div>')
    return (f'<div class="family"><div class="fhead"><span class="fname">Family</span>'
            f'<span class="fstars"><span class="star">★</span>{stars}</span>'
            f'<span class="fnote">everyone wins</span></div>{bar}{coming}</div>')


def day_order(chore: dict) -> tuple:
    """(group, time, Skylight position): Morning, Afternoon, Evening routines, then untimed."""
    t = chore.get("time")
    pos = chore.get("position") or 0
    if not t:
        return (3, "", pos)
    return (0 if t < "12:00" else 1 if t < "17:00" else 2, t, pos)


def star_tag(points: int) -> str:
    return f'<span class="pts">★{points}</span>' if points else ""


def kid_cards(cfg: Config, kids: list[dict], now: dt.datetime) -> str:
    cards = []
    for k in kids:
        color = cfg.kids.get(k["name"], NEUTRAL)
        stars = k.get("stars")
        chores = k.get("chores") or []
        earned = sum(c["points"] for c in chores if c["done"])
        possible = sum(c["points"] for c in chores)
        # grouped by routine window; what's left first, finished ones sink (hidden first)
        chores = sorted(chores, key=lambda c: (day_order(c)[0], c["done"], *day_order(c)[1:]))
        # a routine drops off once its part of the day is over; the totals still count it
        over = {g for g, until in GROUP_ENDS.items() if now.time() >= until}
        chores = [c for c in chores if day_order(c)[0] not in over]
        shown = chores[: MAX_CHORES - 1] if len(chores) > MAX_CHORES else chores
        groups = {day_order(c)[0] for c in shown}
        items, current = "", None
        for c in shown:
            g = day_order(c)[0]
            if g != current and (g != 3 or len(groups) > 1):  # "Anytime" only labelled alongside others
                items += f'<li class="grp">{GROUP_LABELS[g]}</li>'
            current = g
            items += (f'<li class="{"done" if c["done"] else ""}"><span class="box">{"✓" if c["done"] else ""}</span>'
                      f'<span class="t">{html.escape(c["title"])}</span>{star_tag(c["points"])}</li>')
        if len(chores) > MAX_CHORES:
            items += f'<li class="more"><span class="t">+{len(chores) - len(shown)} more</span></li>'
        today = (f'<div class="today">today <b>{earned}</b> of {possible} ★</div><ul data-key="chores">{items}</ul>'
                 if chores or possible else "")
        num = "—" if stars is None else stars
        cards.append(f'<div class="kid" style="--c:{color}"><div class="khead">'
                     f'<span class="name">{html.escape(k["name"])}</span>'
                     f'<span class="stars"><span class="star">★</span><span class="num">{num}</span></span></div>'
                     f'{today}</div>')
    return "\n".join(cards)


def build_html(cfg: Config, data: dict, now: dt.datetime) -> str:
    today = now.date()
    ev_today = events_for(today, data.get("events", []), cfg.tz)
    ev_tom = events_for(today + dt.timedelta(days=1), data.get("events", []), cfg.tz)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{STYLE}</style></head>
<body>
  <div class="left">
    <div class="datebar"><span class="date">{now.strftime("%A")}, <span>{now.strftime("%B %-d")}</span></span>
      <span class="clock">{fmt_time(now)}</span></div>
    <div class="kids">{kid_cards(cfg, data.get("kids", []), now)}</div>
    {family_card(cfg, data.get("family"), data.get("kids"))}
  </div>
  <div class="right">
    <h2>Today</h2>
    <div class="list" data-key="today">{event_rows(cfg, ev_today, now, dim_past=True)}</div>
    <h2 class="tom">Tomorrow</h2>
    <div class="list small" data-key="tom">{event_rows(cfg, ev_tom, now, dim_past=False)}</div>
    {grabs_section(cfg, data.get("grabs"))}
  </div>
  <div class="foot">updated {now.strftime("%-I:%M %p").lower()}{html.escape(data.get("note", ""))}</div>
</body></html>"""


# Make both columns fit by trimming rows (keeping a "+N more" marker per list), then put
# rows back in priority order while they still fit. Right column: up-for-grabs gives way
# first, then tomorrow; today's calendar only as a last resort (finished events before
# upcoming ones, shown as "N earlier"). Left column: the longest chore list gives way
# first (finished chores before open ones); then spare room grows the chore text.
FIT_JS = r"""() => {
  const ROW = '.ev, .chip, li:not(.more):not(.grp)';
  const rows = l => [...l.querySelectorAll(ROW)];
  function bump(l, by, earlier) {
    const cls = earlier ? 'earlier' : 'more';
    let m = l.querySelector(earlier ? ':scope > .earlier' : ':scope > .more:not(.earlier)');
    if (!m) {
      m = document.createElement(l.tagName === 'UL' ? 'li' : 'div'); m.className = 'more ' + cls;
      if (earlier) l.prepend(m); else l.appendChild(m);
    }
    const n = (+(m.textContent.match(/\d+/) || [0])[0]) + by;
    if (n <= 0) m.remove(); else m.textContent = earlier ? n + ' earlier' : '+' + n + ' more';
  }
  function fit(col, stages, restoreOrder) {
    const over = () => col.scrollHeight > col.clientHeight + 1;
    const removed = new Map();
    const take = (l, r, earlier) => {
      r.remove(); bump(l, 1, earlier);
      if (!removed.has(l)) removed.set(l, []);
      removed.get(l).push([r, r._next, earlier]);
    };
    for (const [pick, keep, fromTop] of stages) {
      while (over()) {
        const l = pick(); if (!l) break;
        let rs = rows(l);
        if (fromTop) rs = rs.filter(r => r.classList.contains('past'));
        if (rows(l).length <= keep || !rs.length) break;
        const done = rs.filter(x => x.classList.contains('done'));
        const r = fromTop ? rs[0] : (done.length ? done[done.length - 1] : rs[rs.length - 1]);
        r._next = r.nextSibling; take(l, r, fromTop);
      }
    }
    for (const l of restoreOrder()) {
      const stack = removed.get(l) || [];
      while (stack.length) {
        const [r, next, earlier] = stack.pop();
        l.insertBefore(r, next && next.parentNode === l ? next : l.querySelector(':scope > .more:not(.earlier)'));
        bump(l, -1, earlier);
        if (over()) { r.remove(); bump(l, 1, earlier); break; }
      }
    }
  }
  const q = k => document.querySelector(`[data-key="${k}"]`);
  fit(document.querySelector('.right'),
      [[() => q('grabs'), 1], [() => q('tom'), 2], [() => q('grabs'), 0], [() => q('tom'), 0],
       [() => q('today'), 1, true], [() => q('today'), 1]],
      () => [q('today'), q('tom'), q('grabs')].filter(Boolean));
  const longest = () => [...document.querySelectorAll('[data-key="chores"]')]
      .sort((a, b) => rows(b).length - rows(a).length)[0];
  const left = document.querySelector('.left');
  fit(left, [[longest, 3]], () => [...document.querySelectorAll('[data-key="chores"]')]);
  for (const h of document.querySelectorAll('li.grp')) {
    const n = h.nextElementSibling;
    if (!n || n.classList.contains('grp') || n.classList.contains('more')) h.remove();
  }
  if (!left.querySelector('.kid .more')) {
    const kids = document.querySelector('.kids');
    for (let size = 26; size <= 40; size++) {
      kids.style.setProperty('--cs', size + 'px');
      if (left.scrollHeight > left.clientHeight + 1) { kids.style.setProperty('--cs', (size - 1) + 'px'); break; }
    }
  }
}"""
