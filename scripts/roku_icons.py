"""Render the Roku home-screen icons (roku/images/icon_*.png) from the SVG below.

    python scripts/roku_icons.py

Roku focus-icon sizes: FHD 540x405, HD 290x218, SD 246x140. The artwork is drawn in a
540x405 box and centred ("meet") in each size, so SD gets a little side padding.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "roku" / "images"
SIZES = {"fhd": (540, 405), "hd": (290, 218), "sd": (246, 140)}

STAR = ("M0,-1 L0.2245,-0.309 L0.951,-0.309 L0.3633,0.118 L0.5878,0.809 L0,0.382 "
        "L-0.5878,0.809 L-0.3633,0.118 L-0.951,-0.309 L-0.2245,-0.309 Z")

SVG = f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 540 405" width="100%" height="100%"
     preserveAspectRatio="xMidYMid meet">
  <defs>
    <linearGradient id="fill" x1="0" x2="1">
      <stop offset="0" stop-color="#facc15"/><stop offset="1" stop-color="#f472b6"/>
    </linearGradient>
  </defs>
  <!-- checklist card -->
  <rect x="120" y="62" width="230" height="220" rx="30" fill="rgba(255,255,255,0.07)" stroke="#60a5fa" stroke-width="7"/>
  <g stroke-linecap="round" stroke-linejoin="round">
    <rect x="148" y="98" width="38" height="38" rx="10" fill="#60a5fa"/>
    <path d="M157 117 l8 8 l14 -16" stroke="#0d1324" stroke-width="7" fill="none"/>
    <line x1="204" y1="117" x2="318" y2="117" stroke="#64748b" stroke-width="12"/>
    <rect x="148" y="156" width="38" height="38" rx="10" fill="#60a5fa"/>
    <path d="M157 175 l8 8 l14 -16" stroke="#0d1324" stroke-width="7" fill="none"/>
    <line x1="204" y1="175" x2="318" y2="175" stroke="#64748b" stroke-width="12"/>
    <rect x="149.5" y="215.5" width="35" height="35" rx="9" fill="none" stroke="#94a3b8" stroke-width="5"/>
    <line x1="204" y1="233" x2="290" y2="233" stroke="#e2e8f0" stroke-width="12"/>
  </g>
  <!-- star -->
  <path d="{STAR}" transform="translate(372 222) scale(82)" fill="#facc15" stroke="#0d1324"
        stroke-width="0.09" stroke-linejoin="round"/>
  <!-- progress bar -->
  <rect x="120" y="306" width="300" height="16" rx="8" fill="rgba(255,255,255,0.12)"/>
  <rect x="120" y="306" width="200" height="16" rx="8" fill="url(#fill)"/>
  <text x="270" y="374" text-anchor="middle" fill="#fde68a"
        font-family="Inter, 'Helvetica Neue', Arial, sans-serif" font-size="40" font-weight="800">Family Dashboard</text>
</svg>"""

PAGE = f"""<!doctype html><html><body style="margin:0;width:100vw;height:100vh;overflow:hidden;
background:radial-gradient(circle at 15% 10%, #1e2a4a 0%, #0d1324 55%, #080c18 100%)">{SVG}</body></html>"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, (w, h) in SIZES.items():
            page = browser.new_page(viewport={"width": w, "height": h})
            page.set_content(PAGE)
            page.screenshot(path=OUT / f"icon_{name}.png")
            page.close()
        browser.close()
    print(f"wrote {', '.join(f'icon_{n}.png' for n in SIZES)} to {OUT}")


if __name__ == "__main__":
    main()
