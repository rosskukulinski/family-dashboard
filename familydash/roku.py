"""Package the Roku app (roku/) for this install and side-load it onto the TV.

The app source has two placeholders filled in at packaging time:
  @DASHBOARD_URL@  -> <PUBLIC_URL>/dashboard.jpg   (how the TV reaches this server)
  @VERSION_*@      -> the familydash version, so updates can be detected

    python -m familydash roku-package out.zip
    python -m familydash roku-install           # skips if the TV already has this version
"""
from __future__ import annotations

import io
import re
import urllib.request
import uuid
import zipfile
from pathlib import Path

from . import __version__
from .config import Config

APP_DIR = Path(__file__).resolve().parent.parent / "roku"


def version_parts(version: str = __version__) -> tuple[int, int, int]:
    nums = [int(x) for x in re.findall(r"\d+", version)[:3]]
    return tuple(nums + [0] * (3 - len(nums)))  # type: ignore[return-value]


def package(cfg: Config, app_dir: Path = APP_DIR, version: str = __version__) -> bytes:
    if not cfg.public_url:
        raise ValueError("PUBLIC_URL must be set (e.g. http://192.168.1.10:8097) so the TV can reach the server")
    major, minor, build = version_parts(version)
    subs = {"@DASHBOARD_URL@": f"{cfg.public_url}/dashboard.jpg",
            "@VERSION_MAJOR@": str(major), "@VERSION_MINOR@": str(minor), "@VERSION_BUILD@": str(build)}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(p for p in app_dir.rglob("*") if p.is_file()):
            data = f.read_bytes()
            if f.suffix in ("", ".xml", ".brs") or f.name == "manifest":
                text = data.decode()
                for k, v in subs.items():
                    text = text.replace(k, v)
                data = text.encode()
            z.writestr(str(f.relative_to(app_dir)), data)
    return buf.getvalue()


def installed_version(cfg: Config) -> str | None:
    """Version of the side-loaded app on the TV (ECP), or None."""
    with urllib.request.urlopen(f"http://{cfg.roku_ip}:8060/query/apps", timeout=5) as r:
        m = re.search(r'<app id="dev"[^>]*version="([^"]+)"', r.read().decode())
    return m.group(1) if m else None


def install(cfg: Config, zip_bytes: bytes) -> str:
    """Upload via the TV's developer installer (HTTP digest auth, user 'rokudev')."""
    url = f"http://{cfg.roku_ip}/plugin_install"
    pw = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    pw.add_password(None, url, "rokudev", cfg.roku_dev_password)
    opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(pw))
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"mysubmit\"\r\n\r\nInstall\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"archive\"; filename=\"app.zip\"\r\n"
            f"Content-Type: application/zip\r\n\r\n").encode() + zip_bytes + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with opener.open(req, timeout=60) as r:
        page = r.read().decode("utf-8", "replace")
    m = re.search(r"(Install Success|Identical to previous version|Install Failure[^<]*)", page)
    result = m.group(1) if m else "unknown response"
    if "Failure" in result or result == "unknown response":
        raise RuntimeError(f"Roku install failed: {result}")
    return result


def install_if_needed(cfg: Config, force: bool = False) -> str:
    want = ".".join(map(str, version_parts()))
    have = installed_version(cfg)
    if have == want and not force:
        return f"TV already has {want}"
    return f"{have or 'none'} -> {want}: {install(cfg, package(cfg))}"
