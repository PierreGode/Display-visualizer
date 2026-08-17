"""Self-update: check for new commits on origin/main and trigger a pull+rebuild+restart.

Design:
  * ``status()`` shells out to ``git`` in the repo root to compare local HEAD with
    ``origin/main``. It runs ``git fetch`` at most once every FETCH_INTERVAL_SEC
    seconds so the endpoint stays cheap for frontend polling.
  * ``trigger_update()`` spawns ``update.sh`` detached from the current
    process. The script does the actual work (pull, pip install, npm build,
    systemctl restart), so this process can exit or be killed mid-restart
    without leaving the update half-done.
  * When not inside a git checkout (e.g. running from a source archive) all
    functions return a stub status without erroring.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
UPDATE_SCRIPT = REPO_ROOT / "update.sh"
FETCH_INTERVAL_SEC = 60.0  # rate-limit `git fetch` per process


@dataclass
class UpdateStatus:
    in_git_repo: bool
    branch: str | None
    local_sha: str | None
    local_short: str | None
    remote_sha: str | None
    remote_short: str | None
    behind: int  # commits local is behind remote
    ahead: int   # commits local is ahead of remote
    update_available: bool
    latest_commit_message: str | None
    last_checked: float  # unix ts
    error: str | None = None
    can_apply: bool = False  # is update.sh present + executable?


_cache: UpdateStatus | None = None
_last_fetch_ts: float = 0.0


def _run(args: list[str], timeout: float = 15.0) -> tuple[int, str, str]:
    proc = subprocess.run(
        args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _is_git_repo() -> bool:
    return (REPO_ROOT / ".git").exists() and shutil.which("git") is not None


def status(force_fetch: bool = False) -> UpdateStatus:
    """Return current update state. Runs `git fetch` if the cached data is stale."""
    global _cache, _last_fetch_ts

    if not _is_git_repo():
        return UpdateStatus(
            in_git_repo=False,
            branch=None,
            local_sha=None,
            local_short=None,
            remote_sha=None,
            remote_short=None,
            behind=0,
            ahead=0,
            update_available=False,
            latest_commit_message=None,
            last_checked=time.time(),
            error="not a git checkout — auto-updates are disabled",
        )

    now = time.time()
    should_fetch = force_fetch or (now - _last_fetch_ts) >= FETCH_INTERVAL_SEC

    try:
        if should_fetch:
            # --tags is useful for showing release tags later. Ignore network errors
            # so a temporarily-offline Pi still returns cached status.
            fetch_rc, _, fetch_err = _run(["git", "fetch", "--quiet", "origin", "main"], timeout=20)
            if fetch_rc != 0 and _cache is not None:
                # Return cached status with an appended note.
                cached = _cache
                return UpdateStatus(**{**cached.__dict__, "error": f"fetch failed: {fetch_err}", "last_checked": now})
            _last_fetch_ts = now

        rc_local, local_sha, _ = _run(["git", "rev-parse", "HEAD"])
        rc_remote, remote_sha, _ = _run(["git", "rev-parse", "origin/main"])
        rc_branch, branch, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if rc_local or rc_remote or rc_branch:
            raise RuntimeError("git rev-parse failed")

        # count ahead/behind
        rc_counts, counts, _ = _run(["git", "rev-list", "--left-right", "--count", f"{local_sha}...{remote_sha}"])
        if rc_counts == 0 and counts:
            ahead_str, behind_str = counts.split()
            ahead, behind = int(ahead_str), int(behind_str)
        else:
            ahead, behind = 0, 0

        _, message, _ = _run(["git", "log", "-1", "--format=%s", "origin/main"])

        st = UpdateStatus(
            in_git_repo=True,
            branch=branch,
            local_sha=local_sha,
            local_short=local_sha[:7],
            remote_sha=remote_sha,
            remote_short=remote_sha[:7],
            behind=behind,
            ahead=ahead,
            update_available=behind > 0,
            latest_commit_message=message or None,
            last_checked=now,
            error=None,
            can_apply=UPDATE_SCRIPT.exists() and os.access(UPDATE_SCRIPT, os.X_OK),
        )
        _cache = st
        return st
    except Exception as e:
        if _cache:
            return UpdateStatus(**{**_cache.__dict__, "error": str(e), "last_checked": now})
        return UpdateStatus(
            in_git_repo=True,
            branch=None,
            local_sha=None,
            local_short=None,
            remote_sha=None,
            remote_short=None,
            behind=0,
            ahead=0,
            update_available=False,
            latest_commit_message=None,
            last_checked=now,
            error=str(e),
        )


def trigger_update() -> dict[str, Any]:
    """Spawn update.sh detached; return immediately."""
    st = status(force_fetch=True)
    if not st.in_git_repo:
        return {"ok": False, "error": "not a git checkout"}
    if not st.update_available:
        return {"ok": False, "error": "already up to date"}
    if not UPDATE_SCRIPT.exists():
        return {"ok": False, "error": f"{UPDATE_SCRIPT} missing — installer may not have set it up"}
    if not os.access(UPDATE_SCRIPT, os.X_OK):
        return {"ok": False, "error": f"{UPDATE_SCRIPT} not executable"}

    log_path = Path("/tmp") / f"display-visualizer-update-{int(time.time())}.log"
    try:
        # Fully detach: new session, new stdio → the child survives this process
        # being killed by systemd during `restart`.
        log_fh = open(log_path, "ab", buffering=0)
        subprocess.Popen(
            ["bash", str(UPDATE_SCRIPT)],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
        )
        return {
            "ok": True,
            "log": str(log_path),
            "message": f"Update started — pulling {st.local_short} → {st.remote_short}. The service will restart in ~1-2 minutes.",
        }
    except OSError as e:
        return {"ok": False, "error": f"failed to spawn update.sh: {e}"}
