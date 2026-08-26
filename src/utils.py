"""Utility helpers for filename sanitization, URL parsing, and file I/O."""

from __future__ import annotations

import os
import re
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


def parse_url_lines(text: str) -> list[str]:
    """Return URL strings from raw text, one per line.

    Blank lines and lines starting with ``#`` are ignored.
    """
    urls: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def parse_url_file(path: str) -> list[str]:
    """Read a text file and return a list of valid URL strings.

    Blank lines and lines starting with ``#`` are ignored.
    Only ``http`` and ``https`` schemes are accepted.
    """
    with open(path, encoding="utf-8") as fh:
        return parse_url_lines(fh.read())


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
