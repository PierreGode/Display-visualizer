"""Web-driven ``claude auth login`` flow.

The Claude Code CLI's OAuth login is interactive: it prints an authorization
URL and then parks at a ``Paste code here`` prompt waiting for the code the
user receives after authorizing in their browser. The PKCE verifier lives
inside that one CLI process, so the *same* process that produced the URL must
be the one that receives the code.

This module spawns ``claude auth login`` under a pty, extracts the URL, keeps
the process parked at the prompt, and later feeds the pasted code back to
complete the exchange. Sessions are short-lived and reaped on completion or
timeout.

Credentials are written to wherever ``CLAUDE_CONFIG_DIR`` (inherited from the
process env) points — the installer sets that to a service-writable directory
so this works even though the systemd unit mounts ``/home`` read-only.
"""

from __future__ import annotations

import os
import pty
import re
import select
import signal
import threading
import time
import uuid
from dataclasses import dataclass

# CSI escape sequences (colours, cursor moves). We strip these for display and
# for the plain-text URL fallback.
_ANSI_CSI = re.compile(rb"\x1b\[[0-9;?]*[a-zA-Z]")
# OSC 8 hyperlink: ESC ] 8 ; ; <target> (ST|BEL). The target is the clean URL.
_OSC8_URL = re.compile(rb"\x1b\]8;;(https://[^\x1b\x07]+)")
# Fallback: a bare authorize URL in the plain text.
_PLAIN_URL = re.compile(r"https://\S+?/oauth/authorize\S*")

_PROMPT_HINT = b"Paste code"
# The CLI prints one of these and re-prompts (without exiting) when the pasted
# code is rejected, so we can report a retryable failure instead of hanging.
_BAD_CODE = re.compile(r"invalid code|did not match|expired|login failed|please try again", re.I)
START_TIMEOUT = 30.0   # seconds to wait for the URL to appear
FINISH_TIMEOUT = 45.0  # seconds to wait for the CLI to exchange the code
SESSION_TTL = 600.0    # a pending login may stay open this long


@dataclass
class _Session:
    id: str
    pid: int
    fd: int
    url: str
    created: float


_sessions: dict[str, _Session] = {}
_lock = threading.Lock()


def _strip(raw: bytes) -> str:
    return _ANSI_CSI.sub(b"", raw).decode("utf-8", "replace")


def _extract_url(raw: bytes) -> str | None:
    m = _OSC8_URL.search(raw)
    if m:
        return m.group(1).decode("utf-8", "replace").strip()
    # Fallback: dedupe a doubled plain-text URL (the CLI prints the link target
    # and the visible text back to back with no separator).
    m2 = _PLAIN_URL.search(_strip(raw))
    if not m2:
        return None
    url = m2.group(0)
    dup = url.find("https://", 8)
    return url[:dup] if dup != -1 else url


def _kill(sess: _Session) -> None:
    try:
        os.kill(sess.pid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass
    try:
        os.close(sess.fd)
    except OSError:
        pass
    try:
        os.waitpid(sess.pid, 0)
    except (ChildProcessError, OSError):
        pass


def _reap_expired() -> None:
    now = time.time()
    for sid, sess in list(_sessions.items()):
        if now - sess.created > SESSION_TTL:
            _kill(sess)
            _sessions.pop(sid, None)


def start() -> dict:
    """Begin a login: spawn the CLI and return ``{session_id, url}`` or ``{error}``."""
    with _lock:
        _reap_expired()

    pid, fd = pty.fork()
    if pid == 0:  # child
        # Keep colours off so the visible prompt text is easy to match, but the
        # OSC 8 hyperlink (which carries the clean URL) is emitted regardless.
        os.environ["FORCE_COLOR"] = "0"
        os.environ["NO_COLOR"] = "1"
        try:
            os.execvp("claude", ["claude", "auth", "login", "--claudeai"])
        except OSError:
            os._exit(127)
        os._exit(127)  # unreachable

    buf = b""
    url: str | None = None
    deadline = time.time() + START_TIMEOUT
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], 0.5)
        if fd in r:
            try:
                data = os.read(fd, 4096)
            except OSError:
                break
            if not data:
                break
            buf += data
            if _PROMPT_HINT in buf:
                url = _extract_url(buf)
                if url:
                    break

    if not url:
        _kill(_Session("", pid, fd, "", time.time()))
        detail = _strip(buf).strip()
        return {"error": f"could not obtain a login URL from the claude CLI. Output: {detail[:600]}"}

    sid = uuid.uuid4().hex
    with _lock:
        _sessions[sid] = _Session(sid, pid, fd, url, time.time())
    return {"session_id": sid, "url": url}


def submit(session_id: str, code: str) -> dict:
    """Feed the pasted code to the parked CLI and report the outcome.

    Success signal: the CLI *exits* (it only does so once the code exchange
    succeeds and credentials are written). A rejected code makes the CLI print
    an "Invalid code" message and re-prompt without exiting — we detect that and
    keep the session alive so the user can paste a corrected code.
    """
    with _lock:
        sess = _sessions.get(session_id)
    if not sess:
        return {"ok": False, "error": "unknown or expired login session — start over"}

    code = code.strip()
    if not code:
        return {"ok": False, "error": "empty code"}

    try:
        os.write(sess.fd, (code + "\n").encode("utf-8"))
    except OSError as e:
        _drop(session_id)
        _kill(sess)
        return {"ok": False, "error": f"failed to send code to CLI: {e}"}

    buf = b""
    deadline = time.time() + FINISH_TIMEOUT
    exited = False
    while time.time() < deadline:
        r, _, _ = select.select([sess.fd], [], [], 0.5)
        if sess.fd in r:
            try:
                data = os.read(sess.fd, 4096)
            except OSError:
                break
            if data:
                buf += data
        try:
            wpid, _ = os.waitpid(sess.pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            wpid = sess.pid
        if wpid == sess.pid:
            exited = True
            break
        # Rejected code: the CLI stays alive and re-prompts. Report a retryable
        # error and leave the session open so the user can try again.
        if _BAD_CODE.search(_strip(buf)):
            return {"ok": False, "error": "Invalid code — copy the full code from the authorization page and try again.", "retryable": True}

    output = _strip(buf).strip()
    _drop(session_id)
    _kill(sess)

    if not exited:
        return {"ok": False, "error": "timed out waiting for the CLI to accept the code — start the sign-in again.", "output": output[-600:]}

    # Exited cleanly — confirm credentials actually landed.
    from . import claude_agent

    st = claude_agent.check_status()
    if st.authenticated:
        return {"ok": True, "email": st.email, "output": output[-600:]}
    return {
        "ok": False,
        "error": "the CLI exited but still reports logged-out. Output: " + (output[-300:] or "(none)"),
    }


def _drop(session_id: str) -> None:
    with _lock:
        _sessions.pop(session_id, None)


def cancel(session_id: str) -> dict:
    with _lock:
        sess = _sessions.pop(session_id, None)
    if sess:
        _kill(sess)
    return {"ok": True}
