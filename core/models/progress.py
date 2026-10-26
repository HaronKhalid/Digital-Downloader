"""Progress model for media transfer tracking."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DownloadProgress:
    job_id: str = ""
    status: str = ""
    percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed_bps: float | None = None
    eta_seconds: float | None = None
    stage: str = ""

    @property
    def fraction(self) -> float:
        if not self.total_bytes or self.total_bytes <= 0:
            return 0.0
        return min(1.0, max(0.0, self.downloaded_bytes / self.total_bytes))

    @property
    def percentage(self) -> float:
        return self.percent if self.percent else self.fraction * 100.0

