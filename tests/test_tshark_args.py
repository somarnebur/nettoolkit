"""Unit tests for tshark / mergecap command-argument building."""

from __future__ import annotations

import os
import sys

# Ensure src/ is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pcap.models import OutputFormat
from pcap.tshark import build_mergecap_command, build_tshark_command


class TestBuildTsharkCommand:
    def test_default_pcapng(self):
        cmd = build_tshark_command(
            tshark_path="tshark",
            input_file="in.pcap",
            output_file="out.pcapng",
            display_filter="ip.addr == 10.0.0.5",
        )
        assert cmd == [
            "tshark",
            "-r", "in.pcap",
            "-Y", "ip.addr == 10.0.0.5",
            "-w", "out.pcapng",
            "-F", "pcapng",
        ]

    def test_pcap_format(self):
        cmd = build_tshark_command(
            tshark_path="tshark",
            input_file="in.pcapng",
            output_file="out.pcap",
            display_filter="tcp.port == 443",
            output_format=OutputFormat.PCAP,
        )
        assert cmd[-2:] == ["-F", "pcap"]
        assert "-Y" in cmd
        assert cmd[cmd.index("-Y") + 1] == "tcp.port == 443"

    def test_filter_passed_as_single_arg(self):
        # A filter with spaces must remain one argument (no shell parsing).
        cmd = build_tshark_command(
            tshark_path="tshark",
            input_file="in.pcap",
            output_file="out.pcapng",
            display_filter="http && ip.src == 192.168.1.10",
        )
        assert "http && ip.src == 192.168.1.10" in cmd


class TestBuildMergecapCommand:
    def test_basic(self):
        cmd = build_mergecap_command(
            mergecap_path="mergecap",
            input_files=["a.pcap", "b.pcap"],
            output_file="merged.pcapng",
        )
        assert cmd[0] == "mergecap"
        assert cmd[1:3] == ["-w", "merged.pcapng"]
        assert cmd[-2:] == ["a.pcap", "b.pcap"]

    def test_pcap_format(self):
        cmd = build_mergecap_command(
            mergecap_path="mergecap",
            input_files=["a.pcap", "b.pcap"],
            output_file="merged.pcap",
            output_format=OutputFormat.PCAP,
        )
        assert "-F" in cmd
        assert cmd[cmd.index("-F") + 1] == "pcap"
        # Inputs come after the format flag.
        assert cmd[-2:] == ["a.pcap", "b.pcap"]
