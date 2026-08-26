"""tshark / mergecap CLI wrapper: tool detection, command-arg building."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from .models import OutputFormat


@dataclass
class TsharkInfo:
    """Result of detecting tshark on the system."""

    found: bool
    path: str = ""
    version: str = ""
    error: str = ""


@dataclass
class MergecapInfo:
    """Result of detecting mergecap on the system."""

    found: bool
    path: str = ""
    version: str = ""
    error: str = ""


def _find_wireshark_tool(tool: str) -> str | None:
    """Locate a Wireshark CLI tool, searching PATH then Windows install paths."""
    exe = shutil.which(tool)
    if exe is not None:
        return exe

    if os.name == "nt":
        exe_name = f"{tool}.exe"
        candidates = [
            os.path.join(
                os.environ.get("ProgramFiles", r"C:\Program Files"),
                "Wireshark",
                exe_name,
            ),
            os.path.join(
                os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                "Wireshark",
                exe_name,
            ),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
    return None


def _tool_version(exe: str) -> tuple[bool, str, str]:
    """Run ``<exe> -v`` and return (ok, version_line, error)."""
    try:
        result = subprocess.run(
            [exe, "-v"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
        )
        if result.returncode != 0:
            return False, "", (result.stderr or result.stdout or "-v failed").strip()
        # Some tools write version info to stderr.
        out_text = result.stdout or result.stderr
        version_line = out_text.strip().splitlines()[0] if out_text else ""
        return True, version_line, ""
    except Exception as exc:
        return False, "", str(exc)


def detect_tshark() -> TsharkInfo:
    """Detect whether tshark is available and return version info."""
    exe = _find_wireshark_tool("tshark")
    if exe is None:
        return TsharkInfo(
            found=False,
            error=(
                "tshark not found. Install Wireshark and ensure tshark is on PATH.\n"
                "Download: https://www.wireshark.org/download.html"
            ),
        )
    ok, version, error = _tool_version(exe)
    if not ok:
        return TsharkInfo(found=False, path=exe, error=error)
    return TsharkInfo(found=True, path=exe, version=version)


def detect_mergecap() -> MergecapInfo:
    """Detect whether mergecap is available and return version info."""
    exe = _find_wireshark_tool("mergecap")
    if exe is None:
        return MergecapInfo(
            found=False,
            error=(
                "mergecap not found. Install Wireshark and ensure mergecap is on PATH.\n"
                "Download: https://www.wireshark.org/download.html"
            ),
        )
    ok, version, error = _tool_version(exe)
    if not ok:
        return MergecapInfo(found=False, path=exe, error=error)
    return MergecapInfo(found=True, path=exe, version=version)


def build_tshark_command(
    tshark_path: str,
    input_file: str,
    output_file: str,
    display_filter: str,
    output_format: OutputFormat = OutputFormat.PCAPNG,
) -> list[str]:
    """Build a tshark command-line as a list of arguments (no shell)."""
    cmd = [
        tshark_path,
        "-r", input_file,
        "-Y", display_filter,
        "-w", output_file,
    ]
    if output_format == OutputFormat.PCAP:
        cmd.extend(["-F", "pcap"])
    else:
        cmd.extend(["-F", "pcapng"])
    return cmd


def build_mergecap_command(
    mergecap_path: str,
    input_files: list[str],
    output_file: str,
    output_format: OutputFormat = OutputFormat.PCAPNG,
) -> list[str]:
    """Build a mergecap command-line as a list of arguments (no shell)."""
    cmd = [
        mergecap_path,
        "-w", output_file,
    ]
    if output_format == OutputFormat.PCAP:
        cmd.extend(["-F", "pcap"])
    else:
        cmd.extend(["-F", "pcapng"])
    cmd.extend(input_files)
    return cmd
