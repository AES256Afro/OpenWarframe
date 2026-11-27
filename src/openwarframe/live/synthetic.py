"""Draw a fake reward screen: names placed where ``ocr.slot_boxes`` expects them.

Used by tests and ``openwarframe live sample-image`` to check the crop + OCR + match chain
without the game. It is not a picture of the real screen, only of the text layout.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from .ocr import screen_scaling, slot_boxes

# system fonts that cover each script (Windows names first, then macOS); Arial covers Latin and Cyrillic
SCRIPT_FONTS = {
    "ja": (
        "meiryo.ttc",
        "YuGothM.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    ),
    "ko": ("malgun.ttf", "/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    "zh": (
        "msyh.ttc",
        "simsun.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
    ),
    "tc": (
        "msjh.ttc",
        "mingliu.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
    ),
    "th": (
        "tahoma.ttf",
        "leelawad.ttf",
        "/System/Library/Fonts/Supplemental/Tahoma.ttf",
        "/System/Library/Fonts/Thonburi.ttc",
    ),
}


def _font(px: int, lang: str = "en") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in (
        *SCRIPT_FONTS.get(lang, ()),
        "arial.ttf",
        "segoeui.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default(size=px)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines[:2]


def reward_screen(
    names: list[str], size: tuple[int, int] = (1920, 1080), ui_scale: float = 1.0, lang: str = "en"
) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, (14, 16, 24))
    draw = ImageDraw.Draw(img)
    s = screen_scaling(w, h) * ui_scale
    font = _font(max(8, round(19 * s)), lang)
    line_h = round(24 * s)
    for box, name in zip(slot_boxes(w, h, len(names), ui_scale), names, strict=True):
        # a dim card behind each reward, like the game's reward tiles
        draw.rectangle((box.left + 6, box.top - round(150 * s), box.right - 6, box.bottom), fill=(30, 34, 46))
        lines = _wrap(draw, name, font, box.width - round(16 * s))
        y0 = box.top + (box.height - line_h * len(lines)) // 2
        for i, ln in enumerate(lines):
            tw = draw.textlength(ln, font=font)
            draw.text((box.left + (box.width - tw) / 2, y0 + i * line_h), ln, fill=(232, 232, 220), font=font)
    return img
