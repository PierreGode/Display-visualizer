"""Runtime that user code imports via ``import waveshare_sim as ws``.

Not imported by the backend directly — this package sits on sys.path only inside
the sandboxed subprocess that runs user code.
"""

from .display import Display, display  # re-exports for `from waveshare_sim import display`

__all__ = ["Display", "display"]
