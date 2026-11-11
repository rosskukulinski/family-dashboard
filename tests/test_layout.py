"""Render real pages in headless Chromium and check the fit logic (needs: playwright
install chromium). Run with: pytest -m browser"""

import pytest

from familydash.render import FIT_JS, build_html
from tests.conftest import at, make_cfg

pytestmark = pytest.mark.browser
sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def page():
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(args=["--no-sandbox"])
        except Exception as e:  # browser not installed
            pytest.skip(f"chromium unavailable: {e}")
        yield browser.new_page(viewport={"width": 1920, "height": 1080})
        browser.close()


def ev(day, h, title, m=0, loc=None):
    return {"title": title, "start": f"2026-11-{day:02d}T{h:02d}:{m:02d}:00-08:00",
            "end": f"2026-11-{day:02d}T{h + 1:02d}:{m:02d}:00-08:00", "location": loc}


def busy_day():
    return {
        "kids": [{"name": "Ada", "stars": 14, "chores": [
                     {"title": f"Chore {i}", "done": i % 4 == 0, "points": 1,
                      "time": ["06:00", "14:00", "20:00"][i % 3], "position": i} for i in range(14)]},
                 {"name": "Max", "stars": 7, "chores": [{"title": "Brush teeth", "done": True, "points": 1, "time": "20:00"}]}],
        "family": {"stars": 13, "goal": {"name": "Pizza night", "emoji": "🍕", "points": 20}},
        "grabs": [{"title": f"Job {i}", "points": 2, "emoji": None, "done": False, "who": None} for i in range(7)],
        "events": [ev(9, h, f"Today {h}", loc="Somewhere") for h in (8, 9, 12, 13, 15, 17, 18, 19)]
                + [ev(10, h, f"Tomorrow {h}") for h in (8, 10, 14, 16, 18)],
    }


def render(page, data, now):
    page.set_content(build_html(make_cfg(star_sweep=True), data, now))
    page.evaluate(FIT_JS)
    return page.evaluate("""() => {
      const fits = s => { const e = document.querySelector(s); return e.scrollHeight <= e.clientHeight + 1; };
      return {left: fits('.left'), right: fits('.right'),
              today: [...document.querySelectorAll('[data-key=today] .ev .title')].map(e => e.textContent),
              markers: [...document.querySelectorAll('.more')].map(e => e.textContent),
              family: document.querySelector('.family').getBoundingClientRect().bottom};
    }""")


def test_busy_day_fits_and_keeps_upcoming_events(page):
    r = render(page, busy_day(), at(13, 5))
    assert r["left"] and r["right"]
    for h in (13, 15, 17, 18, 19):                      # every upcoming event of today stays visible
        assert f"Today {h}" in r["today"]
    assert any(m.endswith("earlier") for m in r["markers"])   # finished ones folded away first
    assert r["family"] <= 1080 - 60 + 2                  # family card pinned inside the bottom padding (sub-pixel slack)


def test_quiet_day_fits_without_markers(page):
    data = {"kids": [{"name": "Ada", "stars": 0, "chores": [{"title": "Make bed", "done": False, "points": 1, "time": "06:00"}]}],
            "family": {"stars": 0, "goal": None}, "grabs": [], "events": [ev(9, 17, "Swim")]}
    r = render(page, data, at(9))
    assert r["left"] and r["right"] and r["markers"] == []
