"""Claude Code agent integration.

The visualizer embeds a Claude Code agent so users can ask it to write /
adapt display code, read files from a configured project directory, and
run the code against the currently selected simulated display.

Auth model:
  - The Anthropic OAuth flow lives in the ``claude`` CLI on the Pi.
    The user runs ``claude login`` once (over SSH is fine — it's a device
    flow with a URL + one-time code).
  - This module uses ``claude-agent-sdk`` which piggybacks on that
    authenticated CLI session, so we never touch OAuth tokens directly.

Sandbox:
  - Claude only gets our custom MCP tools (``mcp__waveshare__*``); built-in
    filesystem/bash tools are not in ``allowed_tools``.
  - ``read_project_file`` / ``list_project_files`` enforce that all paths
    stay inside ``CLAUDE_PROJECT_DIR`` (default ``/project``). Symlink
    escapes are blocked by resolving against the real path.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
    query,
    tool,
)

from . import catalog, runner

# --- Config -----------------------------------------------------------------

DEFAULT_PROJECT_DIR = "/project"
# Runtime override chosen from the web UI, persisted so it survives restarts.
# Lives in the install dir (writable by the service; untouched by reinstalls).
_STATE_FILE = Path(__file__).resolve().parent.parent / ".active_project"


def _configured_default() -> Path:
    raw = os.environ.get("CLAUDE_PROJECT_DIR", DEFAULT_PROJECT_DIR)
    return Path(raw).expanduser().resolve()


def project_dir() -> Path:
    """The directory the agent's file tools are scoped to.

    Precedence: a runtime selection made from the web UI (persisted in
    ``_STATE_FILE``) wins; otherwise the ``CLAUDE_PROJECT_DIR`` env default.
    """
    try:
        if _STATE_FILE.exists():
            raw = _STATE_FILE.read_text(encoding="utf-8").strip()
            if raw:
                p = Path(raw).expanduser().resolve()
                if p.is_dir():
                    return p
    except OSError:
        pass  # unreadable/missing selection — fall back to the configured default
    return _configured_default()


def set_project_dir(raw: str) -> dict:
    """Point the agent at any readable directory on the Pi. Validated and
    persisted; returns the resolved path or a reason it was rejected."""
    raw = (raw or "").strip()
    if not raw:
        return {"ok": False, "error": "empty path"}
    try:
        p = Path(raw).expanduser().resolve()
        is_dir = p.is_dir()  # can raise PermissionError on e.g. /root/*
    except OSError as e:
        return {"ok": False, "error": f"cannot access {raw!r}: {e}"}
    if not is_dir:
        return {"ok": False, "error": f"not a directory: {p}"}
    if not os.access(p, os.R_OK | os.X_OK):
        return {"ok": False, "error": f"not readable by the service user: {p}"}
    try:
        _STATE_FILE.write_text(str(p), encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": f"could not save selection: {e}"}
    return {"ok": True, "project_dir": str(p)}


# --- Auth / status ----------------------------------------------------------


@dataclass
class ClaudeStatus:
    cli_installed: bool
    cli_version: str | None
    authenticated: bool
    project_dir: str
    project_dir_exists: bool
    email: str | None = None
    error: str | None = None


def check_status() -> ClaudeStatus:
    pd = project_dir()
    cli = shutil.which("claude")
    if not cli:
        return ClaudeStatus(
            cli_installed=False,
            cli_version=None,
            authenticated=False,
            project_dir=str(pd),
            project_dir_exists=pd.exists(),
            error="`claude` CLI not found on PATH. Install with `npm install -g @anthropic-ai/claude-code`.",
        )
    try:
        version = subprocess.run(
            [cli, "--version"], capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        return ClaudeStatus(
            cli_installed=True,
            cli_version=None,
            authenticated=False,
            project_dir=str(pd),
            project_dir_exists=pd.exists(),
            error=f"claude --version failed: {e}",
        )

    # Authoritative auth check: `claude auth status` emits JSON with a
    # `loggedIn` boolean (and the account email when signed in). It reads
    # whatever CLAUDE_CONFIG_DIR points at, which we inherit from the env.
    authenticated = False
    email: str | None = None
    auth_error: str | None = None
    try:
        proc = subprocess.run(
            [cli, "auth", "status"], capture_output=True, text=True, timeout=15
        )
        payload = json.loads(proc.stdout.strip() or "{}")
        authenticated = bool(payload.get("loggedIn"))
        email = payload.get("email")
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as e:
        auth_error = f"could not read auth status: {e}"

    return ClaudeStatus(
        cli_installed=True,
        cli_version=version,
        authenticated=authenticated,
        project_dir=str(pd),
        project_dir_exists=pd.exists(),
        email=email,
        error=auth_error,
    )


# --- MCP tools --------------------------------------------------------------


def _path_within(target: Path, root: Path) -> Path | None:
    """Resolve ``target`` against ``root`` and return it iff it stays inside."""
    try:
        resolved = (root / target).resolve() if not target.is_absolute() else target.resolve()
    except (OSError, ValueError):
        return None
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


@tool(
    "list_displays",
    "List every Waveshare display the visualizer supports. Returns id, name, "
    "family, resolution, mode, palette, shape and capabilities for each.",
    {},
)
async def _list_displays(_: dict[str, Any]) -> dict[str, Any]:
    items = []
    for d in catalog.all_displays():
        items.append(
            {
                "id": d["id"],
                "name": d["name"],
                "family": d["family"],
                "resolution": d["resolution"],
                "mode": d["mode"],
                "palette": d.get("palette"),
                "shape": d.get("shape", "rect"),
                "char_grid": d.get("char_grid"),
                "capabilities": catalog.capabilities(d),
            }
        )
    return {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}


@tool(
    "get_display",
    "Get detailed catalog info for a single display by id (call list_displays first if you don't know the id).",
    {
        "type": "object",
        "properties": {
            "display_id": {"type": "string", "description": "e.g. 'epd4in2_v2'"}
        },
        "required": ["display_id"],
    },
)
async def _get_display(args: dict[str, Any]) -> dict[str, Any]:
    d = catalog.get_display(args["display_id"])
    if not d:
        return {"content": [{"type": "text", "text": f"unknown display: {args['display_id']}"}], "isError": True}
    payload = {**d, "capabilities": catalog.capabilities(d)}
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]}


@tool(
    "render_on_display",
    "Execute Python code on the simulated display and report whether it rendered. "
    "The code MUST import `from waveshare_sim import display` and call display.show(img) "
    "with a PIL image whose mode matches display.mode. Returns success, timing, stdout, "
    "stderr, and a note if the render produced an image the user can now see in the browser.",
    {
        "type": "object",
        "properties": {
            "display_id": {"type": "string"},
            "code": {"type": "string", "description": "full Python program"},
        },
        "required": ["display_id", "code"],
    },
)
async def _render_on_display(args: dict[str, Any]) -> dict[str, Any]:
    d = catalog.get_display(args["display_id"])
    if not d:
        return {"content": [{"type": "text", "text": f"unknown display: {args['display_id']}"}], "isError": True}
    result = runner.run_user_code(
        args["code"],
        width=d["resolution"][0],
        height=d["resolution"][1],
        mode=d["mode"],
        palette=d.get("palette"),
        shape=d.get("shape", "rect"),
        family=d.get("family", "lcd"),
        char_grid=d.get("char_grid"),
        api=d.get("api"),
        driver=d.get("driver"),
    )
    text = json.dumps(
        {
            "ok": result.ok,
            "duration_ms": result.duration_ms,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "error_summary": result.friendly,
            "rendered_image": bool(result.image_base64),
        },
        indent=2,
    )
    return {"content": [{"type": "text", "text": text}], "isError": not result.ok}


@tool(
    "list_project_files",
    "List files (recursively, up to 500 entries) inside the configured project directory. "
    "Paths returned are relative to the project root.",
    {
        "type": "object",
        "properties": {
            "subdir": {
                "type": "string",
                "description": "optional relative subdirectory to scope the listing",
                "default": "",
            }
        },
    },
)
async def _list_project_files(args: dict[str, Any]) -> dict[str, Any]:
    root = project_dir()
    if not root.exists():
        return {
            "content": [{"type": "text", "text": f"project dir {root} does not exist. Set CLAUDE_PROJECT_DIR."}],
            "isError": True,
        }
    subdir = args.get("subdir", "") or ""
    scope = _path_within(Path(subdir), root) if subdir else root
    if scope is None or not scope.is_dir():
        return {
            "content": [{"type": "text", "text": f"subdir {subdir!r} is outside the project root or not a directory"}],
            "isError": True,
        }
    out: list[str] = []
    for p in _iter_project_files(scope, root, limit=20000, include_binary=True):
        if len(out) >= 500:
            out.append("… (truncated at 500 entries — use search_project or a subdir)")
            break
        out.append(str(p.relative_to(root)))
    return {"content": [{"type": "text", "text": "\n".join(out) or "(empty)"}]}


MAX_FILE_BYTES = 8_000_000   # refuse to load anything bigger than this into memory
MAX_RETURN_BYTES = 90_000    # cap the text we hand back in one tool call

# Directories and file types that are noise for code exploration — pruned from
# listing/search so top-level source isn't starved behind big data/vcs trees.
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
              ".mypy_cache", ".pytest_cache", ".ruff_cache", "backup"}
_BINARY_EXT = {".bmp", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
               ".ttf", ".otf", ".woff", ".woff2", ".db", ".sqlite", ".sqlite3",
               ".zip", ".gz", ".tar", ".xz", ".pyc", ".so", ".o", ".bin",
               ".pdf", ".mp3", ".wav", ".mp4", ".mov", ".jpg", ".class"}


def _iter_project_files(scope: Path, root: Path, limit: int, include_binary: bool = False):
    """Yield files under ``scope`` (relative-prunable), skipping heavy VCS/cache
    trees, bounded by ``limit`` files walked. Walk order keeps top-level source
    ahead of deep data directories.

    ``include_binary`` controls whether non-text assets (fonts, images, …) are
    yielded: listings include them so the agent can discover assets it may
    reference by path; content search skips them (nothing to grep)."""
    walked = 0
    for p in scope.rglob("*"):
        if walked >= limit:
            return
        rel_parts = p.relative_to(root).parts
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if not p.is_file():
            continue
        if not include_binary and p.suffix.lower() in _BINARY_EXT:
            continue
        walked += 1
        yield p


@tool(
    "read_project_file",
    "Read a UTF-8 text file inside the configured project directory. Paths must "
    "be relative to the project root or absolute inside it. Large files can be "
    "paged with start_line/max_lines — the response header reports the total "
    "line count so you can request later ranges. Output is line-numbered.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "description": "1-based first line to return", "default": 1},
            "max_lines": {"type": "integer", "description": "how many lines to return (default 400)", "default": 400},
        },
        "required": ["path"],
    },
)
async def _read_project_file(args: dict[str, Any]) -> dict[str, Any]:
    root = project_dir()
    if not root.exists():
        return {
            "content": [{"type": "text", "text": f"project dir {root} does not exist. Set CLAUDE_PROJECT_DIR."}],
            "isError": True,
        }
    target = _path_within(Path(args["path"]), root)
    if target is None:
        return {"content": [{"type": "text", "text": f"path {args['path']!r} is outside the project root"}], "isError": True}
    if not target.is_file():
        return {"content": [{"type": "text", "text": f"not a file: {target}"}], "isError": True}
    try:
        size = target.stat().st_size
        if size > MAX_FILE_BYTES:
            return {"content": [{"type": "text", "text": f"file too large to open: {size} bytes (limit {MAX_FILE_BYTES})"}], "isError": True}
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"content": [{"type": "text", "text": "file is not UTF-8 text"}], "isError": True}
    except OSError as e:
        return {"content": [{"type": "text", "text": f"read failed: {e}"}], "isError": True}

    lines = text.splitlines()
    total = len(lines)
    start = max(1, int(args.get("start_line", 1) or 1))
    count = max(1, int(args.get("max_lines", 400) or 400))
    chunk = lines[start - 1 : start - 1 + count]
    end = start - 1 + len(chunk)

    body_lines = [f"{start + i:>6}\t{ln}" for i, ln in enumerate(chunk)]
    body = "\n".join(body_lines)
    truncated_bytes = False
    if len(body.encode("utf-8")) > MAX_RETURN_BYTES:
        body = body.encode("utf-8")[:MAX_RETURN_BYTES].decode("utf-8", "ignore")
        truncated_bytes = True

    header = f"# {target.relative_to(root)} — lines {start}-{end} of {total} ({size} bytes)"
    if end < total:
        header += f"; request start_line={end + 1} for more"
    if truncated_bytes:
        header += " [output byte-capped — narrow the range]"
    return {"content": [{"type": "text", "text": header + "\n" + body}]}


@tool(
    "search_project",
    "Case-insensitive substring search across text files in the configured "
    "project directory (like grep). Returns 'relpath:lineno: line' matches so "
    "you can locate code in large files before reading a range.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "substring to search for"},
            "subdir": {"type": "string", "description": "optional relative subdirectory to scope the search", "default": ""},
            "max_results": {"type": "integer", "default": 100},
        },
        "required": ["query"],
    },
)
async def _search_project(args: dict[str, Any]) -> dict[str, Any]:
    root = project_dir()
    if not root.exists():
        return {"content": [{"type": "text", "text": f"project dir {root} does not exist. Set CLAUDE_PROJECT_DIR."}], "isError": True}
    query = (args.get("query") or "").lower()
    if not query:
        return {"content": [{"type": "text", "text": "empty query"}], "isError": True}
    subdir = args.get("subdir", "") or ""
    scope = _path_within(Path(subdir), root) if subdir else root
    if scope is None or not scope.is_dir():
        return {"content": [{"type": "text", "text": f"subdir {subdir!r} is outside the project root or not a directory"}], "isError": True}
    limit = max(1, int(args.get("max_results", 100) or 100))

    import time
    deadline = time.monotonic() + 5.0  # keep the tool responsive on big trees
    hits: list[str] = []
    stopped_early = False
    for p in _iter_project_files(scope, root, limit=20000):
        if len(hits) >= limit:
            hits.append("… (more matches — narrow the query or scope)")
            break
        if time.monotonic() > deadline:
            stopped_early = True
            break
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            with p.open(encoding="utf-8", errors="strict") as fh:
                for n, line in enumerate(fh, 1):
                    if query in line.lower():
                        hits.append(f"{p.relative_to(root)}:{n}: {line.strip()[:200]}")
                        if len(hits) >= limit:
                            break
        except (UnicodeDecodeError, OSError):
            continue
    if stopped_early:
        hits.append("… (search time budget reached — narrow the query or pass a subdir)")
    return {"content": [{"type": "text", "text": "\n".join(hits) or "(no matches)"}]}


TOOLS = [
    _list_displays,
    _get_display,
    _render_on_display,
    _list_project_files,
    _read_project_file,
    _search_project,
]

MCP_SERVER = create_sdk_mcp_server(name="waveshare", version="0.1.0", tools=TOOLS)

# Toolnames that Claude is allowed to call. Anything not on this list is refused,
# including all built-in Read/Write/Bash tools.
ALLOWED_TOOLS = [f"mcp__waveshare__{t.name}" for t in TOOLS]


SYSTEM_PROMPT = """You are the Display Visualizer assistant. You help the user write \
Python code that renders on simulated Waveshare e-paper, LCD and OLED displays.

