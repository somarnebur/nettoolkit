"""Utility helpers: folder scanning, filename collision handling, timestamps."""

from __future__ import annotations

import os
import re
import time

# Extensions we consider capture files (case-insensitive).
CAPTURE_EXTENSIONS = {".pcap", ".pcapng"}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_FILENAME_LENGTH = 240


def scan_capture_files(folder: str) -> list[str]:
    """Return sorted list of absolute paths to .pcap/.pcapng files in *folder*.

    Only considers immediate files (non-recursive).
    """
    results: list[str] = []
    try:
        entries = os.listdir(folder)
    except OSError:
        return results

    for name in sorted(entries, key=str.lower):
        full = os.path.join(folder, name)
        if not os.path.isfile(full):
            continue
        _, ext = os.path.splitext(name)
        if ext.lower() in CAPTURE_EXTENSIONS:
            results.append(full)
    return results


def build_output_filename(input_filename: str, output_ext: str = ".pcapng") -> str:
    """Derive the filtered output filename from *input_filename*.

    Example: ``trace1.pcap`` -> ``trace1_filtered.pcapng``
    """
    stem, _ = os.path.splitext(input_filename)
    return sanitize_filename(f"{stem}_filtered{output_ext}")


def unique_filepath(directory: str, filename: str) -> str:
    """Return a path in *directory* for *filename*, adding a suffix to avoid collisions.

    Example: ``file_filtered.pcapng`` -> ``file_filtered (1).pcapng``
    """
    dest = os.path.join(directory, filename)
    if not os.path.exists(dest):
        return dest

    stem, ext = os.path.splitext(filename)
    counter = 1
    while True:
        candidate = os.path.join(directory, f"{stem} ({counter}){ext}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def timestamp() -> str:
    """Return a formatted timestamp string for logging."""
    return time.strftime("%H:%M:%S")


def sanitize_filename(name: str) -> str:
    """Remove or replace characters that are invalid in file names."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
    if not name:
        return "capture"

    stem, ext = os.path.splitext(name)
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"

    max_stem_length = MAX_FILENAME_LENGTH - len(ext)
    if max_stem_length < 1:
        ext = ext[: MAX_FILENAME_LENGTH - 1]
        max_stem_length = 1
    stem = stem[:max_stem_length]

    name = f"{stem}{ext}".strip(". ")
    return name or "capture"
