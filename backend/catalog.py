"""Load and expose the display catalog."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parent / "displays.json"


@lru_cache(maxsize=1)
def _load_raw() -> dict[str, Any]:
    with CATALOG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def all_displays() -> list[dict[str, Any]]:
    return list(_load_raw()["displays"])


def get_display(display_id: str) -> dict[str, Any] | None:
    for entry in _load_raw()["displays"]:
        if entry["id"] == display_id:
            return entry
    return None


def capabilities(entry: dict[str, Any]) -> dict[str, Any]:
    """Describe what a display's driver actually accepts.

    Kept here (not in main.py) so anything that has a catalog entry can
    infer capabilities without pulling in FastAPI.
    """
    mode = entry["mode"]
    palette = entry.get("palette")
    if mode == "RGB":
        colors = 16_777_216
        supports_color = True
    elif mode == "P":
        colors = len(palette) if palette else 2
        supports_color = colors > 2 and any(
            c.lower() not in ("#000000", "#ffffff") for c in (palette or [])
        )
    elif mode == "L":
        colors = 256
        supports_color = False
    else:  # "1"
        colors = 2
        supports_color = False
    return {
        "mode": mode,
        "colors": colors,
        "supports_color": supports_color,
        "shape": entry.get("shape", "rect"),
    }
