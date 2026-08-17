"""Vendor-API-compatible driver shims (the *device-ready* code path).

These classes mirror the real Waveshare driver APIs so code written in the
visualizer runs unchanged on a Raspberry Pi:

    from waveshare_epd import epd7in3f
    epd = epd7in3f.EPD(); epd.init()
    epd.display(epd.getbuffer(image)); epd.sleep()

    from lib import LCD_1inch28
    disp = LCD_1inch28.LCD_1inch28(); disp.Init(); disp.ShowImage(image)

    from lib import OLED_1in3
    disp = OLED_1in3.OLED_1in3(); disp.Init(); disp.ShowImage(disp.getbuffer(image))

All SPI/GPIO calls are no-ops. The only methods that do anything are the ones
that receive a framebuffer image — they route it through ``quantize`` (the same
fidelity core the unified ``display.show`` uses) and ``Display._emit`` (the same
preview pipeline), so what you see is byte-identical whether you use the simple
API or the vendor API.

The per-panel bridge modules the runner drops in the sandbox are one-liners:
``EPD = make_epd_class()`` / ``LCD_1inch28 = make_lcd_class()`` etc. Each factory
reads ``WS_SIM_SPEC`` from the environment (same contract as ``display``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PIL import Image

from sim import quantize as _q
from sim.display import Display


def _display_from_env() -> Display:
    spec = json.loads(os.environ["WS_SIM_SPEC"])
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


def _blank_rgb(d: Display) -> Image.Image:
    return Image.new("RGB", (d.width, d.height), (255, 255, 255))


# --- e-Paper: waveshare_epd.<driver>.EPD -----------------------------------

def make_epd_class():
    d = _display_from_env()
    api = d.api or "epaper_mono"

    class EPD:
        # Class/instance geometry, exactly like the vendor driver.
        width = d.height  # vendor convention: width/height are the panel's own
        height = d.width  # short/long — but our Display carries the framebuffer
        # We expose the framebuffer size the way user code expects it:
        WIDTH = d.width
        HEIGHT = d.height

        def __init__(self) -> None:
            self.width = d.width
            self.height = d.height

        # --- lifecycle: all no-ops on the sim ---
        def init(self, *args, **kwargs) -> int:
            return 0

        def init_4Gray(self, *args, **kwargs) -> int:
            return 0

        def reset(self) -> None:
            pass

        def sleep(self) -> None:
            pass

        def Dev_exit(self) -> None:
            pass

        def Clear(self, *args, **kwargs) -> None:
            d._emit(Image.new("RGB", (d.width, d.height), (255, 255, 255)))

        # --- framebuffer: getbuffer is a pass-through; display quantizes ---
        def getbuffer(self, image: Image.Image) -> Image.Image:
            return image

        def getbuffer_4Gray(self, image: Image.Image) -> Image.Image:
            return image

        def display(self, image: Image.Image, *rest) -> None:
            if api == "epaper_redblack" and rest:
                d._emit(_q.redblack_combine(image, rest[0]))
            else:
                d._emit(_q.quantize(image, api, d.mode, d.palette, d._palette_image))

        def display_4Gray(self, image: Image.Image) -> None:
            d._emit(_q.to_gray4(image))

    return EPD


# --- LCD: lib.<driver>.<driver> --------------------------------------------

def make_lcd_class():
    d = _display_from_env()

    class LCD:
        def __init__(self, *args, **kwargs) -> None:
            self.width = d.width
            self.height = d.height

        def Init(self, *args, **kwargs) -> None:
            pass

        def reset(self) -> None:
            pass

        def bl_DutyCycle(self, *args, **kwargs) -> None:
            pass

        def bl_Frequency(self, *args, **kwargs) -> None:
            pass

        def module_exit(self) -> None:
            pass

        def clear(self, *args, **kwargs) -> None:
            d._emit(_q.to_rgb565(_blank_rgb(d)))

        def ShowImage(self, image: Image.Image, *args, **kwargs) -> None:
            d._emit(_q.to_rgb565(image))

    return LCD


# --- OLED: lib.<driver>.<driver> -------------------------------------------

def make_oled_class():
    d = _display_from_env()
    api = d.api or "oled_mono"

    class OLED:
        def __init__(self, *args, **kwargs) -> None:
            self.width = d.width
            self.height = d.height

        def Init(self, *args, **kwargs) -> None:
            pass

        def reset(self) -> None:
            pass

        def clear(self, *args, **kwargs) -> None:
            blank = Image.new("1", (d.width, d.height), 1) if api != "oled_rgb" else _blank_rgb(d)
            d._emit(_q.quantize(blank, api, d.mode, d.palette, d._palette_image))

        def getbuffer(self, image: Image.Image) -> Image.Image:
            return image

        def ShowImage(self, image: Image.Image, *args, **kwargs) -> None:
            d._emit(_q.quantize(image, api, d.mode, d.palette, d._palette_image))

    return OLED
