"""Starter code snippets that appear in the frontend's example picker.

Each snippet is a full, runnable program. Every example uses ``display.mode``,
``display.bg`` and ``display.fg`` so the drawing matches whatever the real
Waveshare driver would render — no hardcoded RGB on a 1-bit e-paper.

The ``min_colors`` and ``shape`` fields let the frontend hide examples that
don't make sense for the selected display (e.g. hide colour examples on
black/white displays, hide the round gauge on rectangular ones).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Example:
    id: str
    name: str
    family: str          # 'any' | 'epaper' | 'lcd' | 'oled' — for grouping only
    code: str
    min_colors: int = 2  # minimum palette size the display must support
    shape: str = "any"   # 'any' | 'rect' | 'round'


EXAMPLES: list[Example] = [
    Example(
        id="hello",
        name="Hello, display",
        family="any",
        code='''\
from waveshare_sim import display
from PIL import Image, ImageDraw, ImageFont

img = Image.new(display.mode, (display.width, display.height), display.bg)
draw = ImageDraw.Draw(img)

# Pick a font size that scales with the display
size = max(12, min(display.width, display.height) // 6)
try:
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", size)
except OSError:
    font = ImageFont.load_default()

text = "Hello!"
bbox = draw.textbbox((0, 0), text, font=font)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
draw.text(
    ((display.width - tw) / 2, (display.height - th) / 2 - bbox[1]),
    text,
    font=font,
    fill=display.fg,
)

display.show(img)
''',
    ),
    Example(
        id="clock",
        name="Digital clock",
        family="any",
        code='''\
import datetime
from waveshare_sim import display
from PIL import Image, ImageDraw, ImageFont

img = Image.new(display.mode, (display.width, display.height), display.bg)
draw = ImageDraw.Draw(img)

size = max(16, min(display.width, display.height) // 3)
try:
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", size)
except OSError:
    font = ImageFont.load_default()

now = datetime.datetime.now().strftime("%H:%M")
bbox = draw.textbbox((0, 0), now, font=font)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
draw.text(
    ((display.width - tw) / 2, (display.height - th) / 2 - bbox[1]),
    now,
    font=font,
    fill=display.fg,
)

display.show(img)
''',
    ),
    Example(
        id="shapes",
        name="Shapes & lines",
        family="any",
        code='''\
from waveshare_sim import display
from PIL import Image, ImageDraw

img = Image.new(display.mode, (display.width, display.height), display.bg)
draw = ImageDraw.Draw(img)

w, h = display.width, display.height
draw.rectangle([2, 2, w - 3, h - 3], outline=display.fg, width=2)
draw.line([(0, 0), (w, h)], fill=display.fg, width=1)
draw.line([(w, 0), (0, h)], fill=display.fg, width=1)
draw.ellipse([w // 4, h // 4, 3 * w // 4, 3 * h // 4], outline=display.fg, width=2)

display.show(img)
''',
    ),
    Example(
        id="sine",
        name="Sine wave plot",
        family="any",
        code='''\
import math
from waveshare_sim import display
from PIL import Image, ImageDraw

img = Image.new(display.mode, (display.width, display.height), display.bg)
draw = ImageDraw.Draw(img)

w, h = display.width, display.height
mid = h / 2
points = []
for x in range(w):
    y = mid + math.sin(x * 0.15) * (h * 0.35)
    points.append((x, y))

draw.line([(0, mid), (w, mid)], fill=display.fg)
draw.line(points, fill=display.fg, width=2)

display.show(img)
''',
    ),
    Example(
        # Adaptive: uses display.palette when the panel has one (colour e-paper),
        # a curated RGB set on full-colour LCDs, and refuses to show up in the
        # picker for mono displays.
        id="color_stripes",
        name="Colour stripes",
        family="any",
        min_colors=3,
        code='''\
from waveshare_sim import display
from PIL import Image, ImageDraw

# Pick colours the driver actually supports.
if display.palette:
    # Colour e-paper: use every palette entry except the background so each
    # stripe is a real device colour, not a nearest-match approximation.
    colours = [c for c in display.palette if c.lower() != "#ffffff"] or list(display.palette)
else:
    # Full-colour RGB LCD.
    colours = ["#ff3b30", "#ff9500", "#ffcc00", "#34c759", "#5ac8fa", "#007aff", "#af52de"]

img = Image.new("RGB", (display.width, display.height), "#ffffff")
draw = ImageDraw.Draw(img)

band = display.height / len(colours)
for i, c in enumerate(colours):
    draw.rectangle([0, int(i * band), display.width, int((i + 1) * band)], fill=c)

display.show(img)
''',
    ),
    Example(
        id="round_gauge",
        name="Round gauge",
        family="lcd",
        min_colors=256,  # RGB LCD only
        shape="round",
        code='''\
import math
from waveshare_sim import display
from PIL import Image, ImageDraw, ImageFont

w, h = display.width, display.height
cx, cy = w / 2, h / 2
r = min(w, h) / 2 - 4

img = Image.new("RGB", (w, h), "black")
draw = ImageDraw.Draw(img)

# Tick marks around the dial
for deg in range(0, 360, 15):
    a = math.radians(deg)
    long = deg % 45 == 0
    r0 = r - (14 if long else 8)
    draw.line(
        [(cx + r0 * math.cos(a), cy + r0 * math.sin(a)),
         (cx + r * math.cos(a), cy + r * math.sin(a))],
        fill="#3a3a3a" if not long else "#6a6a6a",
        width=2,
    )

# Value arc (0..270 degrees), starting from the bottom-left
value = 0.68
start, sweep = 135, 270
draw.arc(
    [cx - r + 18, cy - r + 18, cx + r - 18, cy + r - 18],
    start, start + sweep * value,
    fill="#34c759", width=8,
)

# Needle
a = math.radians(start + sweep * value)
draw.line([(cx, cy), (cx + (r - 30) * math.cos(a), cy + (r - 30) * math.sin(a))],
          fill="#ff3b30", width=3)
draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill="#ffffff")

# Centered readout
size = max(16, int(r / 2.2))
try:
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", size)
except OSError:
    font = ImageFont.load_default()
label = f"{int(value * 100)}%"
bbox = draw.textbbox((0, 0), label, font=font)
tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
draw.text((cx - tw / 2, cy + r * 0.28 - bbox[1]), label, font=font, fill="#ffffff")

display.show(img)
''',
    ),
    Example(
        id="analog_clock",
        name="Analog clock",
        family="lcd",
        min_colors=256,
        shape="round",
        code='''\
import datetime, math
from waveshare_sim import display
from PIL import Image, ImageDraw

w, h = display.width, display.height
cx, cy = w / 2, h / 2
r = min(w, h) / 2 - 4

img = Image.new("RGB", (w, h), "#0b1020")
draw = ImageDraw.Draw(img)
draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline="#2a3550", width=3)

# Hour ticks
for i in range(12):
    a = math.radians(i * 30 - 90)
    r0 = r - (16 if i % 3 == 0 else 10)
    draw.line([(cx + r0 * math.cos(a), cy + r0 * math.sin(a)),
               (cx + r * math.cos(a), cy + r * math.sin(a))],
              fill="#8fadff", width=3 if i % 3 == 0 else 1)

now = datetime.datetime.now()
hands = [
    ((now.hour % 12 + now.minute / 60) / 12, r * 0.50, "#ffffff", 6),
    ((now.minute + now.second / 60) / 60, r * 0.72, "#ffffff", 4),
    (now.second / 60, r * 0.80, "#ff3b30", 2),
]
for frac, length, color, wdt in hands:
    a = math.radians(frac * 360 - 90)
    draw.line([(cx, cy), (cx + length * math.cos(a), cy + length * math.sin(a))],
              fill=color, width=wdt)
draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill="#ff3b30")

display.show(img)
''',
    ),
    Example(
        id="radar",
        name="Radar sweep",
        family="lcd",
        min_colors=256,
        shape="round",
        code='''\
import math, random
from waveshare_sim import display
from PIL import Image, ImageDraw

w, h = display.width, display.height
cx, cy = w / 2, h / 2
r = min(w, h) / 2 - 4

img = Image.new("RGB", (w, h), "#001b0e")
draw = ImageDraw.Draw(img)

# Range rings + crosshair
step = max(1, int(r / 4))
for rr in range(step, int(r) + 1, step):
    draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline="#0f7a3f", width=1)
draw.line([(cx - r, cy), (cx + r, cy)], fill="#0f7a3f")
draw.line([(cx, cy - r), (cx, cy + r)], fill="#0f7a3f")

# Fading sweep trailing the leading edge
heading = 45
for k in range(40):
    a = math.radians(heading - k * 1.5)
    shade = int(150 * (1 - k / 40))
    draw.line([(cx, cy), (cx + r * math.cos(a), cy + r * math.sin(a))],
              fill=(0, shade, int(shade * 0.4)))
a = math.radians(heading)
draw.line([(cx, cy), (cx + r * math.cos(a), cy + r * math.sin(a))], fill="#4dff9e", width=2)

# Contacts
random.seed(7)
for _ in range(5):
    ba = random.uniform(0, 2 * math.pi)
    br = random.uniform(r * 0.2, r * 0.9)
    bx, by = cx + br * math.cos(ba), cy + br * math.sin(ba)
    draw.ellipse([bx - 3, by - 3, bx + 3, by + 3], fill="#7bffbd")

display.show(img)
''',
    ),
    Example(
        id="compass",
        name="Compass",
        family="lcd",
        min_colors=256,
        shape="round",
        code='''\
import math
from waveshare_sim import display
from PIL import Image, ImageDraw, ImageFont

w, h = display.width, display.height
cx, cy = w / 2, h / 2
r = min(w, h) / 2 - 4

img = Image.new("RGB", (w, h), "#12151c")
draw = ImageDraw.Draw(img)
draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline="#39415a", width=3)

size = max(12, int(r / 3.5))
try:
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", size)
except OSError:
    font = ImageFont.load_default()

for label, ang in [("N", -90), ("E", 0), ("S", 90), ("W", 180)]:
    a = math.radians(ang)
    lx, ly = cx + (r - size) * math.cos(a), cy + (r - size) * math.sin(a)
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((lx - tw / 2, ly - th / 2 - bbox[1]), label, font=font,
              fill="#ff3b30" if label == "N" else "#c8d2ea")

heading = 30  # degrees clockwise from north
a = math.radians(heading - 90)
draw.line([(cx, cy), (cx + r * 0.7 * math.cos(a), cy + r * 0.7 * math.sin(a))],
          fill="#ff3b30", width=5)
draw.line([(cx, cy), (cx - r * 0.7 * math.cos(a), cy - r * 0.7 * math.sin(a))],
          fill="#e8ecf5", width=5)
draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill="#ffd60a")

display.show(img)
''',
    ),
    Example(
        id="activity_rings",
        name="Activity rings",
        family="lcd",
        min_colors=256,
        shape="round",
        code='''\
from waveshare_sim import display
from PIL import Image, ImageDraw

w, h = display.width, display.height
cx, cy = w / 2, h / 2
R = min(w, h) / 2 - 6

img = Image.new("RGB", (w, h), "#000000")
draw = ImageDraw.Draw(img)

rings = [("#ff2d55", 0.82), ("#a8ff00", 0.63), ("#00e5ff", 0.95)]
thick = max(6, int(R / 9))
gap = thick + 4
for i, (color, frac) in enumerate(rings):
    rad = R - i * gap
    box = [cx - rad, cy - rad, cx + rad, cy + rad]
    draw.arc(box, 0, 360, fill="#1c1c1e", width=thick)       # track
    draw.arc(box, -90, -90 + 360 * frac, fill=color, width=thick)  # progress

display.show(img)
''',
    ),
    Example(
        id="rainbow_rings",
        name="Rainbow rings",
        family="lcd",
        min_colors=256,
        shape="round",
        code='''\
import colorsys
from waveshare_sim import display
from PIL import Image, ImageDraw

w, h = display.width, display.height
cx, cy = w / 2, h / 2
R = min(w, h) / 2

img = Image.new("RGB", (w, h), "#000000")
draw = ImageDraw.Draw(img)

rings = 64
for i in range(rings, 0, -1):
    rad = R * i / rings
    cr, cg, cb = colorsys.hsv_to_rgb(i / rings, 0.9, 1.0)
    draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                 fill=(int(cr * 255), int(cg * 255), int(cb * 255)))

display.show(img)
''',
    ),
    Example(
        id="radial_eq",
        name="Radial equaliser",
        family="lcd",
        min_colors=256,
        shape="round",
        code='''\
import math, random, colorsys
from waveshare_sim import display
from PIL import Image, ImageDraw

w, h = display.width, display.height
cx, cy = w / 2, h / 2
R = min(w, h) / 2 - 2
inner = R * 0.45

img = Image.new("RGB", (w, h), "#05060a")
draw = ImageDraw.Draw(img)

random.seed(3)
bars = 48
for i in range(bars):
    a = math.radians(i * 360 / bars)
    amp = 0.35 + 0.65 * abs(math.sin(i * 0.7)) * random.uniform(0.5, 1.0)
    r2 = inner + (R - inner) * amp
    cr, cg, cb = colorsys.hsv_to_rgb(i / bars, 0.85, 1.0)
    draw.line([(cx + inner * math.cos(a), cy + inner * math.sin(a)),
               (cx + r2 * math.cos(a), cy + r2 * math.sin(a))],
              fill=(int(cr * 255), int(cg * 255), int(cb * 255)), width=4)
draw.ellipse([cx - inner, cy - inner, cx + inner, cy + inner], outline="#222633", width=2)

display.show(img)
''',
    ),
    Example(
        id="bar_chart",
        name="Bar chart",
        family="any",
        code='''\
from waveshare_sim import display
from PIL import Image, ImageDraw

w, h = display.width, display.height
img = Image.new(display.mode, (w, h), display.bg)
draw = ImageDraw.Draw(img)

data = [3, 7, 4, 8, 6, 9, 5]

# Pick bar colours the panel can actually show.
if display.palette and len(display.palette) >= 3:
    palette = [c for c in display.palette if c.lower() not in ("#ffffff", "#000000")] or list(display.palette)
    def bar_colour(i):
        return palette[i % len(palette)]
elif display.mode == "RGB":
    accent = ["#ff3b30", "#ff9500", "#ffcc00", "#34c759", "#5ac8fa", "#007aff", "#af52de"]
    def bar_colour(i):
        return accent[i % len(accent)]
else:
    def bar_colour(i):
        return display.fg

pad = max(4, w // 20)
n = len(data)
bw = (w - pad * (n + 1)) / n
mx = max(data)
base = h - pad
for i, v in enumerate(data):
    bh = (v / mx) * (h - 2 * pad)
    x0 = pad + i * (bw + pad)
    draw.rectangle([x0, base - bh, x0 + bw, base], fill=bar_colour(i))
draw.line([(0, base), (w, base)], fill=display.fg)

display.show(img)
''',
    ),
    Example(
        id="starfield",
        name="Starfield",
        family="any",
        code='''\
import random
from waveshare_sim import display
from PIL import Image, ImageDraw

w, h = display.width, display.height
img = Image.new(display.mode, (w, h), display.bg)
draw = ImageDraw.Draw(img)

random.seed(42)
for _ in range(int(w * h / 300)):
    x = random.randint(0, w - 1)
    y = random.randint(0, h - 1)
    s = random.choice([0, 0, 1])  # mostly single pixels, a few brighter
    draw.ellipse([x, y, x + s, y + s], fill=display.fg)

display.show(img)
''',
    ),
    Example(
        id="gradient",
        name="Rainbow gradient",
        family="any",
        min_colors=256,
        code='''\
import colorsys
from waveshare_sim import display
from PIL import Image, ImageDraw

w, h = display.width, display.height
img = Image.new("RGB", (w, h))
draw = ImageDraw.Draw(img)

# One horizontal line per row keeps this fast even at 480x480.
for y in range(h):
    cr, cg, cb = colorsys.hsv_to_rgb(y / h, 0.7, 1.0)
    draw.line([(0, y), (w, y)], fill=(int(cr * 255), int(cg * 255), int(cb * 255)))

display.show(img)
''',
    ),
    Example(
        id="julia",
        name="Julia fractal",
        family="any",
        min_colors=256,
        code='''\
import colorsys
from waveshare_sim import display
from PIL import Image

w, h = display.width, display.height

# Compute at reduced resolution for speed, then upscale to the panel.
gw, gh = min(w, 160), min(h, 160)
img = Image.new("RGB", (gw, gh))
px = img.load()

cx, cy = -0.7, 0.27015
max_it = 48
for j in range(gh):
    for i in range(gw):
        zx = 3.0 * (i - gw / 2) / gw
        zy = 2.0 * (j - gh / 2) / gh
        it = 0
        while zx * zx + zy * zy < 4 and it < max_it:
            xt = zx * zx - zy * zy + cx
            zy = 2 * zx * zy + cy
            zx = xt
            it += 1
        if it >= max_it:
            px[i, j] = (0, 0, 0)
        else:
            cr, cg, cb = colorsys.hsv_to_rgb((0.6 + it / max_it) % 1.0, 0.85, 1.0)
            px[i, j] = (int(cr * 255), int(cg * 255), int(cb * 255))

display.show(img.resize((w, h), Image.BICUBIC))
''',
    ),
    Example(
        id="lcd1602_hello",
        name="Character LCD (16×2)",
        family="char",
        min_colors=256,
        code='''\
from waveshare_sim import display

# Character LCDs (HD44780 / LCD1602) don't take a framebuffer — you write text
# into their cell grid. `display.text_lines` renders each character as the
# classic 5x7 dot matrix on the blue backlight. Lines/columns past the panel's
# char_grid are clipped, exactly like the real controller.
cols, rows = display.char_grid or (16, 2)

display.text_lines([
    "Waveshare  LCD".center(cols),
    "16x2  HD44780".center(cols),
])
''',
    ),
    Example(
        id="lcd1602_meter",
        name="Char LCD bar meter",
        family="char",
        min_colors=256,
        code='''\
from waveshare_sim import display

# A CPU-style bar built from block characters — a common trick on 16x2 panels.
cols, rows = display.char_grid or (16, 2)
value = 0.67  # 0..1

label = "CPU"
bar_cells = cols - len(label) - 3  # room for "CPU " and trailing "%"
filled = round(value * bar_cells)
bar = "\\xff" * filled + "-" * (bar_cells - filled)  # 0xff = solid block glyph

line0 = f"{label} {bar}"
line1 = f"{int(value * 100):>3d}% load".center(cols)
display.text_lines([line0[:cols], line1[:cols]])
''',
    ),
]


# --- Device-ready starter code (real Waveshare vendor API) ------------------
#
# Generated per panel so the `import` and calls match the exact driver the
# selected display uses. This is the code that runs UNCHANGED on the Pi — the
# visualizer executes it against vendor-API shims that render the same pixels
# the panel would. Panels without a portable vendor driver (IT8951 12.48"/
# 9.7"/10.3", character LCDs) return None and the UI hides the button.

def device_snippet(entry: dict) -> str | None:
    driver = entry.get("driver")
    api = entry.get("api")
    if not driver or not api:
        return None
    family = entry.get("family", "lcd")

    if family == "epaper":
        return _epaper_snippet(driver, api)
    if family == "lcd":
        return _lcd_snippet(driver)
    if family == "oled":
        return _oled_snippet(driver, api)
    return None


def _epaper_snippet(driver: str, api: str) -> str:
    head = (
        f"from waveshare_epd import {driver}\n"
        "from PIL import Image, ImageDraw\n\n"
        f"epd = {driver}.EPD()\n"
    )
    if api == "epaper_4gray":
        return head + (
            "epd.init(0)          # 4-level grayscale mode\n"
            "epd.Clear(0xFF)\n\n"
            "img = Image.new('L', (epd.width, epd.height), 0xFF)\n"
            "draw = ImageDraw.Draw(img)\n"
            "# The panel renders exactly 4 greys: 0x00, 0x55/0x80, 0xAA/0xC0, 0xFF\n"
            "for i, g in enumerate((0x00, 0x80, 0xC0)):\n"
            "    draw.rectangle((10, 10 + i*40, epd.width-10, 40 + i*40), fill=g)\n"
            "draw.text((14, 6), 'e-Paper 4 gray', fill=0x00)\n\n"
            "epd.display_4Gray(epd.getbuffer_4Gray(img))\n"
            "epd.sleep()\n"
        )
    if api == "epaper_redblack":
        return head + (
            "epd.init()\n"
            "epd.Clear()\n\n"
            "# Two 1-bit planes: 0 = ink, 255 = paper.\n"
            "black = Image.new('1', (epd.width, epd.height), 255)\n"
            "red   = Image.new('1', (epd.width, epd.height), 255)\n"
            "ImageDraw.Draw(black).text((6, 6), 'Black text', fill=0)\n"
            "ImageDraw.Draw(red).rectangle((6, 30, epd.width-6, 52), fill=0)\n\n"
            "epd.display(epd.getbuffer(black), epd.getbuffer(red))\n"
            "epd.sleep()\n"
        )
    if api in ("epaper_4color", "epaper_6color", "epaper_7color"):
        colors = {
            "epaper_4color": "(0,0,0), (255,255,0), (255,0,0)",
            "epaper_6color": "(255,0,0), (0,0,255), (0,255,0), (255,255,0)",
            "epaper_7color": "(255,0,0), (0,255,0), (0,0,255), (255,255,0), (255,128,0)",
        }[api]
        return head + (
            "epd.init()\n"
            "epd.Clear()\n\n"
            "img = Image.new('RGB', (epd.width, epd.height), (255, 255, 255))\n"
            "draw = ImageDraw.Draw(img)\n"
            f"palette = [{colors}]\n"
            "band = epd.height // (len(palette) + 1)\n"
            "for i, c in enumerate(palette):\n"
            "    draw.rectangle((0, i*band, epd.width, (i+1)*band), fill=c)\n"
            "draw.text((8, len(palette)*band + 6), 'Colour e-Paper', fill=(0, 0, 0))\n\n"
            "epd.display(epd.getbuffer(img))\n"
            "epd.sleep()\n"
        )
    # mono (and gray16 handled as mono-ish here won't reach: driver None)
    return head + (
        "epd.init()\n"
        "epd.Clear(0xFF)\n\n"
        "img = Image.new('1', (epd.width, epd.height), 255)  # 255 = white\n"
        "draw = ImageDraw.Draw(img)\n"
        "draw.rectangle((2, 2, epd.width-3, epd.height-3), outline=0)\n"
        "draw.text((10, 12), 'Hello e-Paper', fill=0)\n\n"
        "epd.display(epd.getbuffer(img))\n"
        "epd.sleep()\n"
    )


def _lcd_snippet(driver: str) -> str:
    return (
        f"from lib import {driver}\n"
        "from PIL import Image, ImageDraw\n\n"
        f"disp = {driver}.{driver}()\n"
        "disp.Init()\n"
        "disp.clear()\n"
        "disp.bl_DutyCycle(50)   # 50% backlight\n\n"
        "img = Image.new('RGB', (disp.width, disp.height), (0, 0, 0))\n"
        "draw = ImageDraw.Draw(img)\n"
        "draw.rectangle((0, 0, disp.width-1, disp.height-1), outline=(255, 255, 255))\n"
        "draw.text((10, 10), 'Hello LCD', fill=(0, 200, 255))\n\n"
        "disp.ShowImage(img)\n"
    )


def _oled_snippet(driver: str, api: str) -> str:
    if api == "oled_rgb":
        mode, bg, fill = "'RGB'", "(0, 0, 0)", "(0, 200, 255)"
        draw_extra = "draw.rectangle((0, 0, disp.width-1, disp.height-1), outline=(255, 0, 0))\n"
    elif api == "oled_gray16":
        mode, bg, fill = "'L'", "0", "255"
        draw_extra = "for i in range(4):\n    draw.rectangle((i*disp.width//4, disp.height-8, (i+1)*disp.width//4, disp.height), fill=i*80)\n"
    else:  # oled_mono
        mode, bg, fill = "'1'", "0", "1"
        draw_extra = "draw.rectangle((0, 0, disp.width-1, disp.height-1), outline=1)\n"
    return (
        f"from lib import {driver}\n"
        "from PIL import Image, ImageDraw\n\n"
        f"disp = {driver}.{driver}()\n"
        "disp.Init()\n"
        "disp.clear()\n\n"
        f"img = Image.new({mode}, (disp.width, disp.height), {bg})\n"
        "draw = ImageDraw.Draw(img)\n"
        f"draw.text((4, 4), 'OLED', fill={fill})\n"
        f"{draw_extra}\n"
        "disp.ShowImage(disp.getbuffer(img))\n"
    )
