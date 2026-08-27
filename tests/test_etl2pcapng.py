"""Unit tests for the etl2pcapng helper (command building + detection paths)."""

from __future__ import annotations

import os
import sys

# Ensure src/ is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pcap.etl2pcapng import (
    ETL2PCAPNG_URL,
    ETL2PCAPNG_VERSION,
    Etl2PcapngInfo,
    build_etl2pcapng_command,
    detect_etl2pcapng,
)


class TestBuildCommand:
    def test_builds_argument_list(self):
        cmd = build_etl2pcapng_command("etl2pcapng.exe", "in.etl", "out.pcapng")
        assert cmd == ["etl2pcapng.exe", "in.etl", "out.pcapng"]


class TestPinnedRelease:
    def test_url_matches_version(self):
        assert ETL2PCAPNG_VERSION in ETL2PCAPNG_URL
        assert ETL2PCAPNG_URL.startswith("https://github.com/microsoft/etl2pcapng")


class TestDetect:
    def test_returns_info_dataclass(self):
        info = detect_etl2pcapng()
        assert isinstance(info, Etl2PcapngInfo)
        # When not found, an error message should be present.
        if not info.found:
            assert info.error
