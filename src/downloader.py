"""Async download engine with configurable concurrency using httpx."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import threading
from typing import Callable

import httpx

from models import DownloadItem, DownloadStats, DownloadStatus
from utils import (
    filename_from_content_disposition,
    filename_from_url,
    capture_filename_from_url,
    is_valid_url,
    unique_filepath,
)

# Default chunk size for streaming reads. Larger reads mean fewer Python-level
# loop iterations (and fewer progress callbacks) per megabyte transferred.
CHUNK_SIZE = 1_048_576  # 1 MB
# Minimum wall-clock gap between per-item progress callbacks. Bytes are still
# counted on every chunk; only the UI-bound callback is coalesced so a fast
# download does not flood the event loop with thousands of updates per second.
PROGRESS_INTERVAL = 0.1  # seconds
CONNECT_TIMEOUT = 30  # seconds
READ_TIMEOUT = 120  # seconds
MAX_RETRIES = 2
RETRY_BACKOFF = 2  # seconds (doubles each retry)
# Only split a file into parallel range segments when it is at least this large;
# below this, a single streamed connection is already efficient.
SEGMENT_MIN_SIZE = 8 * 1_048_576  # 8 MB


class DownloadEngine:
    """Manages concurrent file downloads driven by an asyncio event-loop.

    Parameters
    ----------
    items : list[DownloadItem]
        Pre-built download items (one per URL).
    output_dir : str
        Directory where completed files are saved.
    concurrency : int
        Maximum simultaneous downloads.
    on_progress : callable, optional
        ``(DownloadItem) -> None`` called on every progress tick
        (from the asyncio thread – UI callbacks must marshal).
    on_log : callable, optional
        ``(str) -> None`` called with timestamped log messages.
    """

    def __init__(
        self,
        items: list[DownloadItem],
        output_dir: str,
        concurrency: int = 5,
        connections_per_file: int = 4,
        on_progress: Callable[[DownloadItem], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.items = items
        self.output_dir = output_dir
        self.concurrency = max(1, min(concurrency, 50))
        self.connections_per_file = max(1, min(connections_per_file, 16))
        self.on_progress = on_progress or (lambda _: None)
        self.on_log = on_log or (lambda _: None)

        self._semaphore: asyncio.Semaphore | None = None
        self._cancel_event: asyncio.Event | None = None
        self._pause_event: asyncio.Event | None = None
        self._client: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._state_lock = threading.Lock()
        self._paused = False

    # ------------------------------------------------------------------
    # Public API (called from any thread)
    # ------------------------------------------------------------------

    async def run(self) -> DownloadStats:
        """Download all items concurrently and return aggregate stats."""
        self._loop = asyncio.get_running_loop()
        self._semaphore = asyncio.Semaphore(self.concurrency)
        self._cancel_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        with self._state_lock:
            self._paused = False

        timeout = httpx.Timeout(
            connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=30, pool=30
        )
        # Size the pool for the worst case of every active file using its full
        # segment fan-out, so range segments reuse kept-alive connections.
        max_conns = self.concurrency * self.connections_per_file + 4
        limits = httpx.Limits(
            max_connections=max_conns,
            max_keepalive_connections=max_conns,
            keepalive_expiry=30,
        )
        async with httpx.AsyncClient(
            timeout=timeout, limits=limits, follow_redirects=True
        ) as client:
            self._client = client
            tasks = [
                asyncio.create_task(self._download_one(item)) for item in self.items
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for item, result in zip(self.items, results):
                if isinstance(result, Exception):
                    item.status = DownloadStatus.FAILED
                    item.error = str(result) or result.__class__.__name__
                    self.on_progress(item)
            self._client = None

        return self._compute_stats()

    def request_cancel(self) -> None:
        """Signal all in-progress and queued downloads to cancel."""
        if self._loop and self._cancel_event and self._pause_event:
            self._loop.call_soon_threadsafe(self._cancel_event.set)
            self._loop.call_soon_threadsafe(self._pause_event.set)

    def current_stats(self) -> DownloadStats:
        """Return aggregate stats for the current item states."""
        return self._compute_stats()

    def toggle_pause(self) -> bool:
        """Toggle pause/resume. Returns True if now paused."""
        with self._state_lock:
            self._paused = not self._paused
            paused = self._paused

        if not self._loop or not self._pause_event:
            return paused

        if paused:
            self._loop.call_soon_threadsafe(self._pause_event.clear)
            self._log("Downloads paused.")
            return True

        self._loop.call_soon_threadsafe(self._pause_event.set)
        self._log("Downloads resumed.")
        return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _download_one(self, item: DownloadItem) -> None:
        """Download a single item, respecting semaphore, pause, and cancel."""
        # Validate URL first.
        if not is_valid_url(item.url):
            item.status = DownloadStatus.FAILED
            item.error = "Invalid URL (must be http or https)"
            self._log(f"[INVALID] {item.url}")
            self.on_progress(item)
            return

        # Wait for semaphore slot.
        assert self._semaphore is not None and self._cancel_event is not None
        async with self._semaphore:
            if self._cancel_event.is_set():
                item.status = DownloadStatus.CANCELED
                self.on_progress(item)
                return

            item.status = DownloadStatus.DOWNLOADING
            self.on_progress(item)
            self._log(f"[START] {item.url}")

            last_error = ""
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    await self._do_download(item)
                    return  # success
                except asyncio.CancelledError:
                    item.status = DownloadStatus.CANCELED
                    self.on_progress(item)
                    return
                except Exception as exc:
                    last_error = str(exc)
                    if attempt < MAX_RETRIES:
                        wait = RETRY_BACKOFF * attempt
                        self._log(
                            f"[RETRY {attempt}/{MAX_RETRIES}] {item.url} – "
                            f"waiting {wait}s ({last_error})"
                        )
                        await asyncio.sleep(wait)
                    else:
                        item.status = DownloadStatus.FAILED
                        item.error = last_error
                        self._log(f"[FAILED] {item.url} – {last_error}")
                        self.on_progress(item)

    async def _do_download(self, item: DownloadItem) -> None:
        """Download an item, using parallel range segments when supported."""
        assert self._client is not None
        assert self._cancel_event is not None

        # Reset counter so retries report accurate progress.
        item.downloaded_bytes = 0

        # Probe for size + range support so large files can be segmented.
        total, accept_ranges, head_headers = await self._probe(item.url)
        if (
            accept_ranges
            and total >= SEGMENT_MIN_SIZE
            and self.connections_per_file > 1
        ):
            item.total_bytes = total
            item.filename = self._resolve_filename(
                item, head_headers.get("Content-Disposition")
            )
            try:
                await self._do_segmented_download(item, total)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Server advertised ranges but misbehaved — fall back to a
                # single stream rather than fail the whole download.
                self._log(f"[FALLBACK] {item.filename}: {exc}")
                item.downloaded_bytes = 0

        await self._do_stream_download(item)

    async def _do_stream_download(self, item: DownloadItem) -> None:
        """Single-connection streaming download (fallback / small files)."""
        assert self._client is not None
        assert self._cancel_event is not None

        async with self._client.stream("GET", item.url) as resp:
            resp.raise_for_status()

            item.filename = self._resolve_filename(
                item, resp.headers.get("Content-Disposition")
            )

            # Content length (may be unknown).
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit():
                item.total_bytes = int(cl)

            # Stream to a temp file, then rename on success.
            tmp_fd, tmp_path = tempfile.mkstemp(dir=self.output_dir)
            try:
                last_emit = 0.0
                with os.fdopen(tmp_fd, "wb") as tmp_file:
                    async for chunk in resp.aiter_bytes(chunk_size=CHUNK_SIZE):
                        # Check cancel.
                        if self._cancel_event.is_set():
                            item.status = DownloadStatus.CANCELED
                            self.on_progress(item)
                            return

                        # Respect pause.
                        await self._wait_if_paused()

                        tmp_file.write(chunk)
                        item.downloaded_bytes += len(chunk)
                        # Coalesce UI-bound progress updates to at most one per
                        # PROGRESS_INTERVAL; byte counting above stays exact.
                        now = time.monotonic()
                        if now - last_emit >= PROGRESS_INTERVAL:
                            last_emit = now
                            self.on_progress(item)

                # Move temp file to final destination.
                final_path = unique_filepath(self.output_dir, item.filename)
                item.filename = os.path.basename(final_path)
                os.replace(tmp_path, final_path)
                tmp_path = ""  # mark as moved
                item.status = DownloadStatus.DONE
                self._log(f"[DONE] {item.filename}")
                self.on_progress(item)
            finally:
                # Clean up temp file if still around (error / cancel).
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

    async def _do_segmented_download(self, item: DownloadItem, total: int) -> None:
        """Download a file as N concurrent byte-range segments."""
        assert self._client is not None
        assert self._cancel_event is not None

        n = min(self.connections_per_file, max(1, total // (1_048_576)))
        seg = total // n
        ranges = []
        for i in range(n):
            start = i * seg
            end = total - 1 if i == n - 1 else start + seg - 1
            ranges.append((start, end))

        tmp_fd, tmp_path = tempfile.mkstemp(dir=self.output_dir)
        try:
            # Pre-size the file so each segment writes into its own region.
            with os.fdopen(tmp_fd, "wb") as f:
                if total > 0:
                    f.truncate(total)

            self._log(f"[SEGMENTED x{n}] {item.filename}")
            tasks = [
                asyncio.create_task(self._fetch_segment(item, tmp_path, s, e))
                for (s, e) in ranges
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            if self._cancel_event.is_set():
                item.status = DownloadStatus.CANCELED
                self.on_progress(item)
                return

            errors = [r for r in results if isinstance(r, Exception)]
            if errors:
                raise errors[0]

            final_path = unique_filepath(self.output_dir, item.filename)
            item.filename = os.path.basename(final_path)
            os.replace(tmp_path, final_path)
            tmp_path = ""  # mark as moved
            item.status = DownloadStatus.DONE
            self._log(f"[DONE] {item.filename}")
            self.on_progress(item)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    async def _fetch_segment(
        self, item: DownloadItem, tmp_path: str, start: int, end: int
    ) -> None:
        """Stream one byte-range [start, end] into its region of tmp_path."""
        assert self._client is not None
        assert self._cancel_event is not None

        headers = {"Range": f"bytes={start}-{end}"}
        async with self._client.stream("GET", item.url, headers=headers) as resp:
            resp.raise_for_status()
            # A 200 (not 206) means the server ignored Range — abort so the
            # caller can retry as a plain stream rather than corrupt the file.
            if resp.status_code != 206:
                raise RuntimeError("server ignored Range request (no 206)")

            # Each segment uses its own handle positioned at its own offset;
            # regions are disjoint so concurrent writes are safe.
            with open(tmp_path, "r+b") as f:
                f.seek(start)
                last_emit = 0.0
                async for chunk in resp.aiter_bytes(chunk_size=CHUNK_SIZE):
                    if self._cancel_event.is_set():
                        return
                    await self._wait_if_paused()
                    f.write(chunk)
                    item.downloaded_bytes += len(chunk)
                    now = time.monotonic()
                    if now - last_emit >= PROGRESS_INTERVAL:
                        last_emit = now
                        self.on_progress(item)

    async def _probe(self, url: str) -> tuple[int, bool, httpx.Headers]:
        """Best-effort HEAD probe for content length and range support."""
        assert self._client is not None
        try:
            resp = await self._client.head(url)
            if resp.status_code >= 400:
                return (0, False, httpx.Headers())
            cl = resp.headers.get("Content-Length")
            total = int(cl) if cl and cl.isdigit() else 0
            accept = resp.headers.get("Accept-Ranges", "").lower() == "bytes"
            return (total, accept, resp.headers)
        except Exception:
            return (0, False, httpx.Headers())

    def _resolve_filename(self, item: DownloadItem, cd_header: str | None) -> str:
        """Pick a filename from Content-Disposition, capture metadata, or URL."""
        fname = filename_from_content_disposition(cd_header)
        capture_name = capture_filename_from_url(item.url)
        if capture_name:
            # Capture URLs carry device/IP metadata worth keeping in the name.
            fname = capture_name
        elif not fname:
            fname = filename_from_url(item.url)
        if not fname:
            fname = f"download_{item.index}.bin"
        return fname

    async def _wait_if_paused(self) -> None:
        """Block until the pause event is set (i.e. not paused)."""
        assert self._pause_event is not None
        await self._pause_event.wait()

    def _compute_stats(self) -> DownloadStats:
        stats = DownloadStats(total=len(self.items))
        for it in self.items:
            if it.status == DownloadStatus.DONE:
                stats.completed += 1
            elif it.status == DownloadStatus.FAILED:
                stats.failed += 1
            elif it.status == DownloadStatus.CANCELED:
                stats.canceled += 1
        stats.remaining = stats.total - stats.done_count
        return stats

    def _log(self, message: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.on_log(f"[{ts}] {message}")
