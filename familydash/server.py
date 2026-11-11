"""Render loop + tiny HTTP server (+ optional TV schedule and nightly star sweep)."""
from __future__ import annotations

import datetime as dt
import os
import threading
import time
import traceback
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from .config import Config
from .data import Loader
from .render import FIT_JS, build_html

VIEWPORT = {"width": 1920, "height": 1080}
BROWSER_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]


class QuietHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


def render_page(page, cfg: Config, data: dict, now: dt.datetime) -> str:
    html = build_html(cfg, data, now)
    page.set_content(html, wait_until="load")
    page.evaluate(FIT_JS)
    return html


def write_images(page, www) -> None:
    """dashboard.png (for browsers) and dashboard.jpg (what the TV loads: ~5x smaller),
    each written atomically."""
    for name, kind, extra in (("dashboard.png", "png", {}), ("dashboard.jpg", "jpeg", {"quality": 88})):
        tmp = www / f".{name}.tmp"
        page.screenshot(path=str(tmp), type=kind, **extra)
        os.replace(tmp, www / name)


def render_loop(cfg: Config, loader: Loader) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        page = p.chromium.launch(args=BROWSER_ARGS).new_page(viewport=VIEWPORT)
        while True:
            started = time.time()
            try:
                now = dt.datetime.now(cfg.tz)
                html = render_page(page, cfg, loader.load(now), now)
                (cfg.www_dir / "dashboard.html").write_text(html)
                write_images(page, cfg.www_dir)
                print(f"{now:%H:%M:%S} rendered in {time.time() - started:.1f}s", flush=True)
            except Exception:
                traceback.print_exc()
            time.sleep(max(5, 60 - (time.time() % 60)) + 1)   # just after each minute boundary


def serve(cfg: Config) -> None:
    for d in (cfg.www_dir, cfg.data_dir):
        d.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer(("0.0.0.0", cfg.port), partial(QuietHandler, directory=str(cfg.www_dir)))
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
    render_loop(cfg, Loader(cfg, sky))
