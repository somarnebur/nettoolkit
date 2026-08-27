"""etl2pcapng helper: locate or download Microsoft's etl2pcapng.exe.

etl2pcapng converts Windows ``.etl`` network traces (ndiscap / pktmon) into
``.pcapng`` files that Wireshark can open. The prebuilt binary is published by
Microsoft under the MIT license:
https://github.com/microsoft/etl2pcapng/releases
"""

from __future__ import annotations

import os
import shutil
import urllib.request
from dataclasses import dataclass
from typing import Callable

# Pinned release so the download URL and expected size are deterministic.
ETL2PCAPNG_VERSION = "v1.11.0"
ETL2PCAPNG_URL = (
    "https://github.com/microsoft/etl2pcapng/releases/download/"
    f"{ETL2PCAPNG_VERSION}/etl2pcapng.exe"
)
# Size (bytes) of the official v1.11.0 etl2pcapng.exe asset - used as a light
# integrity check on the downloaded file.
ETL2PCAPNG_EXPECTED_SIZE = 163_872


@dataclass
class Etl2PcapngInfo:
    """Result of locating etl2pcapng on the system."""

    found: bool
    path: str = ""
    version: str = ""
    error: str = ""


def _project_root() -> str:
    """Return the nettoolkit project root (two levels above this package)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def tools_dir() -> str:
    """Return the project-local ``tools`` folder where the binary is stored."""
    return os.path.join(_project_root(), "tools")


def bundled_path() -> str:
    """Return the expected path of a project-bundled etl2pcapng.exe."""
    return os.path.join(tools_dir(), "etl2pcapng.exe")


def detect_etl2pcapng() -> Etl2PcapngInfo:
    """Locate etl2pcapng: project ``tools`` folder first, then PATH."""
    local = bundled_path()
    if os.path.isfile(local):
        return Etl2PcapngInfo(
            found=True, path=local, version=f"{ETL2PCAPNG_VERSION} (bundled)"
        )

    on_path = shutil.which("etl2pcapng")
    if on_path:
        return Etl2PcapngInfo(found=True, path=on_path, version="on PATH")

    return Etl2PcapngInfo(
        found=False,
        error=(
            "etl2pcapng not found. It can be downloaded automatically from "
            f"{ETL2PCAPNG_URL}"
        ),
    )


def download_etl2pcapng(
    on_log: Callable[[str], None] | None = None,
) -> Etl2PcapngInfo:
    """Download the pinned etl2pcapng.exe into the project ``tools`` folder.

    Returns an :class:`Etl2PcapngInfo` describing the result. The download uses
    HTTPS against a pinned GitHub release URL and verifies the file size.
    """
    log = on_log or (lambda _: None)
    dest = bundled_path()
    os.makedirs(tools_dir(), exist_ok=True)

    log(f"Downloading etl2pcapng {ETL2PCAPNG_VERSION} from GitHub...")
    tmp = dest + ".part"
    try:
        req = urllib.request.Request(
            ETL2PCAPNG_URL, headers={"User-Agent": "nettoolkit"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (pinned https)
            data = resp.read()
        with open(tmp, "wb") as fh:
            fh.write(data)

        if len(data) != ETL2PCAPNG_EXPECTED_SIZE:
            os.remove(tmp)
            return Etl2PcapngInfo(
                found=False,
                error=(
                    "Downloaded etl2pcapng.exe has an unexpected size "
                    f"({len(data)} bytes, expected {ETL2PCAPNG_EXPECTED_SIZE}). "
                    "Aborting for safety."
                ),
            )

        os.replace(tmp, dest)
        log(f"etl2pcapng saved to {dest}")
        return Etl2PcapngInfo(
            found=True, path=dest, version=f"{ETL2PCAPNG_VERSION} (downloaded)"
        )
    except Exception as exc:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return Etl2PcapngInfo(
            found=False, error=f"Failed to download etl2pcapng: {exc}"
        )


def build_etl2pcapng_command(exe: str, input_file: str, output_file: str) -> list[str]:
    """Build the etl2pcapng command-line as an argument list (no shell)."""
    return [exe, input_file, output_file]
