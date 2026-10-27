"""Application settings, loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping

if getattr(sys, "frozen", False):
    REPO_ROOT = Path(sys._MEIPASS)
    if sys.platform == "win32":
        USER_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "DigitalDownloader" / "data"
    else:
        USER_DATA_DIR = Path.home() / ".digitaldownloader" / "data"
else:
    REPO_ROOT = Path(__file__).resolve().parents[3]
    USER_DATA_DIR = REPO_ROOT / "data"

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_DOMAIN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")


DEFAULT_SOURCE_DOMAINS = "*"


class ConfigError(RuntimeError):
    """Invalid or unsafe configuration. Raised at startup so the app never runs misconfigured."""


@dataclass(frozen=True)
class Settings:
    app_env: str
    host: str
    port: int
    output_directory: Path
    temp_directory: Path
    database_path: Path
    frontend_directory: Path
    cookies_path: Path
    max_parallel_jobs: int
    log_level: str
    allowed_ports: frozenset[int]
    cors_origins: tuple[str, ...]
    source_domains: frozenset[str]
    max_download_bytes: int

    @classmethod
    def load(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env

        host = env.get("HOST", "127.0.0.1").strip()
        if host not in LOOPBACK_HOSTS:
            raise ConfigError(
                f"HOST={host!r} is not a loopback address. This application only binds to "
                "127.0.0.1 and must not be exposed to other machines."
            )
        try:
            port = int(env.get("PORT", "8000"))
            max_jobs = int(env.get("MAX_PARALLEL_JOBS", "3"))
            max_gb = int(env.get("MAX_DOWNLOAD_GB", "20"))
        except ValueError as exc:
            raise ConfigError("PORT and MAX_PARALLEL_JOBS must be integers.") from exc
        if not 1024 <= port <= 65535:
            raise ConfigError("PORT must be between 1024 and 65535.")
        if not 1 <= max_gb <= 500:
            raise ConfigError("MAX_DOWNLOAD_GB must be between 1 and 500.")
        if not 1 <= max_jobs <= 4:
            raise ConfigError("MAX_PARALLEL_JOBS must be between 1 and 4.")

        origins = tuple(o.strip() for o in env.get("CORS_ORIGINS", "").split(",") if o.strip())
        if "*" in origins:
            raise ConfigError("CORS_ORIGINS must not contain a wildcard.")

        raw_domains = env.get("ALLOWED_SOURCE_DOMAINS", DEFAULT_SOURCE_DOMAINS)
        domains = frozenset(
            d.strip().lower().lstrip(".")
            for d in raw_domains.split(",")
            if d.strip()
        )
        for domain in domains:
            if domain != "*" and domain != "all" and not _DOMAIN.match(domain):
                raise ConfigError(f"ALLOWED_SOURCE_DOMAINS contains an invalid domain: {domain!r}")

        data = Path(env.get("DATA_DIRECTORY") or USER_DATA_DIR)
        return cls(
            app_env=env.get("APP_ENV", "development").strip().lower(),
            host=host,
            port=port,
            output_directory=Path(
                env.get("OUTPUT_DIRECTORY") or (Path.home() / "Downloads" / "PersonalMedia")
            ).expanduser(),
            temp_directory=Path(env.get("TEMP_DIRECTORY") or (data / "temp")).expanduser(),
            database_path=Path(env.get("DATABASE_PATH") or (data / "database" / "history.sqlite3")),
            frontend_directory=Path(env.get("FRONTEND_DIRECTORY") or (REPO_ROOT / "frontend")),
            cookies_path=Path(env.get("COOKIES_PATH") or (data / "cookies.txt")).expanduser(),
            max_parallel_jobs=max_jobs,
            log_level=env.get("LOG_LEVEL", "INFO").strip().upper(),
            allowed_ports=frozenset({80, 443}),
            cors_origins=origins,
            source_domains=domains,
            max_download_bytes=max_gb * 1024**3,
        )


def _sync_windows_path() -> None:
    """Ensure PATH reflects user environment changes on Windows without needing a shell restart."""
    if sys.platform != "win32":
        return
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            user_path, _ = winreg.QueryValueEx(key, "Path")
            current = os.environ.get("PATH", "")
            current_entries = {os.path.normcase(p) for p in current.split(os.pathsep) if p}
            new_entries = [p for p in user_path.split(";") if p and os.path.normcase(p) not in current_entries]
            if new_entries:
                os.environ["PATH"] = os.pathsep.join(new_entries) + os.pathsep + current
    except (OSError, ValueError):
        pass


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env reader (no dependency). Real environment variables win."""
    _sync_windows_path()
    bin_dir = REPO_ROOT / "bin"
    if bin_dir.is_dir():
        current = os.environ.get("PATH", "")
        if str(bin_dir) not in current:
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{current}" if current else str(bin_dir)
    path = path or REPO_ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))



@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    return Settings.load()
