"""Generate a stylised SVG bezel for a display entry.

We don't ship 20 SVG files — we synthesise them from the ``screen_bbox`` in
displays.json. The resulting SVG has a viewBox where (0,0)..(canvas_w,canvas_h)
matches the bezel image coordinate system that the frontend uses for
compositing the rendered framebuffer.

Users who want real product photos can drop a ``{display_id}.jpg`` (or .png)
under ``backend/assets/photos/`` and update ``screen_bbox`` to match. The
backend serves the photo instead of the generated SVG when it exists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


BEZEL_OUTER_MARGIN = 60  # px around the screen_bbox to pad the PCB


def canvas_size(entry: dict[str, Any], photos_dir: Path | None = None) -> tuple[int, int]:
    """Return the (width, height) of the bezel image coordinate system.

    Order of precedence:

    1. Explicit ``canvas`` field in the catalog entry — used when a display's
       bezel image doesn't sit centred around ``screen_bbox``.
    2. Actual dimensions of a real photo dropped into ``photos_dir`` — probed
       with Pillow so the frontend positions the render correctly regardless
       of the photo's aspect ratio.
    3. Symmetric fallback ``(x*2 + w, y*2 + h)`` — used when only the
       procedural SVG bezel is drawn.

    The frontend uses the returned canvas to convert ``screen_bbox`` pixel
    coordinates into percentages, so this MUST match whatever image
    ``/api/displays/{id}/bezel`` actually serves.
    """
    canvas = entry.get("canvas")
    if canvas and len(canvas) == 2:
        return (int(canvas[0]), int(canvas[1]))
    if photos_dir is not None:
        photo = photo_path(entry["id"], photos_dir)
        if photo is not None:
            try:
                from PIL import Image
                with Image.open(photo) as im:
                    return im.size
            except Exception:
                pass  # fall through to symmetric fallback
    x, y, w, h = entry["screen_bbox"]
    return (x * 2 + w, y * 2 + h)


def _family_theme(family: str) -> dict[str, str]:
    if family == "epaper":
        return {"pcb": "#1e5c3a", "trace": "#2d7a4d", "bg": "#f5f5ee"}
    if family == "lcd":
        return {"pcb": "#0b1730", "trace": "#1b2a55", "bg": "#000000"}
    if family == "oled":
        return {"pcb": "#111111", "trace": "#2a2a2a", "bg": "#000000"}
    if family == "char":
        # Character LCD: green solder mask, blue backlit glass.
        return {"pcb": "#0b3d2e", "trace": "#12684a", "bg": "#122ac4"}
    return {"pcb": "#333333", "trace": "#555555", "bg": "#111111"}


def generate_svg(entry: dict[str, Any]) -> str:
    if entry.get("shape") == "round":
        return generate_round_svg(entry)

    cw, ch = canvas_size(entry)
    x, y, w, h = entry["screen_bbox"]
    theme = _family_theme(entry["family"])
    name = entry["name"]

    hole_r = 12
    corner_r = 24
    label_y = y + h + 40 if (y + h + 40) < ch - 10 else ch - 10

    # preserveAspectRatio="none": the frontend stretches the bezel image to fill
    # its frame (photos, being plain <img>, do the same) and positions the screen
    # overlay as a percentage of that same frame. Letterboxing here would shrink
    # the drawn screen away from where the overlay sits.
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {cw} {ch}" preserveAspectRatio="none">
  <defs>
    <linearGradient id="pcb" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{theme['pcb']}"/>
      <stop offset="1" stop-color="{theme['trace']}"/>
    </linearGradient>
    <filter id="innerShadow" x="-10%" y="-10%" width="120%" height="120%">
      <feGaussianBlur in="SourceAlpha" stdDeviation="3"/>
      <feOffset dx="0" dy="2"/>
      <feComposite in2="SourceAlpha" operator="arithmetic" k2="-1" k3="1"/>
      <feColorMatrix values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.4 0"/>
      <feComposite in2="SourceAlpha" operator="in"/>
      <!-- Merge the shadow back over the shape: compositing "in" against
           SourceGraphic alone would output only the shadow, dropping the
           screen's own fill so an idle panel showed the PCB recess colour
           instead of its glass (paper white on e-paper, black on LCD/OLED). -->
      <feMerge>
        <feMergeNode in="SourceGraphic"/>
        <feMergeNode/>
      </feMerge>
    </filter>
  </defs>
  <rect x="0" y="0" width="{cw}" height="{ch}" rx="{corner_r}" ry="{corner_r}" fill="url(#pcb)"/>
  <rect x="0" y="0" width="{cw}" height="{ch}" rx="{corner_r}" ry="{corner_r}" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
  <circle cx="{hole_r + 8}" cy="{hole_r + 8}" r="{hole_r}" fill="#222" stroke="#555" stroke-width="2"/>
  <circle cx="{cw - hole_r - 8}" cy="{hole_r + 8}" r="{hole_r}" fill="#222" stroke="#555" stroke-width="2"/>
  <circle cx="{hole_r + 8}" cy="{ch - hole_r - 8}" r="{hole_r}" fill="#222" stroke="#555" stroke-width="2"/>
  <circle cx="{cw - hole_r - 8}" cy="{ch - hole_r - 8}" r="{hole_r}" fill="#222" stroke="#555" stroke-width="2"/>
  <rect x="{x - 6}" y="{y - 6}" width="{w + 12}" height="{h + 12}" rx="6" ry="6" fill="#0a0a0a"/>
  <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{theme['bg']}" filter="url(#innerShadow)"/>
  <text x="{cw / 2}" y="{label_y}" text-anchor="middle" font-family="ui-sans-serif, system-ui, sans-serif" font-size="18" fill="rgba(255,255,255,0.55)">{_escape(name)}</text>
</svg>"""


