import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from familydash.config import Config, parse_kids

TZ = ZoneInfo("America/Los_Angeles")


def make_cfg(**kw) -> Config:
    base = dict(kids=parse_kids("Ada:#f472b6,Max:#60a5fa"), family_profile="family", tz=TZ,
                frame_id="1", skylight_email="e", skylight_password="p", public_url="http://dash.test:8097")
    base.update(kw)
    return Config(**base)


@pytest.fixture
def cfg() -> Config:
    return make_cfg()


def at(h: int, m: int = 0, day: int = 9) -> dt.datetime:
    return dt.datetime(2026, 11, day, h, m, tzinfo=TZ)
