"""Screenshot the Warframe window and read the relic reward names with Windows' own OCR.

Only the screen is read: we find the game window, copy its pixels, crop the band where
the reward names are printed and hand each name box to ``Windows.Media.Ocr`` (built into
Windows 10/11, no Tesseract). Nothing touches the game process.

Crop geometry is ported from WFInfo (https://github.com/WFCD/WFinfo, MIT),
``WFInfo/Ocr.cs`` on master, read 2026-11-24 (blob ``14001e5a``). Its constants are
measured on a 1920x1080 screen at 100 % UI scale::

    pixleRewardWidth = 968        // all four reward columns together
    pixleRewardHeight = 235
    pixleRewardYDisplay = 316
    pixelRewardLineHeight = 48    // 58 for CJK languages

``ExtractPartBoxAutomatically`` puts the name band at::

    mostLeft = width/2 - mostWidth/2                 mostWidth = 968 * scaling
    mostTop  = height/2 - (316 - 235 + 48) * scaling
    mostBot  = height/2 - (316 - 235) * scaling * 0.5

and ``ScreenScaling`` is height/1080 on screens wider than 16:9, otherwise width/1920.
The band is always four columns wide; with fewer rewards the names are centred, so
``ProcessRewardScreen`` shifts the first column right by ``width/8`` per missing reward.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import os
import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

REF_W, REF_H = 1920, 1080
REWARD_WIDTH = 968
REWARD_HEIGHT = 235
REWARD_Y_DISPLAY = 316
LINE_HEIGHT = 48
CJK_LINE_HEIGHT = 58


@dataclass(frozen=True)
class Box:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)


def screen_scaling(width: int, height: int) -> float:
    """WFInfo's ScreenScaling: fit a 1920x1080 layout into the window."""
    if width * 9 > height * 16:  # wider than 16:9: height decides
        return height / REF_H
    return width / REF_W


def name_band(width: int, height: int, ui_scale: float = 1.0, *, cjk: bool = False, pad: float = 0.25) -> Box:
    """The strip that holds all reward names (up to two text lines each).

    ``pad`` widens the band up and down by that fraction of a text line, which covers
    small differences between WFInfo's measurements and what the game draws.
    """
    s = screen_scaling(width, height) * ui_scale
    line = (CJK_LINE_HEIGHT if cjk else LINE_HEIGHT) * s
    band_w = REWARD_WIDTH * s
    left = width / 2 - band_w / 2
    top = height / 2 - (REWARD_Y_DISPLAY - REWARD_HEIGHT) * s - line
    bottom = height / 2 - (REWARD_Y_DISPLAY - REWARD_HEIGHT) * s * 0.5
    top -= line * pad
    bottom += line * pad
    return Box(
        max(0, round(left)),
        max(0, round(top)),
        min(width, round(left + band_w)),
        min(height, round(bottom)),
    )


def slot_boxes(
    width: int, height: int, players: int, ui_scale: float = 1.0, *, cjk: bool = False
) -> list[Box]:
    """One box per reward for a squad of ``players`` (1 to 4)."""
    if not 1 <= players <= 4:
        raise ValueError("players must be 1 to 4")
    band = name_band(width, height, ui_scale, cjk=cjk)
    col = band.width / 4
    start = band.left + (4 - players) * col / 2
    return [
        Box(round(start + i * col), band.top, round(start + (i + 1) * col), band.bottom)
        for i in range(players)
    ]


def read_ui_scale(cfg: Path | None = None) -> float:
    """Best-effort UI scale from EE.cfg; 1.0 when the file or key is missing.

    WFInfo reads ``Flash.FlashDrawScale`` (Ocr.cs ``ReadUiScaleFromConfig``).
    """
    if cfg is None:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        cfg = Path(base) / "Warframe" / "EE.cfg"
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 1.0
    m = re.search(r"Flash\.FlashDrawScale\s*=\s*([0-9.]+)", text) or re.search(
        r"FlashDrawScale\s*=\s*([0-9.]+)", text
    )
    try:
        v = float(m.group(1)) if m else 1.0
    except ValueError:
        return 1.0
    return v if 0.3 <= v <= 2.0 else 1.0


