import datetime as dt

from familydash.config import DEFAULT_COLORS, Config, parse_kids


def test_parse_kids_keeps_order_and_fills_colours():
    assert parse_kids("Ada:#111, Max ,Zed:#333") == {"Ada": "#111", "Max": DEFAULT_COLORS[1], "Zed": "#333"}
    assert parse_kids("") == {}


def test_defaults_are_safe():
    c = Config.from_env({})
    assert not c.skylight_enabled
    assert not c.tv_schedule and not c.star_sweep        # nothing touches the TV or Skylight by default
    assert c.port == 8097 and c.tv_on_at == dt.time(7, 0)


def test_tv_schedule_defaults_on_when_tv_configured():
    assert Config.from_env({"ROKU_TV_IP": "10.0.0.5"}).tv_schedule
    assert not Config.from_env({"ROKU_TV_IP": "10.0.0.5", "TV_SCHEDULE": "off"}).tv_schedule


def test_from_env_reads_everything():
    c = Config.from_env({"SKYLIGHT_EMAIL": "a@b", "SKYLIGHT_PASSWORD": "x", "SKYLIGHT_FRAME_ID": "9",
                         "KIDS": "Ada", "TZ": "Europe/London", "STAR_SWEEP": "on", "STAR_SWEEP_AT": "21:30",
                         "PUBLIC_URL": "http://h:1/"})
    assert c.skylight_enabled and c.star_sweep and c.star_sweep_at == dt.time(21, 30)
    assert str(c.tz) == "Europe/London" and c.public_url == "http://h:1" and list(c.kids) == ["Ada"]
