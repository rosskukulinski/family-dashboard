"""python -m familydash [serve | render-once DATA.json OUT.png [--at ISO] | roku-package OUT.zip | roku-install [--force]]"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from . import __version__
from .config import Config


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="familydash")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="render every minute and serve the images (default)")
    r = sub.add_parser("render-once", help="render one image from a model JSON file")
    r.add_argument("data"), r.add_argument("out"), r.add_argument("--at", help="ISO time to render as")
    p = sub.add_parser("roku-package", help="build the Roku app zip for this install")
    p.add_argument("out")
    i = sub.add_parser("roku-install", help="side-load the Roku app onto ROKU_TV_IP if it's out of date")
    i.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    cfg = Config.from_env()

    if a.cmd in (None, "serve"):
        from .server import serve
        serve(cfg)
    elif a.cmd == "render-once":
        from playwright.sync_api import sync_playwright

        from .server import BROWSER_ARGS, VIEWPORT, render_page
        now = dt.datetime.fromisoformat(a.at).astimezone(cfg.tz) if a.at else dt.datetime.now(cfg.tz)
        with sync_playwright() as pw:
            page = pw.chromium.launch(args=BROWSER_ARGS).new_page(viewport=VIEWPORT)
            render_page(page, cfg, json.loads(Path(a.data).read_text()), now)
            page.screenshot(path=a.out)
        print(a.out)
    elif a.cmd == "roku-package":
        from .roku import package
        Path(a.out).write_bytes(package(cfg))
        print(a.out)
    elif a.cmd == "roku-install":
        from .roku import install_if_needed
        print(install_if_needed(cfg, force=a.force))


if __name__ == "__main__":
    main()