def prepare(crop: Image.Image) -> Image.Image:
    """Grey, high-contrast, dark text on light, at least ~40 px per text line."""
    g = ImageOps.grayscale(crop)
    g = ImageOps.autocontrast(g, cutoff=1)
    g = ImageOps.invert(g)
    if g.height < 120:
        f = 120 / max(1, g.height)
        g = g.resize((round(g.width * f), round(g.height * f)), Image.Resampling.LANCZOS)
    return g


# -- Windows OCR --------------------------------------------------------------------------


def ocr_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        from winrt.windows.media.ocr import OcrEngine  # noqa: F401
    except Exception:
        return False
    return True


async def _recognize(img: Image.Image, language: str | None) -> list[str]:
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter

    rgba = img.convert("RGBA")
    w = DataWriter()
    w.write_bytes(rgba.tobytes("raw", "BGRA"))
    bmp = SoftwareBitmap.create_copy_from_buffer(
        w.detach_buffer(), BitmapPixelFormat.BGRA8, rgba.width, rgba.height, BitmapAlphaMode.PREMULTIPLIED
    )
    if language:
        from winrt.windows.globalization import Language

        engine = OcrEngine.try_create_from_language(Language(language))
    else:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError("Windows OCR has no engine for this language; add an OCR language pack.")
    result = await engine.recognize_async(bmp)
    return [ln.text for ln in result.lines]


def _run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    out: dict = {}

    def target():
        try:
            out["v"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - re-raised below
            out["e"] = exc

    t = threading.Thread(target=target)
    t.start()
    t.join()
    if "e" in out:
        raise out["e"]
    return out["v"]


def ocr_lines(img: Image.Image, language: str | None = None) -> list[str]:
    """Text lines Windows OCR finds in an image."""
    return _run(_recognize(img, language))


def read_slots(
    image: Image.Image, players: int, ui_scale: float = 1.0, *, language: str | None = None
) -> list[str]:
    """Raw OCR text for each reward box (lines joined with a space)."""
    out = []
    for box in slot_boxes(image.width, image.height, players, ui_scale):
        lines = ocr_lines(prepare(image.crop(box.as_tuple())), language)
        out.append(" ".join(s.strip() for s in lines if s.strip()))
    return out


def read_all_layouts(
    image: Image.Image, ui_scale: float = 1.0, *, language: str | None = None
) -> dict[int, list[str]]:
    """OCR for every squad size; the matcher picks the layout that reads best."""
    return {n: read_slots(image, n, ui_scale, language=language) for n in (4, 3, 2, 1)}


# -- finding and capturing the game window ------------------------------------------------

GAME_EXES = ("warframe.x64.exe", "warframe.exe")


@dataclass
class GameWindow:
    hwnd: int
    title: str
    exe: str
    box: Box  # client area in screen pixels


def _user32():
    return ctypes.WinDLL("user32", use_last_error=True)


def _dpi_aware() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor: real pixels
    except Exception:
        with contextlib.suppress(Exception):
            ctypes.windll.user32.SetProcessDPIAware()


def _exe_of(hwnd: int) -> str:
    from ctypes import wintypes

    user32 = _user32()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name
        return ""
    finally:
        kernel32.CloseHandle(h)


def find_game_window() -> GameWindow | None:
    """The visible top-level window owned by Warframe.x64.exe, or None."""
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    _dpi_aware()
    user32 = _user32()
    found: list[GameWindow] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        exe = _exe_of(hwnd)
        if exe.lower() in GAME_EXES or (not exe and buf.value == "Warframe"):
            rect = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rect))
            pt = wintypes.POINT(0, 0)
            user32.ClientToScreen(hwnd, ctypes.byref(pt))
            if rect.right > 0 and rect.bottom > 0:
                box = Box(pt.x, pt.y, pt.x + rect.right, pt.y + rect.bottom)
                found.append(GameWindow(int(hwnd), buf.value, exe, box))
        return True

    user32.EnumWindows(cb, 0)
    if not found:
        return None
    return max(found, key=lambda w: w.box.width * w.box.height)


def capture(win: GameWindow) -> Image.Image:
    """Copy the game window's client area from the screen (borderless or windowed mode).

    Exclusive fullscreen can come back black; the game's own borderless mode works.
    """
    import mss

    b = win.box
    with mss.mss() as sct:
        shot = sct.grab({"left": b.left, "top": b.top, "width": b.width, "height": b.height})
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
