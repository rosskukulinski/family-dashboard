"""Skylight API responses -> the dashboard's data model.

The model (also accepted from a static JSON file, see load()):
  {"kids":   [{"name", "stars", "chores": [{"title", "done", "points", "time", "position"}]}],
   "family": {"stars", "goal": {"name", "emoji", "points"} | None} | None,
   "grabs":  [{"title", "points", "emoji", "done", "who"}],
   "events": [{"title", "start", "end", "all_day", "location", "who"}]}
"""
from __future__ import annotations

import datetime as dt
import json
import time
import traceback
from pathlib import Path

from .config import Config


def _rel_id(obj: dict, name: str) -> str | None:
    return (((obj.get("relationships") or {}).get(name) or {}).get("data") or {}).get("id")


def build_model(cfg: Config, categories: dict, reward_points: list, chores: dict,
                rewards: dict, events: dict) -> dict:
    """Pure transform of raw Skylight responses (JSON:API style) into the model."""
    cats = {c["id"]: c["attributes"].get("label") for c in categories["data"]}
    by_name = {v: k for k, v in cats.items()}
    points = {str(p["category_id"]): p for p in reward_points}

    grabs = []
    for c in chores["data"]:
        a = c["attributes"]
        if not a.get("up_for_grabs"):
            continue
        done = a.get("status") == "complete"
        # whoever claimed it is recorded as the "completed_category"
        grabs.append({"title": a.get("summary") or "", "points": a.get("reward_points") or 0,
                      "emoji": a.get("emoji_icon"), "done": done,
                      "who": cats.get(_rel_id(c, "completed_category")) if done else None})
    grabs.sort(key=lambda g: (g["done"], -g["points"]))

    kids = []
    for name in cfg.kids:
        cid = by_name.get(name)
        mine = [c["attributes"] for c in chores["data"]
                if not c["attributes"].get("up_for_grabs") and _rel_id(c, "category") == cid]
        mine.sort(key=lambda a: (a.get("position") is None, a.get("position") or 0))
        kids.append({
            "name": name,
            "stars": (points.get(cid) or {}).get("current_point_balance") if cid else None,
            "chores": [{"title": a.get("summary") or "", "done": a.get("status") == "complete",
                        "points": a.get("reward_points") or 0, "time": a.get("start_time"),
                        "position": a.get("position")} for a in mine],
        })

    family = None
    fam_id = by_name.get(cfg.family_profile)
    if fam_id:
        bal = (points.get(fam_id) or {}).get("current_point_balance") or 0
        goals = sorted((r["attributes"] for r in rewards["data"]
                        if _rel_id(r, "category") == fam_id and not r["attributes"].get("redeemed_at")),
                       key=lambda a: a.get("point_value") or 0)
        # next goal: the cheapest one not yet reached, else the biggest one already reached
        goal = next((g for g in goals if (g.get("point_value") or 0) > bal), goals[-1] if goals else None)
        family = {"stars": bal, "goal": goal and {"name": goal.get("name"), "emoji": goal.get("emoji_icon") or "🎉",
                                                  "points": goal.get("point_value") or 0}}

    evs = []
    for e in events["data"]:
        a = e["attributes"]
        evs.append({"title": a.get("summary") or "(busy)", "start": a["starts_at"], "end": a.get("ends_at"),
                    "all_day": bool(a.get("all_day")), "location": a.get("location"),
                    "who": cats.get(_rel_id(e, "category"))})
    return {"kids": kids, "family": family, "grabs": grabs, "events": evs}


def fetch(sky, cfg: Config, now: dt.datetime) -> dict:
    today = now.date().isoformat()
    return build_model(
        cfg,
        categories=sky.get("/api/frames/{f}/categories"),
        reward_points=sky.get("/api/frames/{f}/reward_points"),
        # up-for-grabs chores are only returned when asked for explicitly
        chores=sky.get("/api/frames/{f}/chores", {"after": today, "before": today, "include_up_for_grabs": "true"}),
        rewards=sky.get("/api/frames/{f}/rewards"),
        events=sky.get("/api/frames/{f}/calendar_events", {
            "date_min": today, "date_max": (now.date() + dt.timedelta(days=2)).isoformat(),
            "timezone": str(cfg.tz)}),
    )


class Loader:
    """Skylight, cached for cfg.skylight_every seconds; on failure keeps the last good
    copy (with a note); without Skylight configured, reads <data_dir>/data.json."""

    def __init__(self, cfg: Config, sky=None, clock=time.time):
        self.cfg, self.sky, self.clock = cfg, sky, clock
        self.data: dict | None = None
        self.at = 0.0
        self.error: str | None = None

    def load(self, now: dt.datetime) -> dict:
        if self.sky is not None and self.clock() - self.at >= self.cfg.skylight_every:
            try:
                self.data, self.error = fetch(self.sky, self.cfg, now), None
                (self.cfg.data_dir / "skylight-last.json").write_text(json.dumps(self.data, indent=1))
            except Exception as e:
                traceback.print_exc()
                self.error = str(e)[:80]
            self.at = self.clock()
        if self.data:
            d = dict(self.data)
            if self.error:
                d["note"] = " · Skylight unreachable, showing last data"
            return d
        static = Path(self.cfg.data_dir) / "data.json"
        if static.exists():
            return json.loads(static.read_text())
        return {"kids": [{"name": n, "stars": None, "chores": []} for n in self.cfg.kids],
                "family": None, "grabs": [], "events": [],
                "note": " · waiting for data" if self.sky is not None else " · no data source configured"}
