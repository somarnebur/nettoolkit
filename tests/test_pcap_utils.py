"""Unit tests for PCAP utils and models."""

from __future__ import annotations

import os
import sys

# Ensure src/ is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pcap.models import BatchStats, CaptureFileItem, FileStatus
from pcap.utils import (
    build_output_filename,
    sanitize_filename,
    scan_capture_files,
    unique_filepath,
)


class TestScanCaptureFiles:
    def test_finds_pcap_and_pcapng(self, tmp_path):
        (tmp_path / "a.pcap").write_bytes(b"x")
        (tmp_path / "b.pcapng").write_bytes(b"x")
        (tmp_path / "c.txt").write_text("nope")
        (tmp_path / "d.PCAP").write_bytes(b"x")  # case-insensitive
        result = scan_capture_files(str(tmp_path))
        names = sorted(os.path.basename(p) for p in result)
        assert names == ["a.pcap", "b.pcapng", "d.PCAP"]

    def test_missing_folder(self):
        assert scan_capture_files(os.path.join("no", "such", "dir")) == []


class TestBuildOutputFilename:
    def test_default(self):
        assert build_output_filename("trace1.pcap") == "trace1_filtered.pcapng"

    def test_custom_ext(self):
        assert build_output_filename("trace1.pcapng", ".pcap") == "trace1_filtered.pcap"


class TestSanitizeFilename:
    def test_removes_illegal_chars(self):
        assert sanitize_filename('a<b>c:d"e') == "a_b_c_d_e"

    def test_empty_becomes_capture(self):
        assert sanitize_filename("") == "capture"


class TestUniqueFilepath:
    def test_no_collision(self, tmp_path):
        result = unique_filepath(str(tmp_path), "merged.pcapng")
        assert os.path.basename(result) == "merged.pcapng"

    def test_collision(self, tmp_path):
        (tmp_path / "merged.pcapng").write_bytes(b"x")
        result = unique_filepath(str(tmp_path), "merged.pcapng")
        assert os.path.basename(result) == "merged (1).pcapng"


class TestModels:
    def test_batch_stats_pct(self):
        stats = BatchStats(total=4, processed=2, succeeded=2)
        assert stats.overall_pct == 50.0
        assert stats.remaining == 2

    def test_capture_item_defaults(self):
        item = CaptureFileItem(index=0, input_path="a.pcap", filename="a.pcap")
        assert item.status == FileStatus.QUEUED
        assert item.elapsed == 0.0
