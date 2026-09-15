"""FishBot web panel ASGI entry.

Wraps the absorbed ros2-mobile-panel backend (backend.app:app) and mounts
the prebuilt PWA assets in frontend-dist/ on "/", so a single uvicorn
process serves both the API/WebSocket and the panel UI without nginx.
Route order guarantees /api and /ws match before the static mount.
"""

from __future__ import annotations

from pathlib import Path

from backend.app import app

_DIST = Path(__file__).resolve().parent / "frontend-dist"

if _DIST.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_DIST, html=True), name="panel")
