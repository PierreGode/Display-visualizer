"""FastAPI app: catalog, examples, run, bezel assets, and static SPA."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import bezel, catalog, runner, update
from .examples import EXAMPLES, device_snippet

BACKEND_DIR = Path(__file__).resolve().parent
PHOTOS_DIR = BACKEND_DIR / "assets" / "photos"
FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"

app = FastAPI(title="Display Visualizer", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_html(request, call_next):
    """Vite hashes the JS/CSS filenames so those are safe to cache long-term,
    but index.html references those hashed names and MUST be re-fetched after
    an update — otherwise browsers keep serving a stale index that points at
    deleted asset files. Force no-cache on HTML responses."""
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if ct.startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


class RunRequest(BaseModel):
    display_id: str = Field(..., description="ID from /api/displays")
    code: str = Field(..., description="Python source to execute")


def _augment(entry: dict) -> dict:
    """Add computed fields the frontend needs."""
    cw, ch = bezel.canvas_size(entry, PHOTOS_DIR)
    has_photo = bezel.photo_path(entry["id"], PHOTOS_DIR) is not None
    return {
        **entry,
        "canvas": [cw, ch],
        "has_photo": has_photo,
        "capabilities": catalog.capabilities(entry),
        "device_snippet": device_snippet(entry),
    }


@app.get("/api/displays")
def list_displays() -> list[dict]:
    return [_augment(e) for e in catalog.all_displays()]


@app.get("/api/displays/{display_id}")
def get_display(display_id: str) -> dict:
    entry = catalog.get_display(display_id)
    if not entry:
        raise HTTPException(status_code=404, detail="unknown display")
    return _augment(entry)


@app.get("/api/displays/{display_id}/bezel")
def get_bezel(display_id: str):
    entry = catalog.get_display(display_id)
    if not entry:
        raise HTTPException(status_code=404, detail="unknown display")

    photo = bezel.photo_path(display_id, PHOTOS_DIR)
    if photo is not None:
        media = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(photo.suffix.lower(), "application/octet-stream")
        return FileResponse(photo, media_type=media)

    svg = bezel.generate_svg(entry)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/examples")
def list_examples() -> list[dict]:
    return [
        {
            "id": ex.id,
            "name": ex.name,
            "family": ex.family,
            "code": ex.code,
            "min_colors": ex.min_colors,
            "shape": ex.shape,
        }
        for ex in EXAMPLES
    ]


@app.post("/api/run")
def run(req: RunRequest) -> JSONResponse:
    entry = catalog.get_display(req.display_id)
    if not entry:
        raise HTTPException(status_code=400, detail="unknown display")
    result = runner.run_user_code(
        req.code,
        width=entry["resolution"][0],
        height=entry["resolution"][1],
        mode=entry["mode"],
        palette=entry.get("palette"),
        shape=entry.get("shape", "rect"),
        family=entry.get("family", "lcd"),
        char_grid=entry.get("char_grid"),
        api=entry.get("api"),
        driver=entry.get("driver"),
    )
    return JSONResponse(
        {
            "ok": result.ok,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "friendly": result.friendly,
            "image_base64": result.image_base64,
            "duration_ms": result.duration_ms,
        }
    )


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


# --- Self-update -----------------------------------------------------------

@app.get("/api/update/status")
def update_status() -> dict:
    return asdict(update.status())


@app.post("/api/update/check")
def update_check() -> dict:
    """Force a fresh `git fetch` and return the new status."""
    return asdict(update.status(force_fetch=True))


@app.post("/api/update/pull")
def update_pull() -> dict:
    return update.trigger_update()


# --- Claude Code integration -----------------------------------------------

class ChatRequest(BaseModel):
    prompt: str
    display_id: str | None = None
    editor_code: str | None = None


class LoginSubmit(BaseModel):
    session_id: str = Field(..., description="id from /api/claude/login/start")
    code: str = Field(..., description="authorization code pasted from the browser")


class LoginCancel(BaseModel):
    session_id: str


class ProjectDirRequest(BaseModel):
    path: str = Field(..., description="absolute path to a directory the service can read")


@app.get("/api/claude/status")
def claude_status() -> dict:
    # Imported lazily so a missing claude-agent-sdk doesn't break the whole app.
    try:
        from . import claude_agent
    except ImportError as e:
        return {
            "cli_installed": False,
            "authenticated": False,
            "error": f"claude-agent-sdk not installed: {e}",
        }
    return asdict(claude_agent.check_status())


@app.get("/api/claude/project")
def claude_project() -> dict:
    from . import claude_agent

    pd = claude_agent.project_dir()
    return {"project_dir": str(pd), "exists": pd.exists()}


@app.post("/api/claude/project")
def claude_set_project(req: ProjectDirRequest) -> dict:
    from . import claude_agent

    return claude_agent.set_project_dir(req.path)


@app.post("/api/claude/login/start")
def claude_login_start() -> dict:
    """Kick off the OAuth flow: returns a URL for the user to authorize, plus a
    session id to complete the login with the code they get back."""
    from . import claude_login

    return claude_login.start()


@app.post("/api/claude/login/submit")
def claude_login_submit(req: LoginSubmit) -> dict:
    from . import claude_login

    return claude_login.submit(req.session_id, req.code)


@app.post("/api/claude/login/cancel")
def claude_login_cancel(req: LoginCancel) -> dict:
    from . import claude_login

    return claude_login.cancel(req.session_id)


@app.post("/api/claude/logout")
def claude_logout() -> dict:
    import shutil
    import subprocess

    cli = shutil.which("claude")
    if not cli:
        raise HTTPException(status_code=503, detail="claude CLI not found")
    try:
        proc = subprocess.run(
            [cli, "auth", "logout"], capture_output=True, text=True, timeout=15
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        raise HTTPException(status_code=500, detail=f"logout failed: {e}")
    return {"ok": proc.returncode == 0, "output": (proc.stdout + proc.stderr).strip()[-400:]}


@app.post("/api/claude/chat")
async def claude_chat(req: ChatRequest) -> StreamingResponse:
    try:
        from . import claude_agent
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"claude-agent-sdk not installed: {e}")

    async def sse() -> AsyncIterator[bytes]:
        # Server-Sent Events. The agent can spend 10-30s "thinking" between tool
        # calls with no events to emit; over a VPN or mobile link an idle socket
        # gets reaped ("TypeError: Load failed" on the client). Emit a comment
        # heartbeat every few seconds so bytes keep flowing and the connection
        # stays open. Comment lines (":" prefix) are ignored by the SSE parser.
        agen = claude_agent.stream_chat(
            req.prompt,
            selected_display_id=req.display_id,
            editor_code=req.editor_code,
        ).__aiter__()
        try:
            while True:
                nxt = asyncio.ensure_future(agen.__anext__())
                while True:
                    try:
                        event = await asyncio.wait_for(asyncio.shield(nxt), timeout=5)
                        break
                    except asyncio.TimeoutError:
                        yield b": keep-alive\n\n"
                yield f"data: {json.dumps(event)}\n\n".encode("utf-8")
        except StopAsyncIteration:
            pass
        yield b"data: {\"type\":\"done\"}\n\n"

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # let nginx pass bytes through immediately
        },
    )


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="spa")
