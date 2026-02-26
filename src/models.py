"""Data models for the concurrent URL downloader."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class DownloadStatus(enum.Enum):
    """Status of an individual download item."""

    QUEUED = "Queued"
    DOWNLOADING = "Downloading"
    DONE = "Done"
    FAILED = "Failed"
    CANCELED = "Canceled"
    PAUSED = "Paused"


@dataclass
class DownloadItem:
    """Represents a single URL to be downloaded."""

    index: int
    url: str
    filename: str = ""
    status: DownloadStatus = DownloadStatus.QUEUED
    total_bytes: int = 0
    downloaded_bytes: int = 0
    error: str = ""

    @property
    def progress_pct(self) -> float:
        """Return download progress as a percentage (0-100)."""
        if self.total_bytes <= 0:
            return 0.0
        return min(100.0, (self.downloaded_bytes / self.total_bytes) * 100.0)


@dataclass
class DownloadStats:
    """Aggregate statistics across all downloads."""

    total: int = 0
    completed: int = 0
    failed: int = 0
    canceled: int = 0
    remaining: int = 0

    @property
    def done_count(self) -> int:
        """Number of items that are no longer pending."""
        return self.completed + self.failed + self.canceled

    @property
    def overall_pct(self) -> float:
        """Overall progress percentage."""
        if self.total <= 0:
            return 0.0
        return min(100.0, (self.done_count / self.total) * 100.0)
