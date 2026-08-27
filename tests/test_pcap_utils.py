"""Unit tests for PCAP utils and models."""

from __future__ import annotations

import os
import sys

# Ensure src/ is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pcap.models import BatchStats, CaptureFileItem, FileStatus
from pcap.utils import (
    build_converted_filename,
    build_merge_group_filename,
    build_output_filename,
    group_capture_items,
    sanitize_filename,
    scan_capture_files,
    scan_etl_files,
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


class TestScanEtlFiles:
    def test_finds_only_etl(self, tmp_path):
        (tmp_path / "trace.etl").write_bytes(b"x")
        (tmp_path / "other.ETL").write_bytes(b"x")  # case-insensitive
        (tmp_path / "cap.pcap").write_bytes(b"x")
        (tmp_path / "note.txt").write_text("nope")
        result = scan_etl_files(str(tmp_path))
        names = sorted(os.path.basename(p) for p in result)
        assert names == ["other.ETL", "trace.etl"]

    def test_missing_folder_returns_empty(self):
        assert scan_etl_files(os.path.join("does", "not", "exist")) == []


class TestBuildConvertedFilename:
    def test_replaces_extension_with_pcapng(self):
        assert build_converted_filename("trace.etl") == "trace.pcapng"

    def test_handles_no_extension(self):
        assert build_converted_filename("capture") == "capture.pcapng"

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

    def test_reserved_paths_are_skipped(self, tmp_path):
        reserved = {os.path.join(str(tmp_path), "merged.pcapng")}
        result = unique_filepath(str(tmp_path), "merged.pcapng", reserved)
        assert os.path.basename(result) == "merged (1).pcapng"


def _item(index, filename):
    return CaptureFileItem(index=index, input_path=filename, filename=filename)


class TestBuildMergeGroupFilename:
    def test_device_and_ip(self):
        assert (
            build_merge_group_filename("exra11.ams21", "104.44.39.154")
            == "exra11.ams21_104.44.39.154_merged.pcapng"
        )

    def test_ip_only(self):
        assert build_merge_group_filename("", "10.0.0.1", ".pcap") == "10.0.0.1_merged.pcap"


class TestGroupCaptureItems:
    def test_groups_by_device_and_ip(self):
        items = [
            _item(0, "exra11.ams21_livesite_2026_08_26_13_24_00_from_h1_104.44.39.154.pcap"),
            _item(1, "exra11.ams21_livesite_2026_08_26_13_25_00_from_h1_104.44.39.154.pcap"),
            _item(2, "exra12.ams21_livesite_2026_08_26_13_24_00_from_h2_10.0.0.9.pcap"),
        ]
        groups = group_capture_items(items)
        keys = [key for key, _ in groups]
        assert keys == [("exra11.ams21", "104.44.39.154"), ("exra12.ams21", "10.0.0.9")]
        assert [len(members) for _, members in groups] == [2, 1]

    def test_non_capture_files_stay_separate(self):
        items = [_item(0, "random.pcap"), _item(1, "other.pcapng")]
        groups = group_capture_items(items)
        assert len(groups) == 2


class TestModels:
    def test_batch_stats_pct(self):
        stats = BatchStats(total=4, processed=2, succeeded=2)
        assert stats.overall_pct == 50.0
        assert stats.remaining == 2

    def test_capture_item_defaults(self):
        item = CaptureFileItem(index=0, input_path="a.pcap", filename="a.pcap")
        assert item.status == FileStatus.QUEUED
        assert item.elapsed == 0.0
