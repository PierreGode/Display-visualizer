"""Hardware-accurate quantization — the single source of truth for fidelity.

Every function here reproduces the *exact* PIL step the real Waveshare driver
performs inside ``getbuffer`` / ``getbuffer_4Gray`` / ``ShowImage`` (all of
which are pure image math — no hardware). Both the unified ``display.show``
path and the vendor-API driver shims route through this module, so the browser
preview shows precisely what the panel's controller would receive.

Ground truth (from waveshareteam/e-Paper):
  * mono   getbuffer      -> image.convert("1")            (Floyd-Steinberg)
  * 4-gray getbuffer_4Gray-> image.convert("L"), top 2 bits -> 4 hard levels
  * 7col F getbuffer      -> RGB.quantize(palette=PAL)      (dithered)
  * 6col E / 4col G       -> same, panel-specific palette
  * B/bc                  -> two 1-bit planes (black, red) -> white/black/red
LCD (ST7789/GC9A01/ILI9341/ILI9486) and RGB OLED (SSD1351) push RGB565, so we
drop each channel to 5/6/5 bits to reproduce the visible banding.
"""

from __future__ import annotations

from typing import Sequence

from PIL import Image

# --- Exact vendor colour tables (RGB triples) ------------------------------
# Order matters: it is the panel's own palette index order.
PAL_7COLOR = [  # epd7in3f / epd5in65f / epd4in01f
    (0, 0, 0), (255, 255, 255), (0, 255, 0), (0, 0, 255),
    (255, 0, 0), (255, 255, 0), (255, 128, 0),
]
PAL_6COLOR = [  # epd7in3e (Spectra 6)
    (0, 0, 0), (255, 255, 255), (255, 255, 0), (255, 0, 0),
    (0, 0, 255), (0, 255, 0),
]
PAL_4COLOR = [  # epd*g  (black / white / yellow / red)
    (0, 0, 0), (255, 255, 255), (255, 255, 0), (255, 0, 0),
]
PAL_REDBLACK = [  # epd*b / *bc  (white / black / red)
    (255, 255, 255), (0, 0, 0), (255, 0, 0),
]

_NAMED = {
    "epaper_7color": PAL_7COLOR,
    "epaper_6color": PAL_6COLOR,
    "epaper_4color": PAL_4COLOR,
    "epaper_redblack": PAL_REDBLACK,
}


def _palette_image(colors: Sequence[tuple[int, int, int]]) -> Image.Image:
    pal = Image.new("P", (1, 1))
    flat: list[int] = []
    for c in colors:
        flat.extend(c)
    flat.extend([0, 0, 0] * (256 - len(colors)))
    pal.putpalette(flat)
    return pal


def to_palette(image: Image.Image, colors: Sequence[tuple[int, int, int]]) -> Image.Image:
    """Vendor colour-eink path: RGB -> nearest palette colour, dithered.

    Mirrors ``image.convert("RGB").quantize(palette=pal_image)`` in the drivers.
    """
    return image.convert("RGB").quantize(palette=_palette_image(colors), dither=Image.Dither.FLOYDSTEINBERG)


def to_mono(image: Image.Image) -> Image.Image:
    """1-bit black/white, dithered — matches getbuffer's image.convert('1')."""
    return image.convert("1")


def to_gray4(image: Image.Image) -> Image.Image:
    """4-level grayscale via the top 2 bits, matching getbuffer_4Gray.

    The vendor keeps only bits 7-6 of each luminance value, giving 4 hard
    levels (no dithering). We spread them evenly so the preview reads as the
    panel's four distinct e-ink greys.
    """
    lum = image.convert("L")
    lut = [(i >> 6) * 85 for i in range(256)]  # 0,85,170,255
    return lum.point(lut)


def to_gray16(image: Image.Image) -> Image.Image:
    """16-level grayscale (SSD1327 OLED, IT8951 9.7\"/10.3\" e-paper)."""
    lum = image.convert("L")
    lut = [(i >> 4) * 17 for i in range(256)]  # 0,17,...,255
    return lum.point(lut)


def to_rgb565(image: Image.Image) -> Image.Image:
    """Reduce to RGB565 (65K colours) as ST7789/ILI9341/GC9A01/SSD1351 do."""
    rgb = image.convert("RGB")
    # Mask to 5/6/5 significant bits, then replicate high bits into the low
    # ones (what the panel effectively displays) so greys stay neutral.
    lut_5 = bytes(((i & 0xF8) | (i >> 5)) for i in range(256))
    lut_6 = bytes(((i & 0xFC) | (i >> 6)) for i in range(256))
    r, g, b = rgb.split()
    r = r.point(lut_5); g = g.point(lut_6); b = b.point(lut_5)
    return Image.merge("RGB", (r, g, b))


def redblack_combine(black: Image.Image, red: Image.Image) -> Image.Image:
    """Two-plane B/bc panels: black plane + red plane -> white/black/red image.

    Real driver: ``display(getbuffer(black_img), getbuffer(red_img))``. Each
    plane is a 1-bit image where 0 = ink. Red wins where both are inked, as on
    the panel.
    """
    kb = black.convert("1")
    rb = red.convert("1")
    out = Image.new("RGB", kb.size, (255, 255, 255))
    px, kpx, rpx = out.load(), kb.load(), rb.load()
    w, h = out.size
    for y in range(h):
        for x in range(w):
            if rpx[x, y] == 0:
                px[x, y] = (255, 0, 0)
            elif kpx[x, y] == 0:
                px[x, y] = (0, 0, 0)
    return out


# --- Dispatcher used by the unified display.show path ----------------------

def quantize(
    image: Image.Image,
    api: str | None,
    mode: str,
    palette: Sequence[str] | None,
    palette_image: Image.Image | None,
) -> Image.Image:
    """Return the exact image the panel would render, in its storage mode.

    ``api`` is the authoritative fidelity selector; when it is ``None`` (e.g.
    the import-stub outside the sandbox) we fall back to the PIL ``mode``.
    """
    if api in _NAMED:
        return to_palette(image, _NAMED[api])
    if api == "epaper_4gray":
        return to_gray4(image)
    if api == "epaper_gray16" or api == "oled_gray16":
        return to_gray16(image)
    if api in ("lcd_rgb565", "oled_rgb"):
        return to_rgb565(image)
    if api in ("epaper_mono", "oled_mono"):
        return to_mono(image)

    # Fall back to mode-based conversion (unified stub / char panels).
    if mode == "1":
        return image.convert("1")
    if mode == "L":
        return image.convert("L")
    if mode == "RGB":
        return image.convert("RGB")
    if mode == "P" and palette_image is not None:
        return image.convert("RGB").quantize(palette=palette_image, dither=Image.Dither.FLOYDSTEINBERG)
    return image.convert("RGB")
