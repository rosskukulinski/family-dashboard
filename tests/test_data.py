import json
from pathlib import Path

from familydash.data import Loader, build_model, fetch

API = json.loads((Path(__file__).parent / "fixtures" / "skylight_api.json").read_text())


def model(cfg):
    return build_model(cfg, API["categories"], API["reward_points"], API["chores"], API["rewards"], API["events"])


def test_kids_get_their_own_chores_and_balance(cfg):
    m = model(cfg)
    ada, max_ = m["kids"]
    assert (ada["name"], ada["stars"], max_["stars"]) == ("Ada", 3, 5)
    titles = [c["title"] for c in ada["chores"]]
    assert titles[0] == "Make bed" and titles[-1] == "Brush teeth (AM)"                 # Skylight position order
    assert {c["title"] for c in max_["chores"]} == {"Make bed", "Feed the cat"}
    assert all(c["title"] != "Pay the bills" for k in m["kids"] for c in k["chores"])     # parents excluded


def test_up_for_grabs_are_separate_and_record_who_claimed(cfg):
    grabs = model(cfg)["grabs"]
    assert [g["title"] for g in grabs] == ["Clean dining table", "Sweep the floor"]          # open first
    assert grabs[1] == {"title": "Sweep the floor", "points": 2, "emoji": None, "done": True, "who": "Max"}


def test_family_goal_is_cheapest_unreached_family_reward(cfg):
    fam = model(cfg)["family"]
    assert fam["stars"] == 18
    assert fam["goal"] == {"name": "Pizza night", "emoji": "🍕", "points": 20}             # not the kid's iPad reward


def test_family_goal_when_everything_reached(cfg):
    pts = [dict(p, current_point_balance=99) if p["category_id"] == 12 else p for p in API["reward_points"]]
    fam = build_model(cfg, API["categories"], pts, API["chores"], API["rewards"], API["events"])["family"]
    assert fam["goal"]["name"] == "Zoo trip"


def test_events(cfg):
    evs = {e["title"]: e for e in model(cfg)["events"]}
    assert evs["Max swim"]["who"] == "family" and evs["No school"]["all_day"]


def test_unknown_kid_has_no_balance(cfg):
    from tests.conftest import make_cfg
    m = build_model(make_cfg(kids={"Nobody": "#000"}), API["categories"], API["reward_points"],
                    API["chores"], API["rewards"], API["events"])
    assert m["kids"] == [{"name": "Nobody", "stars": None, "chores": []}]


class FakeSky:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if self.fail:
            raise OSError("down")
        key = path.rsplit("/", 1)[1]
        return API[{"calendar_events": "events"}.get(key, key)]


def test_fetch_asks_for_up_for_grabs(cfg):
    from tests.conftest import at
    sky = FakeSky()
    fetch(sky, cfg, at(9))
    chores = next(p for path, p in sky.calls if path.endswith("chores"))
    assert chores == {"after": "2026-11-09", "before": "2026-11-09", "include_up_for_grabs": "true"}


def test_loader_caches_and_keeps_last_good_copy(cfg, tmp_path):
    from tests.conftest import at, make_cfg
    cfg = make_cfg(data_dir=tmp_path)
    clock = [1000.0]
    sky = FakeSky()
    loader = Loader(cfg, sky, clock=lambda: clock[0])
    first = loader.load(at(9))
    n = len(sky.calls)
    loader.load(at(9))
    assert len(sky.calls) == n                               # cached
    sky.fail, clock[0] = True, clock[0] + cfg.skylight_every
    stale = loader.load(at(9))
    assert stale["kids"] == first["kids"] and "unreachable" in stale["note"]
    assert (tmp_path / "skylight-last.json").exists()


def test_loader_without_skylight_uses_static_file_or_placeholder(tmp_path):
    from tests.conftest import at, make_cfg
    cfg = make_cfg(data_dir=tmp_path)
    assert Loader(cfg, None).load(at(9))["note"] == " · no data source configured"
    (tmp_path / "data.json").write_text(json.dumps({"kids": [], "events": []}))
    assert Loader(cfg, None).load(at(9)) == {"kids": [], "events": []}
