"""Drive the real login flow and API calls against a local fake Skylight server."""
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from familydash import skylight
from familydash.skylight import Skylight, SkylightError


class Fake(BaseHTTPRequestHandler):
    state = None
    tokens_issued = 0
    reject_next_api = 0
    posted = []

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/oauth/authorize" and q.get("prompt") == ["login"]:
            Fake.state = q["state"][0]
            assert q["code_challenge_method"] == ["S256"]
            return self._send(302, headers=[("Location", "/auth/session/new"), ("Set-Cookie", "sess=1; Path=/")])
        if u.path == "/auth/session/new":
            return self._send(200, b'<form><input type="hidden" name="authenticity_token" value="tok123"></form>')
        if u.path == "/oauth/authorize":
            assert "sess=1" in (self.headers.get("Cookie") or "")
            return self._send(302, headers=[("Location", f"https://ourskylight.com/welcome?code=c0de&state={Fake.state}")])
        if u.path.startswith("/api/"):
            if Fake.reject_next_api:
                Fake.reject_next_api -= 1
                return self._send(401)
            assert self.headers["Authorization"] == f"Bearer t{Fake.tokens_issued}"
            return self._send(200, json.dumps({"path": u.path, "q": q}).encode())
        self._send(404)

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        if self.path == "/auth/session":
            f = urllib.parse.parse_qs(body)
            if f.get("password") != ["right"] or f.get("authenticity_token") != ["tok123"]:
                return self._send(422)
            return self._send(302, headers=[("Location", "/oauth/authorize?resume=1")])
        if self.path == "/oauth/token":
            f = urllib.parse.parse_qs(body)
            assert f["code"] == ["c0de"] and f["grant_type"] == ["authorization_code"] and f["code_verifier"]
            Fake.tokens_issued += 1
            return self._send(200, json.dumps({"access_token": f"t{Fake.tokens_issued}"}).encode())
        if self.path.startswith("/api/"):
            Fake.posted.append((self.path, json.loads(body)))
            return self._send(200, b'{"ok": true}')
        self._send(404)


@pytest.fixture
def server(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(skylight, "BASE", f"http://127.0.0.1:{srv.server_address[1]}")
    Fake.tokens_issued, Fake.reject_next_api, Fake.posted = 0, 0, []
    yield
    srv.shutdown()


def test_login_and_get(server):
    s = Skylight("me@example.com", "right", "42")
    r = s.get("/api/frames/{f}/chores", {"after": "2026-11-09", "skip": None})
    assert r["path"] == "/api/frames/42/chores" and r["q"] == {"after": ["2026-11-09"]}
    assert Fake.tokens_issued == 1


def test_bad_password(server):
    with pytest.raises(SkylightError, match="invalid"):
        Skylight("me@example.com", "wrong", "42").get("/api/frames/{f}/x")


def test_expired_token_relogs_in_once(server):
    s = Skylight("me@example.com", "right", "42")
    s.get("/api/frames/{f}/a")
    Fake.reject_next_api = 1
    s.get("/api/frames/{f}/b")
    assert Fake.tokens_issued == 2


def test_add_points_body(server):
    Skylight("me@example.com", "right", "42").add_points("12", -3)
    assert Fake.posted == [("/api/frames/42/reward_points", {"category_ids": [12], "points": -3})]
