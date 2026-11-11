import datetime as dt

from familydash.render import (
    build_html,
    day_order,
    event_rows,
    events_for,
    family_card,
    fmt_time,
    grabs_section,
    kid_cards,
    place,
)
from tests.conftest import TZ, at, make_cfg


def test_place_never_shows_meeting_links():
    assert place("https://us02web.zoom.us/j/1?pwd=SECRET") == "Zoom"
    assert place("https://meet.google.com/abc") == "Google Meet"
    assert place("https://example.com/x") == "Online"
    assert place("Community Pool, 1 Main St") == "Community Pool"


def test_fmt_time():
    assert fmt_time(at(9)) == "9am" and fmt_time(at(17, 30)) == "5:30pm"


def test_events_for_all_day_end_is_exclusive():
    evs = [{"title": "No school", "start": "2026-11-10T00:00:00-08:00", "end": "2026-11-11T00:00:00-08:00", "all_day": True}]
    assert len(events_for(dt.date(2026, 11, 10), evs, TZ)) == 1
    assert events_for(dt.date(2026, 11, 11), evs, TZ) == []


def test_event_rows_states_and_kid_dots(cfg):
    evs = events_for(dt.date(2026, 11, 9), [
        {"title": "Breakfast", "start": "2026-11-09T08:00:00-08:00", "end": "2026-11-09T08:30:00-08:00"},
        {"title": "Ada piano", "start": "2026-11-09T08:45:00-08:00", "end": "2026-11-09T09:30:00-08:00"},
        {"title": "Dinner", "start": "2026-11-09T18:00:00-08:00", "end": "2026-11-09T19:00:00-08:00"}], TZ)
    html = event_rows(cfg, evs, at(9), dim_past=True)
    assert html.index('class="ev past"') < html.index('class="ev now"') < html.index('class="ev "')
    assert "background:#f472b6" in html                       # Ada's colour from her name in the title
    assert event_rows(cfg, [], at(9), True) == '<div class="empty">Nothing scheduled</div>'


def test_day_order_uses_skylight_routine_windows():
    assert day_order({"time": "06:00"})[0] == 0
    assert day_order({"time": "14:00"})[0] == 1
    assert day_order({"time": "20:00"})[0] == 2
    assert day_order({"time": None, "title": "Brush (PM)"})[0] == 3        # names are ignored


CHORES = [
    {"title": "Make bed", "done": True, "points": 1, "time": "06:00", "position": 1},
    {"title": "Brush (AM)", "done": False, "points": 1, "time": "06:00", "position": 2},
    {"title": "Good day at school", "done": False, "points": 2, "time": "14:00", "position": 1},
    {"title": "Brush (PM)", "done": False, "points": 1, "time": "20:00", "position": 1},
]


def headings(html):
    import re
    return re.findall(r'<li class="grp">([^<]+)</li>', html)


def test_kid_cards_group_by_routine_and_hide_finished_parts_of_day(cfg):
    kids = [{"name": "Ada", "stars": 4, "chores": CHORES}]
    assert headings(kid_cards(cfg, kids, at(9))) == ["☀️ Morning", "🌤️ Afternoon", "🌙 Evening"]
    assert headings(kid_cards(cfg, kids, at(13))) == ["🌤️ Afternoon", "🌙 Evening"]
    assert headings(kid_cards(cfg, kids, at(18))) == ["🌙 Evening"]
    noon = kid_cards(cfg, kids, at(13))
    assert "Make bed" not in noon and "today <b>1</b> of 5 ★" in noon     # totals still count hidden chores


def test_kid_cards_unfinished_before_finished_within_group(cfg):
    html = kid_cards(cfg, [{"name": "Ada", "stars": 0, "chores": CHORES}], at(9))
    assert html.index("Brush (AM)") < html.index("Make bed")


def test_kid_cards_unknown_balance_and_escaping(cfg):
    html = kid_cards(cfg, [{"name": "<Ada>", "stars": None, "chores": [
        {"title": "<script>x</script>", "done": False, "points": 0, "time": None}]}], at(9))
    assert "—" in html and "<script>" not in html and "&lt;Ada&gt;" in html


def test_family_card_progress_messages():
    kids = [{"name": "Ada", "stars": 3}, {"name": "Max", "stars": 5}]
    goal = {"name": "Pizza night", "emoji": "🍕", "points": 20}
    sweep = make_cfg(star_sweep=True, star_sweep_at=dt.time(22, 0))
    assert "<b>4</b> more to" in family_card(sweep, {"stars": 8, "goal": goal}, kids)
    tonight = family_card(sweep, {"stars": 14, "goal": goal}, kids)
    assert "unlocks tonight" in tonight and "+8 ★ from Ada & Max at 10pm" in tonight
    assert "unlocked!" in family_card(sweep, {"stars": 20, "goal": goal}, kids)
    no_sweep = family_card(make_cfg(), {"stars": 14, "goal": goal}, kids)
    assert "at 10pm" not in no_sweep and "<b>6</b> more to" in no_sweep    # kids' stars aren't 'coming'
    assert family_card(make_cfg(), None) == ""


def test_grabs_section(cfg):
    html = grabs_section(cfg, [{"title": "Sweep", "points": 2, "emoji": "🧹", "done": False, "who": None},
                               {"title": "Dishes", "points": 1, "emoji": None, "done": True, "who": "Max"}])
    assert "1 left · ask a grown-up before you start" in html and "★2" in html and "✓ Max" in html
    assert grabs_section(cfg, []) == ""
    assert "ask first" in grabs_section(make_cfg(grabs_note="ask first"), [{"title": "x", "points": 0, "done": False}])


def test_build_html_smoke(cfg):
    data = {"kids": [{"name": "Ada", "stars": 1, "chores": CHORES}], "family": None, "grabs": [],
            "events": [{"title": "Swim", "start": "2026-11-10T17:00:00-08:00", "end": "2026-11-10T18:00:00-08:00"}],
            "note": " · <b>"}
    html = build_html(cfg, data, at(9))
    assert "Monday, <span>November 9</span>" in html and "Swim" in html and "&lt;b&gt;" in html
