"""Turn raw Python tracebacks from user code into short, human-friendly messages.

User code runs in a subprocess (see runner.py); on failure all we have is the
captured stderr text. ``humanize`` parses that text and returns a one-or-two
line summary suitable for showing above the (still-available) raw traceback:

    Undefined name — line 7
    You used 'drw' before it was defined. Check for a typo or a missing
    assignment (did you mean 'draw'?).

It never raises: if the text doesn't look like a traceback (e.g. our timeout
notice, which is already friendly) it returns ``None`` and the caller shows the
original text unchanged.
"""

from __future__ import annotations

import re

USER_FILE = "user_main.py"

# Exception class -> short human title. Anything not listed falls back to the
# class name itself, so unknown errors still render sanely.
_TITLES = {
    "ModuleNotFoundError": "Missing module",
    "ImportError": "Import problem",
    "SyntaxError": "Syntax error",
    "IndentationError": "Indentation error",
    "TabError": "Indentation error",
    "NameError": "Undefined name",
    "UnboundLocalError": "Variable used too early",
    "AttributeError": "Unknown attribute or method",
    "TypeError": "Type mismatch",
    "ValueError": "Bad value",
    "IndexError": "Index out of range",
    "KeyError": "Missing key",
    "ZeroDivisionError": "Division by zero",
    "FileNotFoundError": "No file access",
    "PermissionError": "Blocked by the sandbox",
    "OSError": "System error",
    "MemoryError": "Out of memory",
    "RecursionError": "Too much recursion",
    "OverflowError": "Number too large",
    "KeyboardInterrupt": "Interrupted",
}

# Generic follow-up hints. Kept short; only shown when we have one and the
# exception's own message doesn't already spell it out.
_HINTS = {
    "ModuleNotFoundError": (
        "That package isn't in the sandbox. Use `from waveshare_sim import "
        "display`, or the panel's own driver (the ⤓ Device code button)."
    ),
    "NameError": "Check for a typo or a missing assignment.",
    "UnboundLocalError": "Assign the variable before you use it.",
    "SyntaxError": "Look for a missing bracket, quote, comma, or colon.",
    "IndentationError": "Python is strict about consistent spaces — line up your blocks.",
    "TabError": "Don't mix tabs and spaces — pick one.",
    "AttributeError": "Check the spelling, or the display API in the panel above.",
    "TypeError": "A value has the wrong type, or a call got the wrong arguments.",
    "ValueError": "A value is the wrong format or out of range.",
    "IndexError": "You went past the end of a list or sequence.",
    "KeyError": "That key isn't in the dictionary.",
    "FileNotFoundError": "User code can't read files — draw with PIL instead.",
}


def _closest_name(bad: str, candidates: list[str]) -> str | None:
    """Cheap 'did you mean' — case-insensitive, edit-distance <= 2, len-aware."""
    import difflib

    hits = difflib.get_close_matches(bad, candidates, n=1, cutoff=0.75)
    return hits[0] if hits else None


def humanize(stderr: str) -> str | None:
    """Return a short human summary of a Python traceback, or None if the text
    isn't a traceback we should rewrite."""
    text = (stderr or "").strip()
    if not text:
        return None

    lines = text.splitlines()

    # The exception summary is the trailing block of unindented line(s) that
    # follow the last "  File ..." frame. A SyntaxError has no
    # "Traceback (most recent call last):" header but still ends this way.
    frame_idxs = [i for i, ln in enumerate(lines) if ln.lstrip().startswith('File "')]
    if not frame_idxs:
        # Not a traceback (e.g. our timeout / "no image" notices). Leave as-is.
        return None

    exc_start = None
    for i in range(frame_idxs[-1] + 1, len(lines)):
        if lines[i] and not lines[i][0].isspace():
            exc_start = i
            break
    if exc_start is None:
        return None

    exc_block = "\n".join(lines[exc_start:]).strip()
    if not exc_block:
        return None

    # First line is "ExceptionType: message" (message may continue on the
    # following lines, e.g. our own multi-line ImportError guidance).
    first, _, rest = exc_block.partition("\n")
    m = re.match(r"^([A-Za-z_][\w.]*)\s*:?\s*(.*)$", first)
    if not m:
        return None
    exc_type = m.group(1).split(".")[-1]
    exc_msg = m.group(2).strip()
    if rest:
        exc_msg = (exc_msg + "\n" + rest).strip()

    # The user's own line number (last frame pointing at their file).
    user_line = None
    for ln in lines:
        mm = re.search(rf'File "[^"]*{re.escape(USER_FILE)}", line (\d+)', ln)
        if mm:
            user_line = int(mm.group(1))
    where = f" — line {user_line}" if user_line else ""

    title = _TITLES.get(exc_type, exc_type)

    # Our own ImportError guard (panel/code mismatch) is already fully written
    # for humans — show its message verbatim under a compact title.
    if exc_type in ("ImportError", "ModuleNotFoundError") and "selected display" in exc_msg:
        return f"{title}{where}\n{exc_msg}"

    # NameError: try a 'did you mean' against names the user code defines.
    hint = _HINTS.get(exc_type)
    if exc_type == "NameError":
        nm = re.search(r"name '([^']+)'", exc_msg)
        if nm:
            # Pull candidate identifiers out of the traceback's shown source
            # lines (best-effort; we don't have the full script here).
            src = " ".join(l.strip() for l in lines if l.startswith("    "))
            names = sorted(set(re.findall(r"[A-Za-z_]\w+", src)))
            guess = _closest_name(nm.group(1), [n for n in names if n != nm.group(1)])
            if guess:
                hint = f"Check for a typo or a missing assignment (did you mean '{guess}'?)."

    # Python 3.13 already appends its own "Did you mean: 'x'?" to many messages;
    # don't stack a generic hint on top of a specific suggestion.
    if hint and "did you mean" in exc_msg.lower():
        hint = None

    parts = [f"{title}{where}"]
    if exc_msg:
        parts.append(exc_msg)
    if hint:
        parts.append(hint)
    return "\n".join(p for p in parts if p)