Ground rules:
1. Before writing code, call `list_displays` (or `get_display` if the user named one) to \
learn the exact resolution, mode ('1'/'L'/'RGB'/'P'), palette and shape ('rect'/'round') of the target panel.
2. Never hardcode colours the panel doesn't support. On mono e-paper use `display.fg`/`display.bg` \
only. On palette displays use entries from `display.palette`. On RGB displays you can use any colour.
3. Every program must:
    - `from waveshare_sim import display`
    - build a `PIL.Image` with mode matching `display.mode`
    - call `display.show(img)` exactly once
   Never call `display.show` in a loop — real e-paper takes seconds per refresh anyway, and the \
sim only surfaces the last frame.
   For a character LCD (family 'char', e.g. LCD1602) there is no framebuffer to draw into: it has a \
`display.char_grid` of [columns, rows] and you render text with `display.text_lines(["line 1", "line 2"])`, \
which draws each character as a 5x7 dot matrix. Clip/pad each line to the column count. `\\xff` is the \
solid-block glyph (handy for bar meters).
4. You can call `render_on_display` to actually run your code and see if it succeeded. If it \
fails, read the stderr and fix it. Do NOT loop more than 3 render attempts without pausing to \
report back to the user.
5. When the user references a project ("test the Ragnar display", "adapt my code"), explore it with \
`list_project_files`, `search_project` (grep to locate the relevant code), and `read_project_file` \
(page big files with start_line/max_lines — the header tells you the total line count). These tools \
are scoped to the configured project directory; nothing outside it is accessible. Real device scripts \
usually import a hardware driver (e.g. `waveshare_epd.epdXinY`, `gc9a01`) and call `epd.display(epd.getbuffer(img))`. \
Don't try to run that unchanged — extract the PIL drawing that builds the frame and port it to the sim: \
`from waveshare_sim import display`, build an image at `display.width`x`display.height` in `display.mode`, \
then `display.show(img)`. You may read the project's own assets (fonts, images) by absolute path inside \
the project dir when rendering, so the result matches the real device.
6. Reply in short prose plus one final Python code block that the user can paste into their editor. \
Do not paste huge files back at the user."""


# --- Streaming chat ---------------------------------------------------------


def _message_to_event(msg: Any) -> dict[str, Any] | None:
    """Convert an SDK message into a JSON-serializable event for the frontend."""
    if isinstance(msg, AssistantMessage):
        blocks: list[dict[str, Any]] = []
        for block in msg.content:
            if isinstance(block, TextBlock):
                blocks.append({"type": "text", "text": block.text})
            elif isinstance(block, ToolUseBlock):
                blocks.append({"type": "tool_use", "name": block.name, "input": block.input})
            elif isinstance(block, ThinkingBlock):
                # Skip thinking blocks — they're internal.
                pass
        if blocks:
            return {"type": "assistant", "blocks": blocks}
        return None
    if isinstance(msg, UserMessage):
        # Tool results echoed back — surface them so the UI can show what a tool returned.
        return None
    if isinstance(msg, SystemMessage):
        return None
    if isinstance(msg, ResultMessage):
        result_text = getattr(msg, "result", None)
        ev = {
            "type": "result",
            "subtype": msg.subtype,
            "duration_ms": msg.duration_ms,
            "total_cost_usd": msg.total_cost_usd,
            "num_turns": msg.num_turns,
            "is_error": msg.is_error,
        }
        if msg.is_error and result_text:
            ev["message"] = _friendly_error(str(result_text))
            ev["auth"] = _is_auth_error(str(result_text))
        return ev
    return None


async def stream_chat(
    prompt: str,
    *,
    selected_display_id: str | None,
    editor_code: str | None,
    max_turns: int = 40,
) -> AsyncIterator[dict[str, Any]]:
    """Yield JSON events describing a single Claude turn."""
    context_prefix = ""
    if selected_display_id:
        d = catalog.get_display(selected_display_id)
        if d:
            context_prefix += (
                f"[The user has selected display `{selected_display_id}` "
                f"({d['name']}, {d['resolution'][0]}x{d['resolution'][1]}, "
                f"mode={d['mode']}, family={d['family']}). Prefer this display "
                f"unless the user asks for a different one.]\n\n"
            )
    if editor_code and editor_code.strip():
        context_prefix += "[Current editor contents:]\n```python\n" + editor_code + "\n```\n\n"

    pd = project_dir()
    add_dirs: list[str | Path] = []
    if pd.exists():
        add_dirs.append(pd)

    options = ClaudeAgentOptions(
        mcp_servers={"waveshare": MCP_SERVER},
        allowed_tools=ALLOWED_TOOLS,
        disallowed_tools=["Bash", "Write", "Edit", "Read", "Glob", "Grep", "WebFetch", "WebSearch"],
        system_prompt=SYSTEM_PROMPT,
        max_turns=max_turns,
        permission_mode="bypassPermissions",  # our sandbox lives in the tools themselves
        cwd=str(pd) if pd.exists() else None,
        add_dirs=add_dirs,
    )

    try:
        async for msg in query(prompt=context_prefix + prompt, options=options):
            event = _message_to_event(msg)
            if event is not None:
                yield event
    except Exception as e:
        yield {"type": "error", "message": _friendly_error(str(e)), "auth": _is_auth_error(str(e))}


def _is_auth_error(text: str) -> bool:
    low = text.lower()
    return (
        "401" in low
        or "revoked" in low
        or "unauthorized" in low
        or "authentication_error" in low
        or ("oauth" in low and "token" in low)
    )


def _friendly_error(text: str) -> str:
    """Turn raw SDK/CLI failure strings into something a user can act on."""
    low = text.lower()
    if _is_auth_error(text):
        return (
            "Your Claude session is no longer valid (the sign-in token was "
            "revoked or expired). Click “log out”, then “Sign in to "
            "Claude” to reconnect. Original error: " + text
        )
    if "maximum number of turns" in low:
        return (
            "The assistant hit its step limit before finishing. Try a more "
            "specific request (e.g. name the file to read), or ask it to "
            "continue. Original error: " + text
        )
    return text
