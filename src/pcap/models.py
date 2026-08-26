"""Data models for the batch PCAP filter / merge functionality."""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass


class FileStatus(enum.Enum):
    """Status of an individual capture file in the processing queue."""

    QUEUED = "Queued"
    PROCESSING = "Processing"
    DONE = "Done"
    FAILED = "Failed"
    CANCELED = "Canceled"


class OutputFormat(enum.Enum):
    """Supported tshark / mergecap output formats."""

    PCAPNG = "pcapng"
    PCAP = "pcap"


@dataclass
class CaptureFileItem:
    """Represents a single capture file to be processed."""

    index: int
    input_path: str
    filename: str = ""
    status: FileStatus = FileStatus.QUEUED
    output_path: str = ""
    error: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    exit_code: int | None = None

    @property
    def elapsed(self) -> float:
        """Return elapsed processing time in seconds."""
        if self.start_time <= 0:
            return 0.0
        end = self.end_time if self.end_time > 0 else time.time()
        return end - self.start_time


@dataclass
class BatchStats:
    """Aggregate statistics across all files in a batch."""

    total: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    canceled: int = 0

    @property
    def remaining(self) -> int:
        return self.total - self.processed - self.canceled

    @property
    def done_count(self) -> int:
        return self.succeeded + self.failed + self.canceled

    @property
    def overall_pct(self) -> float:
        if self.total <= 0:
            return 0.0
        return min(100.0, (self.done_count / self.total) * 100.0)
