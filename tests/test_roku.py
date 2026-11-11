import io
import zipfile

import pytest

from familydash import __version__
from familydash.roku import package, version_parts
from tests.conftest import make_cfg


def test_version_parts():
    assert version_parts("1.2.3") == (1, 2, 3) and version_parts("0.5") == (0, 5, 0)


def test_package_fills_placeholders():
    z = zipfile.ZipFile(io.BytesIO(package(make_cfg(public_url="http://10.0.0.2:8097"))))
    names = set(z.namelist())
    assert {"manifest", "source/main.brs", "components/MainScene.xml"} <= names
    text = "".join(z.read(n).decode() for n in names if not n.endswith(".png"))
    assert "@DASHBOARD_URL@" not in text and "@VERSION_" not in text   # no unfilled placeholders
    assert 'value="http://10.0.0.2:8097/dashboard.jpg"' in z.read("components/MainScene.xml").decode()
    major, minor, build = version_parts(__version__)
    manifest = z.read("manifest").decode()
    assert f"major_version={major}" in manifest and f"build_version={build}" in manifest


def test_package_needs_public_url():
    with pytest.raises(ValueError):
        package(make_cfg(public_url=""))


def test_package_includes_home_screen_icons():
    z = zipfile.ZipFile(io.BytesIO(package(make_cfg(public_url="http://10.0.0.2:8097"))))
    manifest = z.read("manifest").decode()
    for res in ("fhd", "hd", "sd"):
        assert f"mm_icon_focus_{res}=pkg:/images/icon_{res}.png" in manifest
        assert z.read(f"images/icon_{res}.png").startswith(b"\x89PNG")   # binary kept intact
