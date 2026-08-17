"""The ``display`` object user code interacts with.

The backend spawns a subprocess with a display spec injected via env vars
(``WS_SIM_WIDTH``, ``WS_SIM_HEIGHT``, ``WS_SIM_MODE``, ``WS_SIM_PALETTE``,
``WS_SIM_OUT``). User code does::

    from waveshare_sim import display
    from PIL import Image, ImageDraw
    img = Image.new(display.mode, (display.width, display.height), display.bg)
    draw = ImageDraw.Draw(img)
    draw.text((4, 4), "hello", fill=display.fg)
    display.show(img)

On ``show()`` the image is quantized to the display's palette (for e-paper /
OLED) and written to ``WS_SIM_OUT`` as PNG. The backend reads it back and
returns it to the browser.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw

from sim import quantize as _q


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """Linear blend of two RGB colors (t=0 -> a, t=1 -> b)."""
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))  # type: ignore[return-value]


class Display:
    """A simulated Waveshare display.

    Attributes:
        width, height: framebuffer dimensions
        mode: PIL image mode ('1', 'L', 'RGB', 'P')
        palette: list of hex colors, or None for full-color RGB
        shape: 'rect' (default) or 'round' — round masks the framebuffer to the
            inscribed circle so pixels in the corners render as background,
            matching the circular glass of displays like the GC9A01.
        fg, bg: convenience colors matching ``mode``
    """

    def __init__(
        self,
        width: int,
        height: int,
        mode: str,
        palette: Sequence[str] | None,
        out_path: Path,
        shape: str = "rect",
        family: str = "lcd",
        char_grid: Sequence[int] | None = None,
        api: str | None = None,
    ) -> None:
        self.width = width
        self.height = height
        self.mode = mode
        self.palette = list(palette) if palette else None
        self.shape = shape if shape in ("rect", "round") else "rect"
        self.family = family
        # Authoritative fidelity selector (e.g. 'epaper_4gray', 'lcd_rgb565').
        # None -> fall back to mode-based quantization (import stub).
        self.api = api
        # For character LCDs (HD44780/LCD1602): [columns, rows] of text cells.
        self.char_grid: tuple[int, int] | None = (
            (int(char_grid[0]), int(char_grid[1])) if char_grid else None
        )
        self._out_path = Path(out_path)
        self._palette_image: Image.Image | None = None
        self._glyph_cache: dict[str, list[list[int]]] = {}

        if mode == "1":
            self.bg = 255  # white
            self.fg = 0    # black
        elif mode == "L":
            self.bg = 255
            self.fg = 0
        elif mode == "RGB" and family == "char":
            # Classic blue-backlight character LCD: white dots on deep blue.
            self.bg = (18, 42, 196)
            self.fg = (236, 245, 255)
        elif mode == "RGB":
            self.bg = (0, 0, 0)
            self.fg = (255, 255, 255)
        elif mode == "P":
            self.bg = 0  # first palette entry
            self.fg = 1  # second palette entry
            self._palette_image = self._build_palette_image()
        else:
            raise ValueError(f"Unsupported display mode: {mode!r}")

    def _build_palette_image(self) -> Image.Image:
        assert self.palette
        pal_img = Image.new("P", (1, 1))
        flat: list[int] = []
        for hex_color in self.palette:
            flat.extend(_hex_to_rgb(hex_color))
        # PIL palette must be 256 entries * 3 channels.
        flat.extend([0, 0, 0] * (256 - len(self.palette)))
        pal_img.putpalette(flat)
        return pal_img

    def blank(self) -> Image.Image:
        """Return a fresh image sized/moded to this display."""
        return Image.new(self.mode, (self.width, self.height), self.bg)

    # --- Character-LCD (HD44780 / LCD1602) helpers -------------------------

    def _glyph_5x7(self, ch: str) -> list[list[int]]:
        """A 5-wide x 7-tall on/off dot pattern for one character.

        Real HD44780 controllers store a 5x7 (in a 5x8 cell) bitmap font. We
        derive an equivalent pattern from the monospace system font so any
        printable character renders, then cache it.
        """
        if ch in self._glyph_cache:
            return self._glyph_cache[ch]
        # HD44780 codes 0xFF (and the block char 0x2588) render as a solid cell.
        if ch in ("\xff", "█"):
            solid = [[1] * 5 for _ in range(7)]
            self._glyph_cache[ch] = solid
            return solid
        from PIL import ImageFont

        try:
            font = ImageFont.truetype("DejaVuSansMono.ttf", 11)
        except OSError:
            font = ImageFont.load_default()
        probe = Image.new("L", (16, 16), 0)
        ImageDraw.Draw(probe).text((0, 0), ch, fill=255, font=font)
        bbox = probe.getbbox()
        if not bbox:  # space / non-printing
            pattern = [[0] * 5 for _ in range(7)]
        else:
            glyph = probe.crop(bbox).resize((5, 7), Image.BILINEAR)
            px = glyph.load()
            pattern = [[1 if px[x, y] > 90 else 0 for x in range(5)] for y in range(7)]
        self._glyph_cache[ch] = pattern
        return pattern

    def text_lines(
        self,
        lines: Sequence[str],
        *,
        show: bool = True,
    ) -> Image.Image:
        """Render text the way an HD44780 character LCD (LCD1602) would.

        ``lines`` is one string per row (extra rows/characters past the panel's
        ``char_grid`` are clipped, matching the real controller). Each character
        is drawn as a 5x7 dot matrix on the blue backlight. Returns the image;
        with ``show=True`` (default) it is also pushed to the framebuffer.
        """
        cols, rows = self.char_grid or (16, 2)
        img = Image.new("RGB", (self.width, self.height), self.bg)
        draw = ImageDraw.Draw(img)

        # Lay out a dot grid that fills the panel: 5 dots per char + 1-dot gap,
        # 7 dots per row + 1-dot gap, with a small margin all round.
        dot_cols = cols * 6 - 1          # 5 + 1 gap per char, minus trailing gap
        dot_rows = rows * 8 - 1          # 7 + 1 gap per row, minus trailing gap
        margin = 0.06
        avail_w = self.width * (1 - 2 * margin)
        avail_h = self.height * (1 - 2 * margin)
        dot = max(1.0, min(avail_w / dot_cols, avail_h / dot_rows))
        grid_w = dot * dot_cols
        grid_h = dot * dot_rows
        ox = (self.width - grid_w) / 2
        oy = (self.height - grid_h) / 2
        pad = dot * 0.12  # tiny gap between dots so the matrix reads as dots
        off = _mix(self.bg, self.fg, 0.10)  # faint unlit dot, like real glass

        for r in range(rows):
            line = lines[r] if r < len(lines) else ""
            for c in range(cols):
                ch = line[c] if c < len(line) else " "
                pattern = self._glyph_5x7(ch)
                cx0 = ox + c * 6 * dot
                cy0 = oy + r * 8 * dot
                for dy in range(7):
                    for dx in range(5):
                        x0 = cx0 + dx * dot
                        y0 = cy0 + dy * dot
                        color = self.fg if pattern[dy][dx] else off
                        draw.rectangle(
                            (x0 + pad, y0 + pad, x0 + dot - pad, y0 + dot - pad),
                            fill=color,
                        )
        if show:
            self.show(img)
        return img

    def clear(self) -> None:
        """Show a blank framebuffer (equivalent to ``epd.Clear()``)."""
        self.show(self.blank())

    def show(self, image: Image.Image) -> None:
        """Composite the given image as the current framebuffer.

        The image is converted to the display's mode/palette so what you see
        in the browser matches what a real device would render.
        """
        self._warn_if_incompatible(image)
        out = _q.quantize(image, self.api, self.mode, self.palette, self._palette_image)
        self._emit(out)

    def _emit(self, out: Image.Image) -> None:
        """Composite an already-quantized, storage-mode image to the preview PNG.

        Shared by ``show`` (unified API) and the vendor-driver shims so both
        paths produce byte-identical previews. Handles framebuffer fit, the
        round-glass mask, and PNG encoding.
        """
        out = self._fit_framebuffer(out)
        if self.shape == "round":
            out = self._apply_round_mask(out)
        # Always emit as PNG in RGB(A) for the browser regardless of mode.
        preview = out.convert("RGB") if out.mode != "RGB" else out
        preview.save(self._out_path, format="PNG")

    def _warn_if_incompatible(self, image: Image.Image) -> None:
        """Warn on stderr when the source image mode wouldn't fit the real driver.

        Waveshare mono drivers call ``epd.getbuffer(image)`` which expects a
        1-bit image; passing RGB on a real HAT either raises or garbles.
        Palette displays (colour e-paper) accept RGB but only render colours
        near the palette. We don't raise here — we still quantize — but the
        warning tells the user their code wouldn't behave the same on device.
        """
        if self.mode == "1" and image.mode not in ("1", "L"):
            sys.stderr.write(
                f"warning: this display is 1-bit (black/white). Your image is "
                f"mode {image.mode!r}; a real driver would refuse it. "
                f"Auto-converting via luminance — expect dithering, not colour.\n"
            )
        elif self.mode == "P" and image.mode not in ("P", "RGB"):
            sys.stderr.write(
                f"warning: this display uses a {len(self.palette or [])}-colour palette. "
                f"Image mode {image.mode!r} will be converted to RGB first.\n"
            )

    def _apply_round_mask(self, out: Image.Image) -> Image.Image:
        """Blank out pixels outside the inscribed circle, matching round glass."""
        w, h = out.size
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, w - 1, h - 1), fill=255)
        background = Image.new(out.mode, (w, h), self.bg)
        background.paste(out, (0, 0), mask)
        return background

    def _fit_framebuffer(self, out: Image.Image) -> Image.Image:
        """Force ``out`` to the panel's exact framebuffer size without scaling.

        Waveshare's ``epd.getbuffer()`` accepts only an image matching the panel:
        it rotates one that is exactly transposed and refuses anything else.
        Scaling a mismatched image would let user code draw on a canvas the
        hardware doesn't have — the panel is the size it is — so we crop/pad to
        the framebuffer instead and say so on stderr.
        """
        if out.size == (self.width, self.height):
            return out

        if out.size == (self.height, self.width):
            sys.stderr.write(
                f"note: image is {out.width}x{out.height} and this panel is "
                f"{self.width}x{self.height}; rotating 90 degrees as epd.getbuffer() does.\n"
            )
            return out.rotate(90, expand=True)

        sys.stderr.write(
            f"warning: image is {out.width}x{out.height} but this panel's framebuffer "
            f"is {self.width}x{self.height}. A real driver would log 'Wrong image "
            f"dimensions' and push a blank frame; cropping to the panel so you can "
            f"see the part that fits. Size your image to "
            f"(display.width, display.height).\n"
        )
        canvas = Image.new(out.mode, (self.width, self.height), self.bg)
        if out.mode == "P":
            canvas.putpalette(out.getpalette() or [])
        canvas.paste(out.crop((0, 0, min(out.width, self.width), min(out.height, self.height))), (0, 0))
        return canvas

    def __repr__(self) -> str:
        return f"Display({self.width}x{self.height} mode={self.mode})"


def _load_from_env() -> Display:
    spec_json = os.environ.get("WS_SIM_SPEC")
    if not spec_json:
        # Not running under the sandbox — provide a friendly stub so users can
        # `import` without immediately erroring in a REPL.
        return Display(width=250, height=122, mode="1", palette=["#ffffff", "#000000"], out_path=Path("/tmp/ws_sim.png"))
    spec = json.loads(spec_json)
    return Display(
        width=int(spec["width"]),
        height=int(spec["height"]),
        mode=str(spec["mode"]),
        palette=spec.get("palette"),
        out_path=Path(spec["out_path"]),
        shape=str(spec.get("shape", "rect")),
        family=str(spec.get("family", "lcd")),
        char_grid=spec.get("char_grid"),
        api=spec.get("api"),
    )


# Module-level singleton — this is what user code imports.
display: Display = _load_from_env()
