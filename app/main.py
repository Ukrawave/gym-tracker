"""FastAPI application entry point.

- Mounts the static SPA at /
- Mounts the host's exercise-gif directory at /media (read-only static files)
- Registers all /api/* routers
- Calls init_schema() on startup so a fresh clone boots cleanly
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.db import init_schema
from app.routes import exercises as exercises_routes
from app.routes import progress as progress_routes
from app.routes import records as records_routes
from app.routes import sessions as sessions_routes
from app.routes import sets as sets_routes

APP_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = APP_ROOT / "static"
DEFAULT_MEDIA_PATH = "/home/hermes/Obsidian Vault/Gym/exercise-gifs"
MEDIA_PATH = Path(os.environ.get("GYM_MEDIA_PATH", DEFAULT_MEDIA_PATH))


def create_app() -> FastAPI:
    app = FastAPI(
        title="Gym Tracker — Mission Control",
        version="1.0.0",
        description="Single-user homelab gym-tracking API with NASA HUD frontend.",
    )

    # CORS open — single-user local app; no auth surface to protect.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def _startup() -> None:
        init_schema()

    # ---- API routers ----
    app.include_router(exercises_routes.router, prefix="/api", tags=["exercises"])
    app.include_router(sessions_routes.router, prefix="/api", tags=["sessions"])
    app.include_router(sets_routes.router, prefix="/api", tags=["sets"])
    app.include_router(progress_routes.router, prefix="/api", tags=["progress"])
    app.include_router(records_routes.router, prefix="/api", tags=["records"])

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "gym-tracker"}

    # ---- Media (host-mounted exercise-gifs) ----
    if MEDIA_PATH.exists() and MEDIA_PATH.is_dir():
        app.mount("/media", StaticFiles(directory=str(MEDIA_PATH)), name="media")
    else:
        @app.get("/media/{file_path:path}", tags=["media"])
        def media_missing(file_path: str) -> Response:
            """Graceful 404 when GYM_MEDIA_PATH is not mounted."""
            return Response(status_code=404, content=f"media path not mounted: {file_path}")

    # ---- Static SPA ----
    if STATIC_DIR.exists():
        # Per-file routes for top-level HTML pages so they resolve at clean URLs.
        @app.get("/", include_in_schema=False)
        def root() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

        @app.get("/exercises.html", include_in_schema=False)
        def exercises_page() -> FileResponse:
            return FileResponse(STATIC_DIR / "exercises.html")

        @app.get("/logger.html", include_in_schema=False)
        def logger_page() -> FileResponse:
            return FileResponse(STATIC_DIR / "logger.html")

        @app.get("/progress.html", include_in_schema=False)
        def progress_page() -> FileResponse:
            return FileResponse(STATIC_DIR / "progress.html")

        # Mount full static dir for css/js/assets.
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


app = create_app()
