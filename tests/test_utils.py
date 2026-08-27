"""Unit tests for utils and models."""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

# Ensure src/ is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from models import DownloadItem, DownloadStats, DownloadStatus
from utils import (
    capture_filename_from_url,
    filename_from_content_disposition,
    filename_from_url,
    is_valid_url,
    parse_capture_metadata,
    parse_url_entries,
    parse_url_file,
    sanitize_filename,
    unique_filepath,
)


# ── URL validation ────────────────────────────────────────────────────


class TestIsValidUrl:
    def test_http(self):
        assert is_valid_url("http://example.com/file.zip") is True

    def test_https(self):
        assert is_valid_url("https://example.com/file.zip") is True

    def test_ftp_rejected(self):
        assert is_valid_url("ftp://example.com/file.zip") is False

    def test_no_scheme(self):
        assert is_valid_url("example.com/file.zip") is False

    def test_empty(self):
        assert is_valid_url("") is False

    def test_garbage(self):
        assert is_valid_url("not a url at all") is False


# ── Filename derivation ──────────────────────────────────────────────


class TestFilenameFromUrl:
    def test_simple(self):
        assert filename_from_url("https://example.com/path/data.csv") == "data.csv"

    def test_encoded(self):
        assert filename_from_url("https://example.com/my%20file.txt") == "my file.txt"

    def test_no_path(self):
        assert filename_from_url("https://example.com/") == ""

    def test_trailing_slash(self):
        assert filename_from_url("https://example.com/dir/") == ""


class TestFilenameFromContentDisposition:
    def test_attachment(self):
        assert (
            filename_from_content_disposition('attachment; filename="report.pdf"')
            == "report.pdf"
        )

    def test_none(self):
        assert filename_from_content_disposition(None) is None

    def test_no_filename(self):
        assert filename_from_content_disposition("inline") is None


# ── Sanitize filename ────────────────────────────────────────────────


class TestSanitizeFilename:
    def test_removes_illegal_chars(self):
        assert sanitize_filename('a<b>c:d"e') == "a_b_c_d_e"

    def test_strips_dots(self):
        assert sanitize_filename("...test...") == "test"

    def test_empty_becomes_download(self):
        assert sanitize_filename("") == "download"

    def test_windows_reserved_name_is_prefixed(self):
        assert sanitize_filename("CON.txt") == "_CON.txt"

    def test_long_filename_is_limited(self):
        result = sanitize_filename(("a" * 300) + ".txt")
        assert len(result) <= 240
        assert result.endswith(".txt")


# ── parse_url_file ───────────────────────────────────────────────────


class TestParseUrlFile:
    def test_basic(self, tmp_path):
        f = tmp_path / "urls.txt"
        f.write_text(
            "https://a.com/1\n"
            "\n"
            "# comment\n"
            "  https://b.com/2  \n"
        )
        result = parse_url_file(str(f))
        assert result == ["https://a.com/1", "https://b.com/2"]

    def test_labelled_url_strips_prefix(self, tmp_path):
        f = tmp_path / "urls.txt"
        f.write_text(
            "Ethernet52/2.4, https://netvalstorage.blob.core.windows.net/pcaps/exra11.ams21\n"
            "plain https://a.com/1\n"
            "https://b.com/2\n"
        )
        result = parse_url_file(str(f))
        assert result == [
            "https://netvalstorage.blob.core.windows.net/pcaps/exra11.ams21",
            "https://a.com/1",
            "https://b.com/2",
        ]

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        assert parse_url_file(str(f)) == []


class TestParseUrlEntries:
    def test_keeps_role_instance_label(self):
        text = (
            "_gsa-0c0afe96-086b_1230, https://host/a.pcap?sig=x\n"
            "plain-label https://host/b.pcap\n"
            "https://host/c.pcap\n"
        )
        entries = parse_url_entries(text)
        assert [(e.role_instance, e.url) for e in entries] == [
            ("_gsa-0c0afe96-086b_1230", "https://host/a.pcap?sig=x"),
            ("plain-label", "https://host/b.pcap"),
            ("", "https://host/c.pcap"),
        ]

    def test_ignores_blank_and_comment_lines(self):
        text = "\n# comment\nrole1, https://host/a.pcap\n\n"
        entries = parse_url_entries(text)
        assert len(entries) == 1
        assert entries[0].role_instance == "role1"
        assert entries[0].url == "https://host/a.pcap"


