"""FastAPI application factory."""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api.routes import health, history, jobs, media, settings as settings_routes, system
from .core.config import Settings, get_settings
from .core.errors import register_exception_handlers
from .core.logging import configure_logging
from .core.security import LocalOnlyMiddleware
from .services.download_service import DownloadService
from .services.history_service import HistoryService
from .services.job_service import AnalysisCache, JobService
from .services.os_open import open_in_os
from .services.settings_service import SettingsService
from .services.source_service import SourceService, build_source_service
from .services.file_service import cleanup_abandoned_temp, ensure_runtime_directories, validate_output_directory

logger = logging.getLogger("app.main")
TOKEN_PLACEHOLDER = "__SESSION_TOKEN__"


def create_app(
    settings: Settings | None = None,
    source_service: SourceService | None = None,
    job_service: JobService | None = None,
    history_service: HistoryService | None = None,
    settings_service: SettingsService | None = None,
    opener=open_in_os,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    session_token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        output = validate_output_directory(settings.output_directory)
        ensure_runtime_directories(output, settings.temp_directory, settings.database_path)
        removed = cleanup_abandoned_temp(settings.temp_directory)
        if removed:
            logger.info("removed abandoned temp folders", extra={"operation": "startup", "status": f"{removed} removed"})
        app.state.job_service.start()
        logger.info(
            "application started",
            extra={"operation": "startup", "status": f"{settings.app_env} {settings.host}:{settings.port}"},
        )
        yield
        app.state.job_service.shutdown()  # cancels running work so no child process outlives the server
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
    app.state.analysis_cache = AnalysisCache()
    app.state.history_service = history_service or HistoryService(settings.database_path)
    app.state.settings_service = settings_service or SettingsService(settings.database_path, settings)
    app.state.job_service = job_service or JobService(
        settings,
        app.state.source_service,
        DownloadService(settings),
        app.state.analysis_cache,
        history=app.state.history_service,
    )
    from core.engine import DownloaderEngine

    app.state.engine = DownloaderEngine(
        source_service=app.state.source_service,
        job_service=app.state.job_service,
        history_service=app.state.history_service,
        settings_service=app.state.settings_service,
    )
    app.state.opener = opener


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
    app.include_router(jobs.router)
    app.include_router(history.router)
    app.include_router(settings_routes.router)

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    def index() -> HTMLResponse:
        page = (settings.frontend_directory / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(page.replace(TOKEN_PLACEHOLDER, session_token), headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=settings.frontend_directory), name="static")
    return app


app = create_app()
