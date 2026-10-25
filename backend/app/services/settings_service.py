"""User settings persistence and management."""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from ..core.config import Settings, _DOMAIN
from ..core.errors import AppError, ErrorCode
from .file_service import PathSafetyError, validate_output_directory

logger = logging.getLogger("app.settings")


class SettingsService:
    def __init__(self, db_path: Path, settings: Settings) -> None:
        self._db_path = Path(db_path)
        self._settings = settings
        self._lock = threading.Lock()
        self._init_db()
        self._load_persisted()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _load_persisted(self) -> None:
        with self._lock, self._get_connection() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = 'output_directory'").fetchone()
            if row:
                try:
                    resolved = validate_output_directory(row["value"])
                    resolved.mkdir(parents=True, exist_ok=True)
                    object.__setattr__(self._settings, "output_directory", resolved)
                except (PathSafetyError, OSError) as exc:
                    logger.warning("invalid persisted output directory, ignoring: %s", exc)

            row_domains = conn.execute("SELECT value FROM app_settings WHERE key = 'allowed_source_domains'").fetchone()
            if row_domains:
                loaded = {d.strip().lower().lstrip(".") for d in row_domains["value"].split(",") if d.strip()}
                valid = {d for d in loaded if _DOMAIN.match(d)}
                if valid:
                    object.__setattr__(self._settings, "source_domains", frozenset(valid))

    def get_output_directory(self) -> Path:
        return self._settings.output_directory

    def update_output_directory(self, raw_path: str) -> Path:
        if not raw_path or not raw_path.strip():
            raise AppError(ErrorCode.INVALID_REQUEST, "Output directory cannot be empty.")
        try:
            resolved = validate_output_directory(raw_path.strip())
            resolved.mkdir(parents=True, exist_ok=True)
        except PathSafetyError as exc:
            raise AppError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
        except OSError as exc:
            raise AppError(ErrorCode.INVALID_REQUEST, f"Could not create output directory: {exc}") from exc

        with self._lock, self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('output_directory', ?)",
                (str(resolved),),
            )
            conn.commit()

        object.__setattr__(self._settings, "output_directory", resolved)
        logger.info("updated output directory", extra={"operation": "settings", "path": str(resolved)})
        return resolved

    def update_allowed_domains(self, domains: list[str]) -> frozenset[str]:
        cleaned = set()
        for d in domains:
            d_clean = d.strip().lower().lstrip(".")
            if not d_clean:
                continue
            if not _DOMAIN.match(d_clean):
                raise AppError(ErrorCode.INVALID_REQUEST, f"Invalid domain: {d}")
            cleaned.add(d_clean)
        if not cleaned:
            raise AppError(ErrorCode.INVALID_REQUEST, "At least one allowed domain is required.")

        as_set = frozenset(cleaned)
        with self._lock, self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('allowed_source_domains', ?)",
                (",".join(sorted(as_set)),),
            )
            conn.commit()

        object.__setattr__(self._settings, "source_domains", as_set)
        logger.info("updated allowed domains", extra={"operation": "settings", "domains": list(sorted(as_set))})
        return as_set

    def get_all(self) -> dict:
        return {
            "output_directory": str(self._settings.output_directory),
            "allowed_source_domains": sorted(self._settings.source_domains),
            "max_parallel_jobs": self._settings.max_parallel_jobs,
            "max_download_gb": int(self._settings.max_download_bytes // (1024**3)),
            "log_level": self._settings.log_level,
        }