# ── capture metadata ─────────────────────────────────────────────────


FULL_URL = (
    "https://netvalstorage.blob.core.windows.net/packettracer-mergedpcaps/"
    "3fa3c40d-ed60-4c40-b761-ab4f22077c5c/exra11.ams21/"
    "livesite_2026_08_26_13_24_00_from_am2pnpf000018c8_104.44.39.154.pcap"
    "?sv=2025-11-05&se=2026-09-02T20%3A42%3A00Z&sr=b&sp=rl&sig=abc%3D"
)


class TestParseCaptureMetadata:
    def test_full_url(self):
        meta = parse_capture_metadata(FULL_URL)
        assert meta.device == "exra11.ams21"
        assert meta.host == "am2pnpf000018c8"
        assert meta.ip == "104.44.39.154"
        assert meta.timestamp == "2026_08_26_13_24_00"
        assert meta.matched is True

    def test_bare_filename_has_no_device(self):
        meta = parse_capture_metadata(
            "livesite_2026_08_18_12_45_00_from_ln2pnpf00017020_10.241.90.223.pcap"
        )
        assert meta.device == ""
        assert meta.ip == "10.241.90.223"
        assert meta.timestamp == "2026_08_18_12_45_00"

    def test_device_prefixed_local_filename(self):
        meta = parse_capture_metadata(
            "exra11.ams21_livesite_2026_08_26_13_24_00_from_am2pnpf000018c8_104.44.39.154.pcap"
        )
        assert meta.device == "exra11.ams21"
        assert meta.ip == "104.44.39.154"

    def test_non_capture_returns_empty(self):
        meta = parse_capture_metadata("https://example.com/file.zip")
        assert meta.matched is False
        assert meta.ip == ""


class TestCaptureFilenameFromUrl:
    def test_prefixes_device(self):
        name = capture_filename_from_url(FULL_URL)
        assert name == (
            "exra11.ams21_livesite_2026_08_26_13_24_00_"
            "from_am2pnpf000018c8_104.44.39.154.pcap"
        )

    def test_non_capture_returns_empty(self):
        assert capture_filename_from_url("https://example.com/file.zip") == ""


# ── unique_filepath ──────────────────────────────────────────────────


class TestUniqueFilepath:
    def test_no_collision(self, tmp_path):
        result = unique_filepath(str(tmp_path), "file.txt")
        assert os.path.basename(result) == "file.txt"

    def test_collision(self, tmp_path):
        (tmp_path / "file.txt").write_text("x")
        result = unique_filepath(str(tmp_path), "file.txt")
        assert os.path.basename(result) == "file (1).txt"

    def test_multiple_collisions(self, tmp_path):
        (tmp_path / "file.txt").write_text("x")
        (tmp_path / "file (1).txt").write_text("x")
        result = unique_filepath(str(tmp_path), "file.txt")
        assert os.path.basename(result) == "file (2).txt"


# ── Models ───────────────────────────────────────────────────────────


class TestDownloadItem:
    def test_progress_pct(self):
        item = DownloadItem(index=0, url="https://x.com/f", total_bytes=200, downloaded_bytes=100)
        assert item.progress_pct == 50.0

    def test_progress_pct_unknown_size(self):
        item = DownloadItem(index=0, url="https://x.com/f")
        assert item.progress_pct == 0.0


class TestDownloadStats:
    def test_overall_pct(self):
        stats = DownloadStats(total=10, completed=3, failed=2, canceled=1, remaining=4)
        assert stats.overall_pct == 60.0

    def test_done_count(self):
        stats = DownloadStats(total=10, completed=3, failed=2, canceled=1, remaining=4)
        assert stats.done_count == 6
