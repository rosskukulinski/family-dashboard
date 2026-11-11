"""Nightly star sweep: at star_sweep_at (22:00) move every star the kids hold into the
family profile in Skylight, so the kids start each day at 0. Off unless STAR_SWEEP=on.

Runs once per day. <data_dir>/sweep-state.json remembers the last date it ran, so a
restart can't move stars twice; if the service starts after star_sweep_at and today's
sweep hasn't run yet, it runs then. Every run is appended to <data_dir>/sweep-log.jsonl.

Order matters: each kid's stars are taken first, then the total actually taken is added
to the family (with retries), so a failure can never create stars from nothing; if the
family add keeps failing, the log says exactly how many to re-add.
"""
from __future__ import annotations

import datetime as dt
import json
import time
import traceback
from collections.abc import Callable

from .config import Config


def sweep(sky, kids: list[str], family: str, sleep: Callable[[float], None] = time.sleep,
          log: Callable[[str], None] = print) -> dict:
    ids = {c["attributes"]["label"]: c["id"] for c in sky.get("/api/frames/{f}/categories")["data"]}
    names = kids + [family]
    missing = [n for n in names if n not in ids]
    if missing:
        raise RuntimeError(f"Skylight profiles not found: {missing}")

    def balances() -> dict:
        b = {str(p["category_id"]): p["current_point_balance"] or 0
             for p in sky.get("/api/frames/{f}/reward_points")}
        return {n: b.get(str(ids[n]), 0) for n in names}

    before = balances()
    taken: dict[str, int] = {}
    for kid in kids:
        n = before[kid]
        if n > 0:
            sky.add_points(ids[kid], -n)
            taken[kid] = n
    total = sum(taken.values())
    added = 0
    if total:
        for attempt in range(3):
            try:
                sky.add_points(ids[family], total)
                added = total
                break
            except Exception as e:
                log(f"family add failed (attempt {attempt + 1}): {e}")
                sleep(10 * (attempt + 1))
    after = balances()
    return {"moved": taken, "family_added": added, "before": before, "after": after, "ok": added == total}


def due(now: dt.datetime, at: dt.time, last: str | None) -> bool:
    return now.time() >= at and last != now.date().isoformat()


def run_forever(cfg: Config) -> None:
    from .skylight import Skylight

    def log(msg: str) -> None:
        print(f"{dt.datetime.now(cfg.tz):%H:%M:%S} sweep: {msg}", flush=True)

    state_file, log_file = cfg.data_dir / "sweep-state.json", cfg.data_dir / "sweep-log.jsonl"
    sky = Skylight(cfg.skylight_email, cfg.skylight_password, cfg.frame_id)
    kids = list(cfg.kids)
    log(f"nightly at {cfg.star_sweep_at:%H:%M}: {', '.join(kids)} -> {cfg.family_profile}")
    while True:
        now = dt.datetime.now(cfg.tz)
        try:
            last = json.loads(state_file.read_text()).get("last") if state_file.exists() else None
        except Exception:
            last = None
        if due(now, cfg.star_sweep_at, last):
            # mark first: never run twice for the same day, even if we crash mid-way
            state_file.write_text(json.dumps({"last": now.date().isoformat()}))
            entry: dict = {"at": now.isoformat(timespec="seconds"), "kind": "nightly"}
            try:
                res = sweep(sky, kids, cfg.family_profile, log=log)
                entry.update(res)
                log(f"moved {res['moved']} -> {cfg.family_profile} +{res['family_added']}"
                    + ("" if res["ok"] else "  !! FAMILY ADD FAILED - re-add manually, see sweep-log.jsonl"))
            except Exception as e:
                entry["error"] = repr(e)
                log(f"error: {e!r}")
                traceback.print_exc()
            with open(log_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        time.sleep(30)
