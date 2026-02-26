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
    filename_from_content_disposition,
    filename_from_url,
    is_valid_url,
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

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        assert parse_url_file(str(f)) == []


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
