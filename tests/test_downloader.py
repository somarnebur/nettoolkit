"""Tests for the download engine: segmented range downloads and fallback."""

from __future__ import annotations

import asyncio
import os
import re
import sys

import httpx
import pytest

# Ensure src/ is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import downloader  # noqa: E402
from downloader import DownloadEngine  # noqa: E402
from models import DownloadItem, DownloadStatus  # noqa: E402

# Body large enough to cross SEGMENT_MIN_SIZE (8 MB) so segmentation kicks in.
BODY = bytes((i * 7 + 13) % 256 for i in range(9 * 1_048_576))


def _make_engine_with_transport(handler, tmp_path, **kwargs):
    """Build an engine whose AsyncClient talks to an in-memory MockTransport."""
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args, **client_kwargs):
        client_kwargs["transport"] = transport
        # MockTransport ignores real pool limits; drop to avoid warnings.
        client_kwargs.pop("limits", None)
        return original(*args, **client_kwargs)

    logs: list[str] = []
    item = DownloadItem(index=0, url="https://example.com/bigfile.bin")
    engine = DownloadEngine(
        items=[item],
        output_dir=str(tmp_path),
        on_log=lambda m: logs.append(m),
        **kwargs,
    )
    return engine, item, logs, patched, original


def _range_handler(support_ranges: bool):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            headers = {"Content-Length": str(len(BODY))}
            if support_ranges:
                headers["Accept-Ranges"] = "bytes"
            return httpx.Response(200, headers=headers)

        rng = request.headers.get("Range")
        if rng and support_ranges:
            m = re.match(r"bytes=(\d+)-(\d+)", rng)
            start, end = int(m.group(1)), int(m.group(2))
            chunk = BODY[start : end + 1]
            return httpx.Response(
                206,
                content=chunk,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{len(BODY)}",
                    "Content-Length": str(len(chunk)),
                },
            )
        return httpx.Response(
            200, content=BODY, headers={"Content-Length": str(len(BODY))}
        )

    return handler


class TestSegmentedDownload:
    def test_reassembles_file_from_segments(self, tmp_path, monkeypatch):
        engine, item, logs, patched, _ = _make_engine_with_transport(
            _range_handler(support_ranges=True), tmp_path, connections_per_file=4
        )
        monkeypatch.setattr(downloader.httpx, "AsyncClient", patched)

        asyncio.run(engine.run())

        assert item.status == DownloadStatus.DONE
        assert item.downloaded_bytes == len(BODY)
        out = tmp_path / item.filename
        assert out.read_bytes() == BODY
        assert any("SEGMENTED" in m for m in logs)

    def test_falls_back_when_ranges_unsupported(self, tmp_path, monkeypatch):
        engine, item, logs, patched, _ = _make_engine_with_transport(
            _range_handler(support_ranges=False), tmp_path, connections_per_file=4
        )
        monkeypatch.setattr(downloader.httpx, "AsyncClient", patched)

        asyncio.run(engine.run())

        assert item.status == DownloadStatus.DONE
        out = tmp_path / item.filename
        assert out.read_bytes() == BODY
        # No Accept-Ranges → single stream, never segmented.
        assert not any("SEGMENTED" in m for m in logs)

    def test_single_connection_setting_skips_segmentation(
        self, tmp_path, monkeypatch
    ):
        engine, item, logs, patched, _ = _make_engine_with_transport(
            _range_handler(support_ranges=True), tmp_path, connections_per_file=1
        )
        monkeypatch.setattr(downloader.httpx, "AsyncClient", patched)

        asyncio.run(engine.run())

        assert item.status == DownloadStatus.DONE
        assert (tmp_path / item.filename).read_bytes() == BODY
        assert not any("SEGMENTED" in m for m in logs)
