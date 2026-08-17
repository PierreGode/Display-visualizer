"""Sandboxed subprocess runner for user code.

Safety model (LAN tool, not internet-facing):
  * user code runs in a subprocess with a hard wall-clock timeout
  * PYTHONPATH is scoped to the sim package + tempdir; user cannot see the
    backend source tree
  * subprocess cwd is a fresh tempdir (deleted afterwards)
  * network isn't blocked at the OS level (would require unshare/nsjail on
    Linux, which we skip for MVP portability) — documented in README

This is enough to keep well-meaning users from tripping on each other's toes
on a shared Pi. It is not a defence against an attacker with shell access.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:  # package import (backend.runner) and flat import (runner) both work
    from . import errors as _errors
except ImportError:  # pragma: no cover
    import errors as _errors

SIM_PACKAGE_DIR = Path(__file__).resolve().parent  # so `import sim` works — we alias below
DEFAULT_TIMEOUT_SEC = 5.0
MAX_CODE_BYTES = 200_000


@dataclass
class RunResult:
    ok: bool
    stdout: str
    stderr: str
    image_base64: str | None  # PNG data-url payload (no prefix)
    duration_ms: int
    friendly: str | None = None  # human-readable summary of stderr, if any


def run_user_code(
    code: str,
    *,
    width: int,
    height: int,
    mode: str,
    palette: list[str] | None,
    shape: str = "rect",
    family: str = "lcd",
    char_grid: list[int] | None = None,
    api: str | None = None,
    driver: str | None = None,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> RunResult:
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        return RunResult(
            False, "", f"code too large (>{MAX_CODE_BYTES} bytes)", None, 0,
            friendly=f"Your code is over the {MAX_CODE_BYTES // 1000} KB limit. Trim it down and run again.",
        )

    tmpdir = Path(tempfile.mkdtemp(prefix="ws_run_"))
    try:
        user_script = tmpdir / "user_main.py"
        user_script.write_text(code, encoding="utf-8")
        out_png = tmpdir / "out.png"

        # Build a shadow "waveshare_sim" package pointing at our sim/ directory.
        # Easiest: prepend backend/ to PYTHONPATH and alias `sim` -> `waveshare_sim`
        # via a tiny .pth-free bridge in the tempdir.
        bridge_pkg = tmpdir / "waveshare_sim"
        bridge_pkg.mkdir()
        (bridge_pkg / "__init__.py").write_text(
            "from sim.display import Display, display\n"
            "__all__ = ['Display', 'display']\n",
            encoding="utf-8",
        )

        # Device-ready path: drop a shim package that mirrors the real Waveshare
        # driver API for the selected panel, so vendor-style code runs as-is.
        _write_vendor_shim(tmpdir, family=family, driver=driver, api=api)

        spec = {
            "width": width,
            "height": height,
            "mode": mode,
            "palette": palette,
            "shape": shape,
            "family": family,
            "char_grid": char_grid,
            "api": api,
            "driver": driver,
            "out_path": str(out_png),
        }
        import os
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": f"{tmpdir}{_pathsep()}{SIM_PACKAGE_DIR}",
                "WS_SIM_SPEC": json.dumps(spec),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
            }
        )
        # -s: no user site; -B: no .pyc. Don't use -I (isolated) — it drops PYTHONPATH.
        import time
        started = time.monotonic()
        try:
            proc = subprocess.run(
                [sys.executable, "-s", "-B", str(user_script)],
                cwd=tmpdir,
                env=env,
                capture_output=True,
                timeout=timeout_sec,
                text=True,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return RunResult(
                ok=False,
                stdout=(exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, (bytes, bytearray)) else (exc.stdout or ""),
                stderr=f"Timed out after {timeout_sec:.1f}s. Long-running loops are not supported — call display.show(img) once and exit.",
                image_base64=None,
                duration_ms=duration_ms,
                friendly=f"Your code ran longer than {timeout_sec:.0f} seconds and was stopped. Draw one frame and call display.show(img) once — infinite loops aren't supported here.",
            )
        duration_ms = int((time.monotonic() - started) * 1000)

        image_b64: str | None = None
        if out_png.exists():
            image_b64 = base64.b64encode(out_png.read_bytes()).decode("ascii")

        ok = proc.returncode == 0 and image_b64 is not None
        if ok:
            stderr = proc.stderr
            friendly = None
        elif proc.returncode == 0:
            # Ran cleanly but drew nothing — already a plain-English nudge.
            stderr = (proc.stderr + "\n[no output image produced]").strip()
            friendly = "No image was produced — did you call display.show(img) (or the driver's ShowImage/display) before your code ended?"
        else:
            stderr = proc.stderr
            friendly = _errors.humanize(proc.stderr)

        return RunResult(
            ok=ok,
            stdout=proc.stdout,
            stderr=stderr,
            image_base64=image_b64,
            duration_ms=duration_ms,
            friendly=friendly,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _pathsep() -> str:
    import os
    return os.pathsep


def _write_vendor_shim(tmpdir: Path, *, family: str, driver: str | None, api: str | None) -> None:
    """Materialise a vendor-API-compatible package for the selected panel.

    e-paper -> ``waveshare_epd/<driver>.py`` exposing ``EPD``.
    lcd/oled -> ``lib/<driver>.py`` exposing ``<driver>`` (module.class).
    Each is a one-liner binding to a factory in ``sim.drivers`` that reads the
    same ``WS_SIM_SPEC`` env the unified ``display`` uses.

    Both the ``waveshare_epd`` and ``lib`` package roots are always created, even
    for the family the selected panel does *not* belong to. Each root carries a
    ``__getattr__`` guard so importing a driver that doesn't match the selected
    panel raises a clear, actionable ImportError instead of the cryptic
    "No module named 'lib'" — the common footgun of running an LCD snippet while
    an e-paper panel is selected (or vice-versa).
    """
    epd_pkg = tmpdir / "waveshare_epd"
    lib_pkg = tmpdir / "lib"
    epd_pkg.mkdir(exist_ok=True)
    lib_pkg.mkdir(exist_ok=True)

    # The import line that *does* match the panel currently selected in the UI.
    if driver and family == "epaper":
        correct = f"from waveshare_epd import {driver}"
    elif driver and family in ("lcd", "oled"):
        correct = f"from lib import {driver}"
    else:
        correct = "the unified API:  from waveshare_sim import display"

    guard = (
        "import importlib\n"
        "def __getattr__(name):\n"
        "    try:\n"
        "        return importlib.import_module(f'.{name}', __name__)\n"
        "    except ModuleNotFoundError:\n"
        "        pass\n"
        "    raise ImportError(\n"
        "        f\"{name!r} is not available for the currently selected display.\\n\"\n"
        f"        \"This display's driver is:  {correct}\\n\"\n"
        "        \"Select the display that matches your code (or click the \\u2913 Device code \"\n"
        "        \"button to load the matching snippet), then run again.\"\n"
        "    )\n"
    )
    epd_pkg.joinpath("__init__.py").write_text(guard, encoding="utf-8")
    lib_pkg.joinpath("__init__.py").write_text(guard, encoding="utf-8")

    if not driver:
        return

    if family == "epaper":
        (epd_pkg / f"{driver}.py").write_text(
            "from sim.drivers import make_epd_class\n"
            "EPD = make_epd_class()\n",
            encoding="utf-8",
        )
    elif family in ("lcd", "oled"):
        factory = "make_lcd_class" if family == "lcd" else "make_oled_class"
        (lib_pkg / f"{driver}.py").write_text(
            f"from sim.drivers import {factory}\n"
            f"{driver} = {factory}()\n",
            encoding="utf-8",
        )
