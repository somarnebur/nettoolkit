"""Utility helpers for filename sanitization, URL parsing, and file I/O."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from email.message import Message
from urllib.parse import unquote, urlparse


WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_FILENAME_LENGTH = 240

# Matches the "livesite" capture filename convention, e.g.
#   livesite_2026_08_26_13_24_00_from_am2pnpf000018c8_104.44.39.154.pcap
CAPTURE_FILENAME_RE = re.compile(
    r"livesite_(?P<timestamp>\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2})"
    r"_from_(?P<host>[^\\/]+?)_(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\.pcap(?:ng)?",
    re.IGNORECASE,
)


@dataclass
class CaptureMetadata:
    """Structured fields pulled from a capture URL or filename."""

    device: str = ""
    host: str = ""
    ip: str = ""
    timestamp: str = ""

    @property
    def matched(self) -> bool:
        """True when the source looked like a livesite capture."""
        return bool(self.ip and self.timestamp)


def parse_capture_metadata(url_or_name: str) -> CaptureMetadata:
    """Extract device, host, IP, and timestamp from a capture URL or filename.

    Handles the full blob URL form
    ``.../<device>/livesite_<ts>_from_<host>_<ip>.pcap?<sas>`` as well as a
    locally saved filename that may carry a ``<device>_`` prefix.
    """
    text = (url_or_name or "").strip()
    is_url = "://" in text
    path_part = text.split("?", 1)[0]
    segments = [s for s in re.split(r"[\\/]+", path_part) if s]
    filename = segments[-1] if segments else path_part

    meta = CaptureMetadata()
    match = CAPTURE_FILENAME_RE.search(filename)
    if not match:
        return meta

    meta.timestamp = match.group("timestamp")
    meta.host = match.group("host")
    meta.ip = match.group("ip")

    # Device is either a prefix on the filename itself (locally saved files) or
    # the parent path segment of the original blob URL.
    prefix = filename[: match.start()].strip("_ .")
    if prefix:
        meta.device = prefix
    elif is_url and len(segments) >= 2 and not CAPTURE_FILENAME_RE.search(segments[-2]):
        meta.device = segments[-2]
    return meta


def parse_url_lines(text: str) -> list[str]:
    """Return URL strings from raw text, one per line.

    Blank lines and lines starting with ``#`` are ignored. A line may carry a
    label before the URL (e.g. ``Ethernet52/2.4, https://host/path``); anything
    before the first ``http://``/``https://`` is dropped so only the URL remains.
    """
    urls: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.search(r"https?://\S+", line)
        urls.append(match.group(0) if match else line)
    return urls


def parse_url_file(path: str) -> list[str]:
    """Read a text file and return a list of valid URL strings.

    Blank lines and lines starting with ``#`` are ignored.
    Only ``http`` and ``https`` schemes are accepted.
    """
    with open(path, encoding="utf-8") as fh:
        return parse_url_lines(fh.read())


@dataclass
class UrlEntry:
    """A pasted URL together with any label (role instance name) before it."""

    url: str
    role_instance: str = ""


def parse_url_entries(text: str) -> list[UrlEntry]:
    """Return :class:`UrlEntry` items from raw text, one per line.

    Blank lines and lines starting with ``#`` are ignored. Anything before the
    first ``http(s)://`` on a line is treated as the role instance name, e.g.
    ``_gsa-0c0afe96-086b_1230, https://host/path`` yields role instance
    ``_gsa-0c0afe96-086b_1230``.
    """
    entries: list[UrlEntry] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.search(r"https?://\S+", line)
        if match:
            url = match.group(0)
            label = line[: match.start()].strip().strip(",").strip()
        else:
            url = line
            label = ""
        entries.append(UrlEntry(url=url, role_instance=label))
    return entries


def parse_url_entries_file(path: str) -> list[UrlEntry]:
    """Read a text file and return :class:`UrlEntry` items (labels preserved)."""
    with open(path, encoding="utf-8") as fh:
        return parse_url_entries(fh.read())


def is_valid_url(url: str) -> bool:
    """Return True if *url* has an http or https scheme."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def filename_from_content_disposition(header_value: str | None) -> str | None:
    """Extract a filename from a Content-Disposition header value.

    Returns ``None`` when no filename can be determined.
    """
    if not header_value:
        return None

    # Use email.message.Message to parse the header robustly.
    msg = Message()
    msg["Content-Disposition"] = header_value
    filename = msg.get_filename()
    if filename:
        return sanitize_filename(filename)
    return None


def filename_from_url(url: str) -> str:
    """Derive a filename from the URL path.

    Falls back to an empty string if nothing useful can be extracted.
    """
    parsed = urlparse(url)
    basename = os.path.basename(unquote(parsed.path))
    if basename:
        return sanitize_filename(basename)
    return ""


def capture_filename_from_url(url: str) -> str:
    """Return a device-tagged filename for a capture URL, or "" if not a capture.

    Example ->
      ``exra11.ams21_livesite_2026_08_26_13_24_00_from_am2pnpf000018c8_104.44.39.154.pcap``
    """
    meta = parse_capture_metadata(url)
    if not meta.matched:
        return ""
    parsed = urlparse(url)
    basename = os.path.basename(unquote(parsed.path))
    if not basename:
        return ""
    if meta.device and not basename.startswith(meta.device):
        basename = f"{meta.device}_{basename}"
    return sanitize_filename(basename)


def sanitize_filename(name: str) -> str:
    """Remove or replace characters that are invalid in file names."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
    if not name:
        return "download"

    stem, ext = os.path.splitext(name)
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"

    max_stem_length = MAX_FILENAME_LENGTH - len(ext)
    if max_stem_length < 1:
        ext = ext[: MAX_FILENAME_LENGTH - 1]
        max_stem_length = 1
    stem = stem[:max_stem_length]

    name = f"{stem}{ext}".strip(". ")
    return name or "download"


def unique_filepath(directory: str, filename: str) -> str:
    """Return a path in *directory* for *filename*, adding a suffix to avoid collisions.

    Example: ``file.txt`` -> ``file (1).txt`` -> ``file (2).txt`` ...
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