def generate_round_svg(entry: dict[str, Any]) -> str:
    """Synthesise a circular PCB bezel for a round LCD (e.g. GC9A01, ST7701S).

    ``screen_bbox`` is the bounding square of the circular glass; the visible
    screen is the inscribed circle. The frontend clips the composited
    framebuffer to the same circle, and the sim blanks the corners, so what the
    user sees matches the round panel.
    """
    cw, ch = canvas_size(entry)
    x, y, w, h = entry["screen_bbox"]
    theme = _family_theme(entry["family"])
    name = entry["name"]

    cx, cy = x + w / 2, y + h / 2
    screen_r = min(w, h) / 2
    board_r = min(cw, ch) / 2 - 4
    bezel_r = screen_r + 14  # dark ring of glass around the active area

    # Four mounting holes on the diagonals, just inside the board edge.
    import math

    hole_r = 12
    hole_orbit = board_r - hole_r - 10
    holes = "".join(
        f'<circle cx="{cx + hole_orbit * math.cos(a):.1f}" cy="{cy + hole_orbit * math.sin(a):.1f}" '
        f'r="{hole_r}" fill="#1a1a1a" stroke="#555" stroke-width="2"/>'
        for a in (math.radians(d) for d in (45, 135, 225, 315))
    )

    # See generate_svg: the frame is stretched to the bezel's aspect ratio, so the
    # SVG must map onto it exactly rather than letterbox inside it.
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {cw} {ch}" preserveAspectRatio="none">
  <defs>
    <radialGradient id="pcb" cx="0.5" cy="0.4" r="0.7">
      <stop offset="0" stop-color="{theme['trace']}"/>
      <stop offset="1" stop-color="{theme['pcb']}"/>
    </radialGradient>
    <filter id="innerShadow" x="-10%" y="-10%" width="120%" height="120%">
      <feGaussianBlur in="SourceAlpha" stdDeviation="3"/>
      <feOffset dx="0" dy="2"/>
      <feComposite in2="SourceAlpha" operator="arithmetic" k2="-1" k3="1"/>
      <feColorMatrix values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.4 0"/>
      <feComposite in2="SourceAlpha" operator="in"/>
      <!-- Merge the shadow back over the shape: compositing "in" against
           SourceGraphic alone would output only the shadow, dropping the
           screen's own fill so an idle panel showed the PCB recess colour
           instead of its glass (paper white on e-paper, black on LCD/OLED). -->
      <feMerge>
        <feMergeNode in="SourceGraphic"/>
        <feMergeNode/>
      </feMerge>
    </filter>
  </defs>
  <circle cx="{cx}" cy="{cy}" r="{board_r}" fill="url(#pcb)"/>
  <circle cx="{cx}" cy="{cy}" r="{board_r}" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>
  {holes}
  <circle cx="{cx}" cy="{cy}" r="{bezel_r}" fill="#0a0a0a"/>
  <circle cx="{cx}" cy="{cy}" r="{screen_r}" fill="{theme['bg']}" filter="url(#innerShadow)"/>
  <text x="{cx}" y="{cy + screen_r + 34 if (cy + screen_r + 34) < ch - 8 else ch - 8}" text-anchor="middle" font-family="ui-sans-serif, system-ui, sans-serif" font-size="18" fill="rgba(255,255,255,0.55)">{_escape(name)}</text>
</svg>"""


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def photo_path(display_id: str, photos_dir: Path) -> Path | None:
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = photos_dir / f"{display_id}{ext}"
        if candidate.exists():
            return candidate
    return None
