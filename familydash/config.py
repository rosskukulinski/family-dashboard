"""All settings come from environment variables (see deploy/.env.example).

Nothing family-specific lives in the code: kid names, colours, the Skylight frame and
the TV's address are all configuration.
"""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_COLORS = ["#f472b6", "#60a5fa", "#34d399", "#fbbf24", "#a78bfa", "#fb923c"]


def _time(value: str) -> dt.time:
    return dt.time.fromisoformat(value)


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def parse_kids(spec: str) -> dict[str, str]:
    """'Ada:#f472b6,Max' -> {'Ada': '#f472b6', 'Max': <next default colour>} (order kept)."""
    kids: dict[str, str] = {}
    for i, part in enumerate(p.strip() for p in spec.split(",") if p.strip()):
        name, _, color = part.partition(":")
        kids[name.strip()] = color.strip() or DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
    return kids


@dataclass(frozen=True)
class Config:
    # Skylight
    skylight_email: str = ""
    skylight_password: str = ""
    frame_id: str = ""
    kids: dict[str, str] = field(default_factory=dict)      # name -> colour, in display order
    family_profile: str = "family"
    skylight_every: int = 120
    # rendering / serving
    tz: ZoneInfo = ZoneInfo("UTC")
    port: int = 8097
    public_url: str = ""                                    # how the TV reaches this server
    data_dir: Path = Path("data")
    www_dir: Path = Path("www")
    # TV (Roku ECP) schedule
    roku_ip: str = ""
    roku_dev_password: str = ""
    tv_schedule: bool = False
    tv_on_at: dt.time = dt.time(7, 0)
    tv_off_at: dt.time = dt.time(20, 0)
    tv_home_idle_min: int = 5
    tv_off_idle_min: int = 15
    tv_wake_settle: int = 60
    # nightly star sweep (moves every kid's stars into the family profile)
    star_sweep: bool = False
    star_sweep_at: dt.time = dt.time(22, 0)
    # wording
    grabs_note: str = "ask a grown-up before you start"

    @property
    def skylight_enabled(self) -> bool:
        return bool(self.skylight_email and self.skylight_password and self.frame_id)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Config:
        e = os.environ if env is None else env
        g = e.get
        roku_ip = g("ROKU_TV_IP", "")
        return cls(
            skylight_email=g("SKYLIGHT_EMAIL", ""),
            skylight_password=g("SKYLIGHT_PASSWORD", ""),
            frame_id=g("SKYLIGHT_FRAME_ID", ""),
            kids=parse_kids(g("KIDS", "")),
            family_profile=g("FAMILY_PROFILE", "family"),
            skylight_every=int(g("SKYLIGHT_EVERY_SECONDS", "120")),
            tz=ZoneInfo(g("TZ", "UTC")),
            port=int(g("PORT", "8097")),
            public_url=g("PUBLIC_URL", "").rstrip("/"),
            data_dir=Path(g("DATA_DIR", "data")),
            www_dir=Path(g("WWW_DIR", "www")),
            roku_ip=roku_ip,
            roku_dev_password=g("ROKU_DEV_PASSWORD", ""),
            tv_schedule=_bool(g("TV_SCHEDULE"), default=bool(roku_ip)),
            tv_on_at=_time(g("TV_ON_AT", "07:00")),
            tv_off_at=_time(g("TV_OFF_AT", "20:00")),
            tv_home_idle_min=int(g("TV_HOME_IDLE_MIN", "5")),
            tv_off_idle_min=int(g("TV_OFF_IDLE_MIN", "15")),
            tv_wake_settle=int(g("TV_WAKE_SETTLE", "60")),
            star_sweep=_bool(g("STAR_SWEEP"), default=False),
            star_sweep_at=_time(g("STAR_SWEEP_AT", "22:00")),
            grabs_note=g("GRABS_NOTE", "ask a grown-up before you start"),
        )
