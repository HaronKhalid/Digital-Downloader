"""SQLite persistence for the download queue.

Only what is needed to *recreate* a job is stored (URL, format id, output format, title) plus its
final status. Active rows (status ``queued``) are restored after a restart or crash; finished rows
stay so a failed or cancelled download can be retried later. No file paths or cookies are stored.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..models.job import Job

logger = logging.getLogger("app.queue")

ACTIVE = "queued"  # stored for every job that has not reached a terminal state
KEEP_FINISHED = 200


@dataclass(frozen=True)
class StoredJob:
    id: str
    url: str
    title: str
    format_id: str
    output_format: str | None
    status: str
    error_message: str | None
    created_at: str


class QueueStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queue_jobs (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    format_id TEXT NOT NULL,
                    output_format TEXT,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        try:
            self._db_path.chmod(0o600)
        except (OSError, NotImplementedError):
            pass

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def add(self, job: Job) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO queue_jobs
                (id, url, title, format_id, output_format, status, error_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (job.id, job.url, job.title, job.format_id, job.output_format, ACTIVE,
                 job.created_at.isoformat(timespec="seconds"), self._now()),
            )
            conn.commit()

    def finish(self, job: Job) -> None:
        """Record a terminal status (completed / failed / cancelled)."""
        message = job.error_message
        with self._lock, self._conn() as conn:
            conn.execute(
                "UPDATE queue_jobs SET status = ?, error_message = ?, updated_at = ? WHERE id = ?",
                (job.status.value, message, self._now(), job.id),
            )
            conn.execute(
                """
                DELETE FROM queue_jobs WHERE status != ? AND id NOT IN (
                    SELECT id FROM queue_jobs WHERE status != ? ORDER BY updated_at DESC LIMIT ?
                )
                """,
                (ACTIVE, ACTIVE, KEEP_FINISHED),
            )
            conn.commit()

    def delete(self, job_id: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM queue_jobs WHERE id = ?", (job_id,))
            conn.commit()

    @staticmethod
    def _row(r: sqlite3.Row) -> StoredJob:
        return StoredJob(r["id"], r["url"], r["title"], r["format_id"], r["output_format"],
                         r["status"], r["error_message"], r["created_at"])

    def pending(self) -> list[StoredJob]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM queue_jobs WHERE status = ? ORDER BY created_at ASC", (ACTIVE,)
            ).fetchall()
        return [self._row(r) for r in rows]

    def get(self, job_id: str) -> StoredJob | None:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM queue_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row(row) if row else None
