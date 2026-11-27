"""Render the brand images from docs/brand/icon.svg.

    uv run python packaging/render_brand.py

Writes:
  docs/brand/icon-1024.png, icon-512.png, icon-128.png
                                           icon on a transparent background
  docs/brand/logo.png                      icon and name, for the README
  docs/brand/social-preview.png            1280x640, for GitHub's link preview
  src/openwarframe/app/static/icon.ico     Windows icon (exe, desktop shortcut)

Needs Chrome or Edge (headless) and Pillow. Works offline: the name uses Cinzel (the
app's display font) when it is installed on this machine, otherwise Georgia.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from openwarframe.printing import find_browser

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "docs" / "brand"
SVG = (BRAND / "icon.svg").read_text(encoding="utf-8")
BG = "#0a0f1d"


def shot(html: str, size: tuple[int, int], out: Path, transparent: bool = False) -> Path:
    browser = find_browser()
    if not browser:
        raise SystemExit("Chrome or Edge is needed to render the brand images.")
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(html, encoding="utf-8")
        args = [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--user-data-dir={Path(tmp) / 'profile'}",
            f"--window-size={size[0]},{size[1]}",
            f"--screenshot={out}",
        ]
        if transparent:
            args.append("--default-background-color=00000000")
        subprocess.run([*args, page.as_uri()], check=True, capture_output=True, timeout=60)  # noqa: S603
    return out


def page(body: str, w: int, h: int, bg: str = "transparent") -> str:
    return (
        "<!doctype html><meta charset='utf-8'><style>html,body{margin:0;background:" + bg + "}"
        f"body{{width:{w}px;height:{h}px;overflow:hidden}}"
        ".row{display:flex;align-items:center;height:100%;box-sizing:border-box}.row svg{flex:none}"
        ".name{font:700 1em Cinzel,'Trajan Pro',Georgia,'Times New Roman',serif;letter-spacing:.12em;color:#d9b35b}"
        ".line{font:400 1em 'Segoe UI',system-ui,sans-serif;color:#97a3bc}"
        "</style>" + body
    )


def icon_pngs() -> Image.Image:
    big = BRAND / "icon-1024.tmp.png"
    shot(
        page(SVG.replace('width="512" height="512"', 'width="1024" height="1024"'), 1024, 1024),
        (1024, 1024),
        big,
        transparent=True,
    )
    img = Image.open(big).convert("RGBA").crop((0, 0, 1024, 1024))
    big.unlink()
    # a clean alpha edge for the rounded tile, whatever the browser did with the background
    mask = Image.new("L", (1024, 1024), 0)
    ImageDraw.Draw(mask).rounded_rectangle((16, 16, 1007, 1007), radius=224, fill=255)
    img.putalpha(mask)
    img.save(BRAND / "icon-1024.png", optimize=True)
    for s in (512, 128):
        img.resize((s, s), Image.LANCZOS).save(BRAND / f"icon-{s}.png", optimize=True)
    return img


def main() -> None:
    BRAND.mkdir(parents=True, exist_ok=True)
    img = icon_pngs()
    ico = ROOT / "src" / "openwarframe" / "app" / "static" / "icon.ico"
    img.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    icon_tag = SVG.replace('width="512" height="512"', 'width="{s}" height="{s}"')
    logo = page(
        "<div class='row' style='padding:0 40px;gap:28px;font-size:56px'>"
        + icon_tag.format(s=128)
        + "<div><div class='name'>OPENWARFRAME</div>"
        "<div class='line' style='font-size:24px;margin-top:6px'>See your Warframe account and what to do next</div>"
        "</div></div>",
        1000,
        200,
        bg=BG,
    )
    shot(logo, (1000, 200), BRAND / "logo.png")

    social = page(
        "<div class='row' style='padding:0 90px;gap:56px;font-size:64px'>"
        + icon_tag.format(s=260)
        + "<div><div class='name'>OPENWARFRAME</div>"
        "<div class='line' style='font-size:34px;margin-top:14px'>See your Warframe account<br>and what to do next</div>"
        "<div class='line' style='font-size:24px;margin-top:22px'>Free and open source, for Windows and macOS</div>"
        "</div></div>",
        1280,
        640,
        bg=BG,
    )
    shot(social, (1280, 640), BRAND / "social-preview.png")
    print("wrote", ", ".join(p.name for p in sorted(BRAND.glob("*.png"))), "and", ico.relative_to(ROOT))


if __name__ == "__main__":
    main()
