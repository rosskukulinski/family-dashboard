"""Render loop + tiny HTTP server (+ optional TV schedule, nightly star sweep and the
Thanksgiving-day screen with its phone page)."""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
import traceback
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Config
from .data import Loader
from .render import FIT_JS, build_html

VIEWPORT = {"width": 1920, "height": 1080}
BROWSER_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
TG_PAGE = Path(__file__).parent / "thanksgiving.html"
TG_STALE = 300          # serve the family image if the Thanksgiving one is older than this (seconds)


class QuietHandler(SimpleHTTPRequestHandler):
    """Static files from www/, plus (when the Thanksgiving screen is on) the phone page,
    its JSON API, and the per-request choice of which image the TV gets."""
    cfg: Config | None = None
    store = None          # tg_state.Store

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if self.store is not None:
            if path in ("/tg", "/tg/", "/thanksgiving"):
                return self.send_bytes(TG_PAGE.read_bytes(), "text/html; charset=utf-8")
            if path == "/api/tg":
                return self.send_json(public(self.store.view()))
        self.route_tv()
        return super().do_GET()

    def do_HEAD(self):
        self.route_tv()
        return super().do_HEAD()

    def route_tv(self):
        """The TV only ever asks for /dashboard.jpg: hand it the Thanksgiving image when
        it's that screen's turn (and the image is fresh; a stale one means the render
        loop is in trouble and the family screen is the safe answer)."""
        if self.store is None or self.path.split("?", 1)[0] != "/dashboard.jpg":
            return
        tg_img = Path(self.directory) / "thanksgiving.jpg"
        fresh = tg_img.exists() and time.time() - tg_img.stat().st_mtime < TG_STALE
        if fresh and showing_now(self.cfg, self.store) == "thanksgiving":
            self.path = "/thanksgiving.jpg"

    def do_POST(self):
        if self.store is None or self.path.split("?", 1)[0] != "/api/tg":
            return self.send_error(404)
        n = int(self.headers.get("Content-Length") or 0)
        if n > 65536:
            return self.send_error(413)
        try:
            op = json.loads(self.rfile.read(n) or b"{}")
            who = str(op.pop("who", "") or "")[:24]
            view = self.store.apply(op, who=who)
        except ValueError as e:
            return self.send_json({"error": str(e)}, 400)
        except Exception:
            traceback.print_exc()
            return self.send_json({"error": "server error"}, 500)
        self.send_json(public(view))

    def send_json(self, obj, status=200):
        self.send_bytes(json.dumps(obj).encode(), "application/json", status)

    def send_bytes(self, body: bytes, ctype: str, status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def public(view: dict) -> dict:
    return {k: v for k, v in view.items() if not k.startswith("_")}


def showing_now(cfg: Config, store) -> str:
    from .tg_state import showing
    now = store.clock()
    return showing(now, cfg, store, store.view(now))


def render_page(page, cfg: Config, data: dict, now: dt.datetime) -> str:
    html = build_html(cfg, data, now)
    page.set_content(html, wait_until="load")
    page.evaluate(FIT_JS)
    return html


def write_images(page, www, stem: str = "dashboard") -> None:
    """<stem>.png (for browsers) and <stem>.jpg (what the TV loads: ~5x smaller),
    each written atomically."""
    for ext, kind, extra in (("png", "png", {}), ("jpg", "jpeg", {"quality": 88})):
        name = f"{stem}.{ext}"
        tmp = www / f".{name}.tmp"
        page.screenshot(path=str(tmp), type=kind, **extra)
        os.replace(tmp, www / name)


def render_tg(page, cfg: Config, store, now: dt.datetime) -> None:
    from .render_tg import build_tg_html
    html = build_tg_html(cfg, store.view(now), now, store.photo())
    page.set_content(html, wait_until="load")      # fixed-size layout: no FIT_JS (it needs .left/.right)
    (cfg.www_dir / "thanksgiving.html").write_text(html)
    write_images(page, cfg.www_dir, "thanksgiving")


def render_loop(cfg: Config, loader: Loader, store=None) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        page = p.chromium.launch(args=BROWSER_ARGS).new_page(viewport=VIEWPORT)
        last_family = 0.0
        while True:
            started = time.time()
            woken = store is not None and store.changed.is_set()
            if store is not None:
                store.changed.clear()
            now = dt.datetime.now(cfg.tz)
            if not woken or time.time() - last_family > 55:
                try:
                    html = render_page(page, cfg, loader.load(now), now)
                    (cfg.www_dir / "dashboard.html").write_text(html)
                    write_images(page, cfg.www_dir)
                    last_family = time.time()
                    print(f"{now:%H:%M:%S} rendered in {time.time() - started:.1f}s", flush=True)
                except Exception:
                    traceback.print_exc()
            if store is not None:
                try:
                    render_tg(page, cfg, store, now)
                except Exception:
                    traceback.print_exc()
            # just after each minute boundary, or as soon as a phone changes something
            if store is None:
                time.sleep(max(5, 60 - (time.time() % 60)) + 1)
            else:
                store.changed.wait(timeout=max(5, 60 - (time.time() % 60)) + 1)
                if store.changed.is_set():
                    time.sleep(1.5)                      # coalesce a burst of taps


def serve(cfg: Config) -> None:
    for d in (cfg.www_dir, cfg.data_dir):
        d.mkdir(parents=True, exist_ok=True)
    store = None
    if cfg.tg_enabled:
        from .tg_state import Store
        store = Store(cfg)
        print(f"Thanksgiving screen on for {cfg.tg_date}: phone page at {cfg.public_url or ''}/tg", flush=True)
    handler = type("Handler", (QuietHandler,), {"cfg": cfg, "store": store})
    srv = ThreadingHTTPServer(("0.0.0.0", cfg.port), partial(handler, directory=str(cfg.www_dir)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"serving {cfg.www_dir} on :{cfg.port}", flush=True)

    sky = None
    if cfg.skylight_enabled:
        from .skylight import Skylight
        sky = Skylight(cfg.skylight_email, cfg.skylight_password, cfg.frame_id)
    else:
        print("Skylight not configured (SKYLIGHT_EMAIL / SKYLIGHT_PASSWORD / SKYLIGHT_FRAME_ID): "
              f"reading {cfg.data_dir / 'data.json'}", flush=True)

    if cfg.tv_schedule and cfg.roku_ip:
        from . import tv_schedule
        threading.Thread(target=tv_schedule.run_forever, args=(cfg,), daemon=True).start()
    if cfg.star_sweep and cfg.skylight_enabled:
        from . import star_sweep
        threading.Thread(target=star_sweep.run_forever, args=(cfg,), daemon=True).start()
    render_loop(cfg, Loader(cfg, sky), store)
