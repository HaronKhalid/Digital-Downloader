"""Application settings, loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


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
    max_parallel_jobs: int
    log_level: str
    allowed_ports: frozenset[int]
    cors_origins: tuple[str, ...]

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
            max_jobs = int(env.get("MAX_PARALLEL_JOBS", "1"))
        except ValueError as exc:
            raise ConfigError("PORT and MAX_PARALLEL_JOBS must be integers.") from exc
        if not 1024 <= port <= 65535:
            raise ConfigError("PORT must be between 1024 and 65535.")
        if not 1 <= max_jobs <= 4:
            raise ConfigError("MAX_PARALLEL_JOBS must be between 1 and 4.")

        origins = tuple(o.strip() for o in env.get("CORS_ORIGINS", "").split(",") if o.strip())
        if "*" in origins:
            raise ConfigError("CORS_ORIGINS must not contain a wildcard.")

        data = REPO_ROOT / "data"
        return cls(
            app_env=env.get("APP_ENV", "development").strip().lower(),
            host=host,
            port=port,
            output_directory=Path(
                env.get("OUTPUT_DIRECTORY") or (Path.home() / "Downloads" / "PersonalMedia")
            ).expanduser(),
            temp_directory=Path(env.get("TEMP_DIRECTORY") or (data / "temp")).expanduser(),
            database_path=Path(env.get("DATABASE_PATH") or (data / "database" / "history.sqlite3")),
            frontend_directory=REPO_ROOT / "frontend",
            max_parallel_jobs=max_jobs,
            log_level=env.get("LOG_LEVEL", "INFO").strip().upper(),
            allowed_ports=frozenset({80, 443}),
            cors_origins=origins,
        )


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env reader (no dependency). Real environment variables win."""
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
