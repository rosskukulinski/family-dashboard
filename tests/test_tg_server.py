"""The HTTP side: phone page, JSON API and which image the TV gets."""
import datetime as dt
import json
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

import pytest

from familydash.config import Config
from familydash.server import QuietHandler
from familydash.tg_state import Store
from tests.conftest import TZ


@pytest.fixture
def srv(tmp_path):
    www, data = tmp_path / "www", tmp_path / "data"
    www.mkdir(), data.mkdir()
    (www / "dashboard.jpg").write_bytes(b"FAMILY")
    (www / "thanksgiving.jpg").write_bytes(b"THANKSGIVING-IMAGE")
    cfg = Config.from_env({"TG_DATE": "2026-11-26", "DATA_DIR": str(data), "WWW_DIR": str(www), "TZ": "America/Los_Angeles"})
    store = Store(cfg, clock=lambda: dt.datetime(2026, 11, 26, 9, 1, 30, tzinfo=TZ))
    handler = type("H", (QuietHandler,), {"cfg": cfg, "store": store})
    s = ThreadingHTTPServer(("127.0.0.1", 0), partial(handler, directory=str(www)))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}", store
    s.shutdown()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read()


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read()
        return e.code, (json.loads(body) if body.startswith(b"{") else {})


def test_page_api_and_rotation(srv):
    base, store = srv
    status, body = get(base + "/tg")
    assert status == 200 and b"Thanksgiving" in body and b"/api/tg" in body
    status, body = get(base + "/api/tg")
    view = json.loads(body)
    assert status == 200 and view["dinner_label"] == "4:00pm" and not any(k.startswith("_") for k in view)
    status, view = post(base + "/api/tg", {"op": "tv_mode", "mode": "thanksgiving", "who": "Ross"})
    assert status == 200 and view["tv"]["mode"] == "thanksgiving"
    assert get(base + "/dashboard.jpg?t=1")[1] == b"THANKSGIVING-IMAGE"     # the TV's request is redirected
    post(base + "/api/tg", {"op": "tv_mode", "mode": "family"})
    assert get(base + "/dashboard.jpg?t=2")[1] == b"FAMILY"
    status, err = post(base + "/api/tg", {"op": "done", "step": "nothing"})
    assert status == 400 and "bad op" in err["error"]
    status, view = post(base + "/api/tg", {"op": "done", "step": "turkey_out_fridge", "who": "Nicole"})
    assert status == 200 and store.state["done"]["turkey_out_fridge"]["by"] == "Nicole"
    assert store.changed.is_set()


def test_stale_thanksgiving_image_falls_back_to_family(srv, tmp_path):
    import os
    import time
    base, store = srv
    post(base + "/api/tg", {"op": "tv_mode", "mode": "thanksgiving"})
    old = time.time() - 1000
    os.utime(tmp_path / "www" / "thanksgiving.jpg", (old, old))
    assert get(base + "/dashboard.jpg")[1] == b"FAMILY"


def test_without_thanksgiving_the_server_is_unchanged(tmp_path):
    www = tmp_path / "www"
    www.mkdir()
    (www / "dashboard.jpg").write_bytes(b"FAMILY")
    cfg = Config.from_env({"WWW_DIR": str(www)})
    handler = type("H", (QuietHandler,), {"cfg": cfg, "store": None})
    s = ThreadingHTTPServer(("127.0.0.1", 0), partial(handler, directory=str(www)))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{s.server_address[1]}"
    try:
        assert get(base + "/dashboard.jpg")[1] == b"FAMILY"
        with pytest.raises(urllib.error.HTTPError):
            get(base + "/tg")
        assert post(base + "/api/tg", {"op": "undo"})[0] == 404
    finally:
        s.shutdown()
