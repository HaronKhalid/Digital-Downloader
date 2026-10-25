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


POPULAR_DOMAINS = (
    "youtube.com,youtu.be,instagram.com,instagr.am,facebook.com,fb.watch,fb.com,"
    "tiktok.com,twitter.com,x.com,reddit.com,pinterest.com,pin.it,vimeo.com,"
    "soundcloud.com,twitch.tv,threads.net,linkedin.com,dailymotion.com,bilibili.com,"
    "archive.org,streamable.com,bandcamp.com,tumblr.com,snapchat.com,bsky.app"
)


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
                except (PathSafetyError, OSError, ValueError) as exc:
                    logger.warning("invalid persisted output directory, ignoring: %s", exc)

            row_domains = conn.execute("SELECT value FROM app_settings WHERE key = 'allowed_source_domains'").fetchone()
            if row_domains:
                loaded = {d.strip().lower().lstrip(".") for d in row_domains["value"].split(",") if d.strip()}
                valid = {d for d in loaded if d == "*" or d == "all" or _DOMAIN.match(d)}
                if valid:
                    object.__setattr__(self._settings, "source_domains", frozenset(valid))

    def get_output_directory(self) -> Path:
        return self._settings.output_directory

    def update_output_directory(self, raw_path: str) -> Path:
        if not raw_path or not raw_path.strip():
            raise AppError(ErrorCode.INVALID_REQUEST, "Output directory cannot be empty.")
        if "\x00" in raw_path:
            raise AppError(ErrorCode.INVALID_REQUEST, "Null bytes are not permitted in paths.")
        p = raw_path.strip()
        try:
            if p.startswith("~"):
                p = str(Path(p).expanduser())
            elif p.lower().startswith(("downloads\\", "downloads/")):
                p = str((Path.home() / Path(p)).resolve())
            resolved = validate_output_directory(p)
            resolved.mkdir(parents=True, exist_ok=True)
        except (PathSafetyError, ValueError) as exc:
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
            if d_clean != "*" and d_clean != "all" and not _DOMAIN.match(d_clean):
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

    def set_universal_mode(self, enabled: bool) -> frozenset[str]:
        if enabled:
            return self.update_allowed_domains(["*"])
        return self.update_allowed_domains(POPULAR_DOMAINS.split(","))

    def get_cookies_status(self) -> dict:
        cookies_file = self._settings.cookies_path
        if not cookies_file.is_file():
            return {
                "has_cookies": False,
                "size_bytes": 0,
                "line_count": 0,
                "updated_at": None,
                "domains_authenticated": [],
            }
        try:
            stat = cookies_file.stat()
            lines = cookies_file.read_text(encoding="utf-8", errors="replace").splitlines()
            domains = set()
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if parts:
                    d = parts[0].lstrip(".").lower()
                    if d:
                        domains.add(d)
            return {
                "has_cookies": True,
                "size_bytes": stat.st_size,
                "line_count": len(lines),
                "updated_at": stat.st_mtime,
                "domains_authenticated": sorted(domains)[:10],
            }
        except OSError:
            return {
                "has_cookies": False,
                "size_bytes": 0,
                "line_count": 0,
                "updated_at": None,
                "domains_authenticated": [],
            }

    def save_cookies(self, content: str) -> dict:
        content = content.strip()
        if not content:
            raise AppError(ErrorCode.INVALID_REQUEST, "Cookie content cannot be empty.")
        if len(content.encode("utf-8")) > 5 * 1024 * 1024:
            raise AppError(ErrorCode.INVALID_REQUEST, "Cookie file exceeds 5MB limit.")

        cookies_file = self._settings.cookies_path
        cookies_file.parent.mkdir(parents=True, exist_ok=True)
        cookies_file.write_text(content + "\n", encoding="utf-8")
        logger.info("saved cookies file", extra={"operation": "cookies", "path": str(cookies_file)})
        return self.get_cookies_status()

    def delete_cookies(self) -> dict:
        cookies_file = self._settings.cookies_path
        if cookies_file.is_file():
            try:
                cookies_file.unlink()
                logger.info("deleted cookies file", extra={"operation": "cookies", "path": str(cookies_file)})
            except OSError as exc:
                raise AppError(ErrorCode.INTERNAL_ERROR, f"Failed to delete cookies: {exc}") from exc
        return self.get_cookies_status()

    def get_all(self) -> dict:
        return {
            "output_directory": str(self._settings.output_directory),
            "allowed_source_domains": sorted(self._settings.source_domains),
            "universal_mode": "*" in self._settings.source_domains or "all" in self._settings.source_domains,
            "has_cookies": self._settings.cookies_path.is_file(),
            "max_parallel_jobs": self._settings.max_parallel_jobs,
            "max_download_gb": int(self._settings.max_download_bytes // (1024**3)),
            "log_level": self._settings.log_level,
        }
