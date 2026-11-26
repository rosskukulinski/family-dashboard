"""Thanksgiving view -> 1920x1080 HTML. Fixed-size layout (no FIT_JS)."""
from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

from . import kelsey as kz
from . import thanksgiving as tg
from .config import Config

STYLE = (Path(__file__).parent / "thanksgiving.css").read_text()
MAX_LANES = 8
esc = html.escape


def fmt(t: dt.datetime) -> str:
    return t.strftime("%-I:%M%p").lower().replace(":00", "")


def ago(d: dt.timedelta) -> str:
    m = max(0, int(d.total_seconds() // 60))
    return f"{m} min" if m < 90 else f"{m // 60}h {m % 60:02d}m"


def row(s: tg.Step, now: dt.datetime) -> str:
    if s.status == "late":
        tail, when = f"{ago(now - s.end)} late", fmt(s.end)
    elif s.status == "waiting":
        tail, when = "waiting", "soon"
    elif s.status == "now":
        tail, when = f"{max(0, int((s.end - now).total_seconds() // 60))} min left", "now"
    else:
        mins = int((s.start - now).total_seconds() // 60)
        tail, when = (f"in {mins} min" if mins < 60 else ""), fmt(s.start)
    return (f'<div class="row {s.status}"><span class="when">{when}</span>'
            f'<span class="t">{esc(s.emoji)} {esc(s.label)}</span><span class="tail">{tail}</span></div>')


def board_html(view: dict, now: dt.datetime) -> str:
    by = tg.by_id(view["_steps"])
    current = [by[i] for i in view["board"]["late"]] + [by[i] for i in view["board"]["now"]]
    nxt = [by[i] for i in view["board"]["next"]]
    cur = "".join(row(s, now) for s in current[:5]) or '<div class="empty">Nothing on the stove</div>'
    nx = "".join(row(s, now) for s in nxt[:5]) or '<div class="empty">That was the last one</div>'
    return f'<div class="board"><div><h2 class="now">Right now</h2>{cur}</div><div><h2>Next</h2>{nx}</div></div>'


def lanes_html(view: dict, now: dt.datetime) -> str:
    steps = view["_steps"]
    dinner = view["_dinner"]
    ws, we = tg.timeline_window(steps, dinner)
    # the afternoon crunch: zoom in once the morning is over
    if now.date() == dinner.date() and now >= dinner - dt.timedelta(hours=2, minutes=30):
        ws = max(ws, (now - dt.timedelta(hours=1, minutes=30)).replace(minute=0, second=0, microsecond=0))
    lanes = tg.lanes([s for s in steps if s.end >= ws], ws, we)[:MAX_LANES]
    ticks = "".join(f'<span style="left:{p:.2f}%">{t}</span>' for p, t in tg.hour_ticks(ws, we))
    out = []
    for lane in lanes:
        blocks = []
        for b in lane["blocks"]:
            if b["width"] <= 0:
                continue
            cls = f'blk {b["kind"]} {b["status"]}' + (" short" if b["width"] < 7 else "")
            label = "" if b["kind"] == "passive" else esc(b["label"])
            blocks.append(f'<div class="{cls}" style="left:{b["left"]:.2f}%;width:{max(0.5, b["width"]):.2f}%">{label}</div>')
        name = f'{esc(lane["emoji"])} {esc(lane["dish"])}'
        out.append(f'<div class="lane" style="--c:{lane["color"]}"><div class="name">{name}</div>'
                   f'<div class="bars">{"".join(blocks)}</div></div>')
    pn, pd = tg.pct(now, ws, we), tg.pct(dinner, ws, we)
    w = "calc(100% - 230px)"
    nowline = (f'<div class="nowline" style="left:calc(230px + {w} * {pn / 100:.4f})"></div>'
               f'<div class="nowtag" style="left:calc(230px + {w} * {pn / 100:.4f})">NOW</div>' if ws <= now <= we else "")
    return (f'<div class="lanes"><div class="lanes-wrap"><div class="tags"></div><div class="axis">{ticks}</div>{"".join(out)}'
            f'{nowline}'
            f'<div class="dinnerline" style="left:calc(230px + {w} * {pd / 100:.4f})"></div>'
            f'<div class="dinnertag" style="left:calc(230px + {w} * {pd / 100:.4f})">DINNER</div></div></div>')


def kelsey_html(cfg: Config, view: dict, now: dt.datetime, photo: str | None) -> str:
    k = view["kelsey"]
    svg = kz.chart_svg(view["_sched"], view["_route"], view["_est"], now, cfg.kelsey_name, photo,
                       view.get("_plan_depart"), w=780, h=520)
    return (f'<div class="kelsey {k["status"]}"><div class="khead"><span class="kname">🚗 {esc(k["name"])}</span>'
            f'<span class="keta">{esc(k["headline"])}</span></div><div class="ksub">{esc(k["sub"])}</div>{svg}</div>')


def kids_html(view: dict, now: dt.datetime) -> str:
    jobs = [s for s in view["_steps"] if s.who]
    if not jobs:
        return ""
    rows = []
    for s in jobs:
        cls = "done" if s.status == "done" else "late" if s.status == "late" else ""
        at = "done ✓" if s.status == "done" else "now!" if s.status in ("now", "late") else fmt(s.start)
        rows.append(f'<div class="job {cls}"><span class="box">{"✓" if s.status == "done" else ""}</span>'
                    f'<span>{esc(s.emoji)} {esc(s.label)}</span><span class="who">· {esc(s.who)}</span>'
                    f'<span class="at">{at}</span></div>')
    return f'<div class="kids"><h2><b>Hannah</b> &amp; <i>Elliott</i></h2>{"".join(rows)}</div>'


def build_tg_html(cfg: Config, view: dict, now: dt.datetime, photo: str | None = None) -> str:
    hero = view["hero"]
    proj = f' <span class="proj">~{esc(view["projected_label"])}</span>' if view.get("projected_label") else ""
    url = (cfg.public_url or "").replace("http://", "")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{STYLE}</style></head>
<body>
  <div class="left">
    <div class="datebar"><span class="date">{now.strftime("%A")}, <span>{now.strftime("%B %-d")}</span></span>
      <span class="dinner">dinner <b>{esc(view["dinner_label"])}</b>{proj}</span><span class="clock">{fmt(now)}</span></div>
    <div class="hero {hero["tone"]}"><div class="big">{esc(hero["big"])}</div><div class="sub">{esc(hero["sub"])}</div></div>
    {board_html(view, now)}
    {lanes_html(view, now)}
  </div>
  <div class="right">
    {kelsey_html(cfg, view, now, photo)}
    {kids_html(view, now)}
  </div>
  <div class="foot">tap along at <b>{esc(url)}/tg</b> · updated {now.strftime("%-I:%M %p").lower()}</div>
</body></html>"""
