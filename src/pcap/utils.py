"""Utility helpers: folder scanning, filename collision handling, timestamps."""

from __future__ import annotations

import os
import re
import time

from utils import parse_capture_metadata

# Extensions we consider capture files (case-insensitive).
CAPTURE_EXTENSIONS = {".pcap", ".pcapng"}
# Windows event-trace logs that etl2pcapng can convert.
ETL_EXTENSIONS = {".etl"}
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


def scan_etl_files(folder: str) -> list[str]:
    """Return sorted list of absolute paths to .etl files in *folder*.

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
        if ext.lower() in ETL_EXTENSIONS:
            results.append(full)
    return results


def build_converted_filename(input_filename: str) -> str:
    """Derive the pcapng output name for an ETL conversion.

    Example: ``trace.etl`` -> ``trace.pcapng``.
    """
    stem, _ = os.path.splitext(input_filename)
    return sanitize_filename(f"{stem}.pcapng")



def build_output_filename(input_filename: str, output_ext: str = ".pcapng") -> str:
    """Derive the filtered output filename from *input_filename*.

    Example: ``trace1.pcap`` -> ``trace1_filtered.pcapng``
    """
    stem, _ = os.path.splitext(input_filename)
    return sanitize_filename(f"{stem}_filtered{output_ext}")


def unique_filepath(directory: str, filename: str, reserved: set[str] | None = None) -> str:
    """Return a path in *directory* for *filename*, adding a suffix to avoid collisions.

    Example: ``file_filtered.pcapng`` -> ``file_filtered (1).pcapng``. Paths in
    *reserved* are treated as taken even if not yet written to disk.
    """
    reserved = reserved or set()
    dest = os.path.join(directory, filename)
    if not os.path.exists(dest) and dest not in reserved:
        return dest

    stem, ext = os.path.splitext(filename)
    counter = 1
    while True:
        candidate = os.path.join(directory, f"{stem} ({counter}){ext}")
        if not os.path.exists(candidate) and candidate not in reserved:
            return candidate
        counter += 1


def build_merge_group_filename(device: str, ip: str, output_ext: str = ".pcapng") -> str:
    """Build the merged output name for a (device, IP) group.

    Example: ``exra11.ams21`` + ``104.44.39.154`` ->
    ``exra11.ams21_104.44.39.154_merged.pcapng``.
    """
    parts = [p for p in (device, ip) if p]
    stem = "_".join(parts) if parts else "merged"
    return sanitize_filename(f"{stem}_merged{output_ext}")


def group_capture_items(items: list) -> list[tuple[tuple[str, str], list]]:
    """Group items by (device, IP), preserving first-seen order.

    Files without an extractable IP are grouped by their own filename stem so
    they are never merged with unrelated captures.
    """
    groups: dict[tuple[str, str], list] = {}
    order: list[tuple[str, str]] = []
    for item in items:
        meta = parse_capture_metadata(item.filename)
        if meta.ip:
            key = (meta.device, meta.ip)
        else:
            key = ("", os.path.splitext(item.filename)[0])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)
    return [(key, groups[key]) for key in order]


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
