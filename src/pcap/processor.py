"""Sequential batch processor & merge processor: queues files, runs tshark / mergecap."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Callable

from .models import BatchStats, CaptureFileItem, FileStatus, OutputFormat
from .tshark import build_mergecap_command, build_tshark_command
from .utils import build_output_filename, timestamp, unique_filepath


class BatchProcessor:
    """Process capture files one at a time in a worker thread.

    Applies a Wireshark display filter to each input file via tshark and writes
    a filtered output file. Processing is strictly sequential (one tshark
    process at a time) to avoid overhead.
    """

    def __init__(
        self,
        items: list[CaptureFileItem],
        output_dir: str,
        display_filter: str,
        tshark_path: str,
        output_format: OutputFormat = OutputFormat.PCAPNG,
        on_progress: Callable[[CaptureFileItem], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.items = items
        self.output_dir = output_dir
        self.display_filter = display_filter
        self.tshark_path = tshark_path
        self.output_format = output_format
        self.on_progress = on_progress or (lambda _: None)
        self.on_log = on_log or (lambda _: None)

        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._pause.set()  # not paused
        self._current_proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> BatchStats:
        """Process all items sequentially (blocking). Call from worker thread."""
        self._cancel.clear()
        self._pause.set()

        ext = ".pcapng" if self.output_format == OutputFormat.PCAPNG else ".pcap"

        for item in self.items:
            if self._cancel.is_set():
                item.status = FileStatus.CANCELED
                self.on_progress(item)
                continue

            # Wait if paused.
            self._pause.wait()
            if self._cancel.is_set():
                item.status = FileStatus.CANCELED
                self.on_progress(item)
                continue

            self._process_one(item, ext)

        return self._compute_stats()

    def request_cancel(self) -> None:
        """Signal cancellation and terminate the running tshark process."""
        self._cancel.set()
        self._pause.set()  # unpause so we can exit
        with self._lock:
            if self._current_proc is not None:
                try:
                    self._current_proc.terminate()
                except OSError:
                    pass

    def toggle_pause(self) -> bool:
        """Toggle pause/resume. Returns True if now paused."""
        if self._pause.is_set():
            self._pause.clear()
            self._log("Processing paused.")
            return True
        self._pause.set()
        self._log("Processing resumed.")
        return False

    def current_stats(self) -> BatchStats:
        """Return aggregate stats for the current item states."""
        return self._compute_stats()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _process_one(self, item: CaptureFileItem, ext: str) -> None:
        """Run tshark for a single capture file."""
        item.status = FileStatus.PROCESSING
        item.start_time = time.time()
        self.on_progress(item)
        self._log(f"[START] {item.filename}")

        out_name = build_output_filename(item.filename, ext)
        out_path = unique_filepath(self.output_dir, out_name)
        item.output_path = out_path

        cmd = build_tshark_command(
            tshark_path=self.tshark_path,
            input_file=item.input_path,
            output_file=out_path,
            display_filter=self.display_filter,
            output_format=self.output_format,
        )

        try:
            with self._lock:
                self._current_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    errors="replace",
                )

            _stdout, stderr = self._current_proc.communicate()
            item.exit_code = self._current_proc.returncode

            with self._lock:
                self._current_proc = None

            item.end_time = time.time()

            if self._cancel.is_set():
                item.status = FileStatus.CANCELED
                self._log(f"[CANCELED] {item.filename}")
                self._remove_if_exists(out_path)
            elif item.exit_code == 0:
                item.status = FileStatus.DONE
                self._log(f"[DONE] {item.filename} -> {os.path.basename(out_path)}")
            else:
                item.status = FileStatus.FAILED
                snippet = (stderr or "").strip()[:300]
                item.error = f"Exit {item.exit_code}: {snippet}"
                self._log(f"[FAILED] {item.filename} - {item.error}")
                self._remove_if_exists(out_path)

        except Exception as exc:
            item.end_time = time.time()
            item.status = FileStatus.FAILED
            item.error = str(exc)
            self._log(f"[ERROR] {item.filename} - {exc}")
            self._remove_if_exists(out_path)
            with self._lock:
                self._current_proc = None

        self.on_progress(item)

    def _compute_stats(self) -> BatchStats:
        return _compute_batch_stats(self.items)

    def _log(self, message: str) -> None:
        self.on_log(f"[{timestamp()}] {message}")

    @staticmethod
    def _remove_if_exists(path: str) -> None:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


class MergeProcessor:
    """Merge multiple capture files into one using mergecap.

    All items are passed as inputs to a single mergecap invocation.
    """

    def __init__(
        self,
        items: list[CaptureFileItem],
        output_dir: str,
        mergecap_path: str,
        output_format: OutputFormat = OutputFormat.PCAPNG,
        on_progress: Callable[[CaptureFileItem], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.items = items
        self.output_dir = output_dir
        self.mergecap_path = mergecap_path
        self.output_format = output_format
        self.on_progress = on_progress or (lambda _: None)
        self.on_log = on_log or (lambda _: None)

        self._cancel = threading.Event()
        self._current_proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> BatchStats:
        """Merge all items into a single file (blocking). Call from worker thread."""
        self._cancel.clear()

        ext = ".pcapng" if self.output_format == OutputFormat.PCAPNG else ".pcap"
        out_name = f"merged{ext}"
        out_path = unique_filepath(self.output_dir, out_name)

        input_files = [item.input_path for item in self.items]

        for item in self.items:
            item.status = FileStatus.PROCESSING
            item.start_time = time.time()
            item.output_path = out_path
            self.on_progress(item)

        self._log(f"Merging {len(input_files)} files -> {os.path.basename(out_path)}")

        cmd = build_mergecap_command(
            mergecap_path=self.mergecap_path,
            input_files=input_files,
            output_file=out_path,
            output_format=self.output_format,
        )

        try:
            with self._lock:
                self._current_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    errors="replace",
                )

            _stdout, stderr = self._current_proc.communicate()
            exit_code = self._current_proc.returncode

            with self._lock:
                self._current_proc = None

            end_time = time.time()

            if self._cancel.is_set():
                for item in self.items:
                    item.status = FileStatus.CANCELED
                    item.end_time = end_time
                    self.on_progress(item)
                self._log("[CANCELED] merge operation")
                self._remove_if_exists(out_path)
            elif exit_code == 0:
                for item in self.items:
                    item.status = FileStatus.DONE
                    item.end_time = end_time
                    item.exit_code = exit_code
                    self.on_progress(item)
                self._log(f"[DONE] Merged -> {os.path.basename(out_path)}")
            else:
                snippet = (stderr or "").strip()[:300]
                err_msg = f"Exit {exit_code}: {snippet}"
                for item in self.items:
                    item.status = FileStatus.FAILED
                    item.end_time = end_time
                    item.exit_code = exit_code
                    item.error = err_msg
                    self.on_progress(item)
                self._log(f"[FAILED] merge - {err_msg}")
                self._remove_if_exists(out_path)

        except Exception as exc:
            end_time = time.time()
            for item in self.items:
                item.status = FileStatus.FAILED
                item.end_time = end_time
                item.error = str(exc)
                self.on_progress(item)
            self._log(f"[ERROR] merge - {exc}")
            self._remove_if_exists(out_path)
            with self._lock:
                self._current_proc = None

        return self._compute_stats()

    def request_cancel(self) -> None:
        """Signal cancellation and terminate the running mergecap process."""
        self._cancel.set()
        with self._lock:
            if self._current_proc is not None:
                try:
                    self._current_proc.terminate()
                except OSError:
                    pass

    def toggle_pause(self) -> bool:
        """No-op for merge (single operation, cannot pause)."""
        return False

    def current_stats(self) -> BatchStats:
        """Return aggregate stats for the current item states."""
        return self._compute_stats()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute_stats(self) -> BatchStats:
        return _compute_batch_stats(self.items)

    def _log(self, message: str) -> None:
        self.on_log(f"[{timestamp()}] {message}")

    @staticmethod
    def _remove_if_exists(path: str) -> None:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


def _compute_batch_stats(items: list[CaptureFileItem]) -> BatchStats:
    stats = BatchStats(total=len(items))
    for it in items:
        if it.status == FileStatus.DONE:
            stats.succeeded += 1
            stats.processed += 1
        elif it.status == FileStatus.FAILED:
            stats.failed += 1
            stats.processed += 1
        elif it.status == FileStatus.CANCELED:
            stats.canceled += 1
    return stats
