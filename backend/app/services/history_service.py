"""SQLite persistence for completed downloads."""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..core.errors import AppError, ErrorCode
from ..models.job import Job, JobStatus
from ..utils.filenames import ALLOWED_OUTPUT_EXTENSIONS

logger = logging.getLogger("app.history")


@dataclass(frozen=True)
class HistoryItem:
    id: str
    url: str
    title: str
    filename: str
    file_path: str
    file_size: int
    source: str
    format_label: str
    completed_at: str
    file_exists: bool

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "filename": self.filename,
            "file_size": self.file_size,
            "source": self.source,
            "format_label": self.format_label,
            "completed_at": self.completed_at,
            "file_exists": self.file_exists,
        }


class HistoryService:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS downloads (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    format_label TEXT NOT NULL,
                    completed_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_completed_at ON downloads(completed_at DESC)")
            conn.commit()

        # Restrict permissions on database file
        try:
            self._db_path.chmod(0o600)
        except (OSError, NotImplementedError):
            pass

    def record(self, job: Job, source: str = "", format_label: str = "") -> HistoryItem | None:
        if job.status is not JobStatus.COMPLETED or not job.output_path or not job.filename:
            return None
        completed_at = (job.completed_at or datetime.now(timezone.utc)).isoformat()
        file_path_str = str(job.output_path.resolve())
        file_size = job.file_size or (job.output_path.stat().st_size if job.output_path.is_file() else 0)

        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO downloads (id, url, title, filename, file_path, file_size, source, format_label, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.url,
                    job.title,
                    job.filename,
                    file_path_str,
                    file_size,
                    source,
                    format_label or (job.output_format or "default").upper(),
                    completed_at,
                ),
            )
            conn.commit()

        return HistoryItem(
            id=job.id,
            url=job.url,
            title=job.title,
            filename=job.filename,
            file_path=file_path_str,
            file_size=file_size,
            source=source,
            format_label=format_label or (job.output_format or "default").upper(),
            completed_at=completed_at,
            file_exists=job.output_path.is_file(),
        )

    def list(self, limit: int = 50) -> list[HistoryItem]:
        limit = max(1, min(100, limit))
        with self._lock, self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, url, title, filename, file_path, file_size, source, format_label, completed_at
                FROM downloads
                ORDER BY completed_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        items = []
        for r in rows:
            path = Path(r["file_path"])
            items.append(
                HistoryItem(
                    id=r["id"],
                    url=r["url"],
                    title=r["title"],
                    filename=r["filename"],
                    file_path=r["file_path"],
                    file_size=r["file_size"],
                    source=r["source"],
                    format_label=r["format_label"],
                    completed_at=r["completed_at"],
                    file_exists=path.is_file(),
                )
            )
        return items

    def get(self, item_id: str) -> HistoryItem | None:
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, url, title, filename, file_path, file_size, source, format_label, completed_at
                FROM downloads
                WHERE id = ?
                """,
                (item_id,),
            ).fetchone()

        if not row:
            return None
        path = Path(row["file_path"])
        return HistoryItem(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            filename=row["filename"],
            file_path=row["file_path"],
            file_size=row["file_size"],
            source=row["source"],
            format_label=row["format_label"],
            completed_at=row["completed_at"],
            file_exists=path.is_file(),
        )

    def delete(self, item_id: str) -> bool:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("DELETE FROM downloads WHERE id = ?", (item_id,))
            conn.commit()
            return cur.rowcount > 0

    def completed_file(self, item_id: str) -> Path:
        item = self.get(item_id)
        if not item:
            raise AppError(ErrorCode.NOT_FOUND, "That history item was not found.", status_code=404)
        path = Path(item.file_path).resolve()
        if not path.is_file() or path.suffix.lstrip(".").lower() not in ALLOWED_OUTPUT_EXTENSIONS:
            raise AppError(ErrorCode.NOT_FOUND, "The downloaded file could not be found.", status_code=404)
        return path
