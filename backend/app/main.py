"""FastAPI application factory."""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api.routes import health, media, system
from .core.config import Settings, get_settings
from .core.errors import register_exception_handlers
from .core.logging import configure_logging
from .core.security import LocalOnlyMiddleware
from .services.source_service import SourceService, build_source_service
from .services.file_service import ensure_runtime_directories, validate_output_directory

logger = logging.getLogger("app.main")
TOKEN_PLACEHOLDER = "__SESSION_TOKEN__"


def create_app(settings: Settings | None = None, source_service: SourceService | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    session_token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        output = validate_output_directory(settings.output_directory)
        ensure_runtime_directories(output, settings.temp_directory, settings.database_path)
        logger.info(
            "application started",
            extra={"operation": "startup", "status": f"{settings.app_env} {settings.host}:{settings.port}"},
        )
        yield
        logger.info("application stopped", extra={"operation": "shutdown", "status": "ok"})

    # Interactive API docs are disabled: they pull scripts from a CDN, which our CSP forbids.
    app = FastAPI(
        title="Personal Media",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.session_token = session_token
    app.state.source_service = source_service or build_source_service(settings)

    app.add_middleware(
        LocalOnlyMiddleware,
        port=settings.port,
        session_token=session_token,
        extra_origins=settings.cors_origins,
    )
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(system.router)
    app.include_router(media.router)

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    def index() -> HTMLResponse:
        page = (settings.frontend_directory / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(page.replace(TOKEN_PLACEHOLDER, session_token), headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=settings.frontend_directory), name="static")
    return app


app = create_app()
