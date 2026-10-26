"""History item domain model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HistoryItem:
    id: str
    url: str
    title: str
    filename: str
    file_path: str = ""
    file_size: int = 0
    source: str = ""
    format_label: str = ""
    completed_at: str = ""
    file_exists: bool = False
    status: str = "completed"

    @property
    def file_size_bytes(self) -> int:
        return self.file_size

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "filename": self.filename,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "source": self.source,
            "format_label": self.format_label,
            "completed_at": self.completed_at,
            "file_exists": self.file_exists,
            "status": self.status,
        }

