"""Utility helpers for filename sanitization, URL parsing, and file I/O."""

from __future__ import annotations

import os
import re
from email.message import Message
from pathlib import Path
from urllib.parse import unquote, urlparse


def parse_url_file(path: str) -> list[str]:
    """Read a text file and return a list of valid URL strings.

    Blank lines and lines starting with ``#`` are ignored.
    Only ``http`` and ``https`` schemes are accepted.
    """
    urls: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


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
    # Replace path-separator and other problematic chars.
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
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
