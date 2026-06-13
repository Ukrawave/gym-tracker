"""FastAPI application entry point.

- Mounts the static SPA at /
- Mounts the host's exercise-gif directory at /media (read-only static files)
- Registers all /api/* routers
- Calls init_schema() on startup so a fresh clone boots cleanly
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

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
        # Storage hygiene: sweep out sessions that never logged any weights.
        # See app/cleanup.py for the rule. Boot-time so the invariant holds
        # across restarts, container rebuilds, and DB volume swaps.
        from app.cleanup import cleanup_empty_sessions
        cleanup_empty_sessions()

    # ---- API routers ----
    app.include_router(exercises_routes.router, prefix="/api", tags=["exercises"])
    app.include_router(sessions_routes.router, prefix="/api", tags=["sessions"])
    app.include_router(sets_routes.router, prefix="/api", tags=["sets"])
    app.include_router(progress_routes.router, prefix="/api", tags=["progress"])
    app.include_router(records_routes.router, prefix="/api", tags=["records"])

    @app.get("/api/health", tags=["meta"])
    def health() -> Response:
        """Liveness + DB-reachable check.

        The frontend HUD polls this every 15s. If the DB blows up we want the
        LED to turn red, not stay green — so actually round-trip a query.
        """
        import json as _json
        from app.db import db_conn  # local import to avoid cold-import cycles

        try:
            with db_conn() as conn:
                ex_count = conn.execute(
                    "SELECT COUNT(*) AS c FROM exercises"
                ).fetchone()["c"]
            body = {
                "status": "ok",
                "service": "gym-tracker",
                "db": "ok",
                "exercises": int(ex_count),
            }
            return Response(
                content=_json.dumps(body),
                status_code=200,
                media_type="application/json",
            )
        except Exception as exc:
            body = {
                "status": "degraded",
                "service": "gym-tracker",
                "db": "error",
                "detail": str(exc),
            }
            return Response(
                content=_json.dumps(body),
                status_code=503,
                media_type="application/json",
            )

    # ---- Media (host-mounted exercise-gifs) ----
    # NOTE: a misconfigured GYM_MEDIA_PATH (typo, unquoted path with spaces in
    # a systemd unit, missing bind mount) silently 404s every exercise image
    # and is invisible from the frontend. Log loudly at startup so it surfaces
    # in `journalctl -u gym-tracker` instead of dying quietly in the browser
    # console.
    if MEDIA_PATH.exists() and MEDIA_PATH.is_dir():
        app.mount("/media", StaticFiles(directory=str(MEDIA_PATH)), name="media")
        print(f"[media] mounted /media -> {MEDIA_PATH}", flush=True)
    else:
        print(
            f"[media] WARNING: GYM_MEDIA_PATH does not exist or is not a "
            f"directory: {MEDIA_PATH!s}. All /media/* requests will 404. "
            f"Check the env var (quote paths containing spaces in systemd "
            f"units).",
            flush=True,
        )

        @app.get("/media/{file_path:path}", tags=["media"])
        def media_missing(file_path: str) -> Response:
            """Graceful 404 when GYM_MEDIA_PATH is not mounted."""
            return Response(
                status_code=404,
                content=(
                    f"media path not mounted: {file_path}\n"
                    f"GYM_MEDIA_PATH={MEDIA_PATH!s} does not exist."
                ),
            )

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
