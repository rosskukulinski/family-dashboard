"""Minimal read-only Skylight client (stdlib only).

Skylight has no public API. This replays the browser OAuth (PKCE) login that the
Skylight web app uses, modelled on @rjhalvorson/skylight-mcp's auth.js, then calls
the same JSON endpoints the app does. The only write it supports is moving reward
points (add_points), used by the nightly star sweep.
"""
from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://app.ourskylight.com"
WEB = "https://ourskylight.com"
API_VERSION = "2026-03-01"
CLIENT_ID = "skylight-mobile"
REDIRECT_URI = f"{WEB}/welcome"
WEB_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:149.0) Gecko/20100101 Firefox/149.0"
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # surface 3xx to the caller
        return None


class SkylightError(RuntimeError):
    pass


class Skylight:
    def __init__(self, email: str, password: str, frame_id: str, timeout: int = 20):
        self.email, self.password, self.frame_id, self.timeout = email, password, frame_id, timeout
        self.token: str | None = None
        self.token_time = 0.0

    # ------------------------------------------------------------ auth

    def _open(self, opener, url, data=None, headers=None):
        req = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            return opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:  # 3xx/4xx come back as HTTPError with no-redirect
            return e

    def login(self) -> None:
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect)
        verifier = secrets.token_hex(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_hex(5)
        q = urllib.parse.urlencode({
            "client_id": CLIENT_ID, "code_challenge": challenge, "code_challenge_method": "S256",
            "redirect_uri": REDIRECT_URI, "response_type": "code", "scope": "everything",
            "state": state, "prompt": "login",
        })
        hdr = {"Accept": HTML_ACCEPT, "User-Agent": WEB_UA, "Referer": f"{WEB}/"}

        r = self._open(opener, f"{BASE}/oauth/authorize?{q}", headers=hdr)
        if r.status != 302:
            raise SkylightError(f"authorize: HTTP {r.status}")
        login_url = urllib.parse.urljoin(BASE, r.headers["Location"])

        r = self._open(opener, login_url, headers=hdr)
        m = re.search(r'name=["\']authenticity_token["\'][^>]*value=["\']([^"\']+)["\']', r.read().decode())
        if not m:
            raise SkylightError("login form: no authenticity_token")

        body = urllib.parse.urlencode({"authenticity_token": m.group(1), "email": self.email,
                                       "password": self.password}).encode()
        r = self._open(opener, f"{BASE}/auth/session", data=body, headers={
            **hdr, "Content-Type": "application/x-www-form-urlencoded", "Origin": BASE,
            "Referer": f"{BASE}/auth/session/new"})
        if r.status in (401, 422):
            raise SkylightError("invalid Skylight email or password")
        if r.status != 302:
            raise SkylightError(f"login submit: HTTP {r.status}")
        authorize_url = urllib.parse.urljoin(BASE, r.headers["Location"])

        r = self._open(opener, authorize_url, headers={**hdr, "Referer": f"{BASE}/auth/session/new"})
        if r.status != 302:
            raise SkylightError(f"post-login authorize: HTTP {r.status}")
        cb = urllib.parse.urlparse(r.headers["Location"])
        params = urllib.parse.parse_qs(cb.query)
        if params.get("state", [None])[0] != state or "code" not in params:
            raise SkylightError("OAuth callback missing code or state mismatch")

        body = urllib.parse.urlencode({
            "grant_type": "authorization_code", "client_id": CLIENT_ID, "scope": "everything",
            "redirect_uri": REDIRECT_URI, "code": params["code"][0], "code_verifier": verifier,
            "skylight_api_client_device_fingerprint": secrets.token_hex(16),
            "skylight_api_client_device_platform": "web",
            "skylight_api_client_device_name": "family-dashboard",
            "skylight_api_client_device_os_version": "unknown",
            "skylight_api_client_device_app_version": "unknown",
            "skylight_api_client_device_hardware": "Linux",
        }).encode()
        r = self._open(opener, f"{BASE}/oauth/token", data=body, headers={
            "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded",
            "Origin": WEB, "Referer": f"{WEB}/", "User-Agent": WEB_UA})
        if r.status != 200:
            raise SkylightError(f"token exchange: HTTP {r.status}")
        data = json.loads(r.read())
        self.token = data.get("access_token") or data.get("token")
        if not self.token:
            raise SkylightError("token exchange returned no token")
        self.token_time = time.time()

    # ------------------------------------------------------------ api

    def get(self, path: str, params: dict | None = None, _retry: bool = True):
        if not self.token:
            self.login()
        url = BASE + path.replace("{f}", self.frame_id)
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/json",
            "User-Agent": "SkylightMobile (web)", "Skylight-Api-Version": API_VERSION})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            if e.code == 401 and _retry:
                self.token = None
                return self.get(path, params, _retry=False)
            raise SkylightError(f"GET {path}: HTTP {e.code}") from e

    def post(self, path: str, body: dict, _retry: bool = True):
        if not self.token:
            self.login()
        req = urllib.request.Request(BASE + path.replace("{f}", self.frame_id), data=json.dumps(body).encode(),
                                     method="POST", headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/json",
            "Content-Type": "application/json", "User-Agent": "SkylightMobile (web)",
            "Skylight-Api-Version": API_VERSION})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            if e.code == 401 and _retry:
                self.token = None
                return self.post(path, body, _retry=False)
            raise SkylightError(f"POST {path}: HTTP {e.code} {e.read()[:200]!r}") from e

    def add_points(self, category_id: str, points: int):
        """Add (or, with a negative number, subtract) reward points for one profile."""
        return self.post("/api/frames/{f}/reward_points", {"category_ids": [int(category_id)], "points": int(points)})
