"""Sequential batch processor & merge processor: queues files, runs tshark / mergecap."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Callable

from .models import BatchStats, CaptureFileItem, FileStatus, OutputFormat
from .etl2pcapng import build_etl2pcapng_command
from .tshark import build_mergecap_command, build_tshark_command
from .utils import (
    build_converted_filename,
    build_merge_group_filename,
    build_output_filename,
    group_capture_items,
    timestamp,
    unique_filepath,
)


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


class EtlConvertProcessor:
    """Convert Windows ``.etl`` traces to ``.pcapng`` using etl2pcapng.

    Each input file is converted with a single etl2pcapng invocation. Output is
    always pcapng (the only format etl2pcapng produces). Processing is strictly
    sequential and supports pause / resume and cancellation, mirroring
    :class:`BatchProcessor`.
    """

    def __init__(
        self,
        items: list[CaptureFileItem],
        output_dir: str,
        etl2pcapng_path: str,
        on_progress: Callable[[CaptureFileItem], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.items = items
        self.output_dir = output_dir
        self.etl2pcapng_path = etl2pcapng_path
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
        """Convert all items sequentially (blocking). Call from worker thread."""
        self._cancel.clear()
        self._pause.set()

        for item in self.items:
            if self._cancel.is_set():
                item.status = FileStatus.CANCELED
                self.on_progress(item)
                continue

            self._pause.wait()
            if self._cancel.is_set():
                item.status = FileStatus.CANCELED
                self.on_progress(item)
                continue

            self._process_one(item)

        return self._compute_stats()

    def request_cancel(self) -> None:
        """Signal cancellation and terminate the running conversion."""
        self._cancel.set()
        self._pause.set()
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
            self._log("Conversion paused.")
            return True
        self._pause.set()
        self._log("Conversion resumed.")
        return False

    def current_stats(self) -> BatchStats:
        return self._compute_stats()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _process_one(self, item: CaptureFileItem) -> None:
        """Run etl2pcapng for a single .etl file."""
        item.status = FileStatus.PROCESSING
        item.start_time = time.time()
        self.on_progress(item)
        self._log(f"[START] {item.filename}")

        out_name = build_converted_filename(item.filename)
        out_path = unique_filepath(self.output_dir, out_name)
        item.output_path = out_path

        cmd = build_etl2pcapng_command(
            self.etl2pcapng_path, item.input_path, out_path
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

            stdout, stderr = self._current_proc.communicate()
            item.exit_code = self._current_proc.returncode

            with self._lock:
                self._current_proc = None

            item.end_time = time.time()

            produced = os.path.isfile(out_path) and os.path.getsize(out_path) > 0
            if self._cancel.is_set():
                item.status = FileStatus.CANCELED
                self._log(f"[CANCELED] {item.filename}")
                self._remove_if_exists(out_path)
            elif item.exit_code == 0 and produced:
                item.status = FileStatus.DONE
                self._log(f"[DONE] {item.filename} -> {os.path.basename(out_path)}")
            else:
                item.status = FileStatus.FAILED
                snippet = (stderr or stdout or "").strip()[:300]
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


class GroupedMergeProcessor:
    """Merge capture files into one output per (device, IP) group via mergecap.

    Each group is a single mergecap invocation; groups run sequentially so only
    one mergecap process is active at a time.
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
        """Merge each (device, IP) group into its own file (blocking)."""
        self._cancel.clear()
        ext = ".pcapng" if self.output_format == OutputFormat.PCAPNG else ".pcap"
        groups = group_capture_items(self.items)
        reserved: set[str] = set()
        self._log(f"Grouping {len(self.items)} files into {len(groups)} merge group(s).")

        for (device, ip), members in groups:
            if self._cancel.is_set():
                for item in members:
                    item.status = FileStatus.CANCELED
                    self.on_progress(item)
                continue
            out_name = build_merge_group_filename(device, ip, ext)
            out_path = unique_filepath(self.output_dir, out_name, reserved)
            reserved.add(out_path)
            self._merge_group(members, out_path, device, ip)

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
        """No-op for grouped merge (single operation per group, cannot pause)."""
        return False

    def current_stats(self) -> BatchStats:
        """Return aggregate stats for the current item states."""
        return self._compute_stats()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _merge_group(
        self, members: list[CaptureFileItem], out_path: str, device: str, ip: str
    ) -> None:
        label = " / ".join(p for p in (device, ip) if p) or "ungrouped"
        for item in members:
            item.status = FileStatus.PROCESSING
            item.start_time = time.time()
            item.output_path = out_path
            self.on_progress(item)
        self._log(
            f"[MERGE] {label}: {len(members)} file(s) -> {os.path.basename(out_path)}"
        )

        cmd = build_mergecap_command(
            mergecap_path=self.mergecap_path,
            input_files=[item.input_path for item in members],
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
                for item in members:
                    item.status = FileStatus.CANCELED
                    item.end_time = end_time
                    self.on_progress(item)
                self._log(f"[CANCELED] merge {label}")
                self._remove_if_exists(out_path)
            elif exit_code == 0:
                for item in members:
                    item.status = FileStatus.DONE
                    item.end_time = end_time
                    item.exit_code = exit_code
                    self.on_progress(item)
                self._log(f"[DONE] {label} -> {os.path.basename(out_path)}")
            else:
                snippet = (stderr or "").strip()[:300]
                err_msg = f"Exit {exit_code}: {snippet}"
                for item in members:
                    item.status = FileStatus.FAILED
                    item.end_time = end_time
                    item.exit_code = exit_code
                    item.error = err_msg
                    self.on_progress(item)
                self._log(f"[FAILED] merge {label} - {err_msg}")
                self._remove_if_exists(out_path)

        except Exception as exc:
            end_time = time.time()
            for item in members:
                item.status = FileStatus.FAILED
                item.end_time = end_time
                item.error = str(exc)
                self.on_progress(item)
            self._log(f"[ERROR] merge {label} - {exc}")
            self._remove_if_exists(out_path)
            with self._lock:
                self._current_proc = None

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


class FilterThenMergeProcessor:
    """Two-phase pipeline: filter every file, then merge the filtered outputs.

    Phase 1 filters each input into a temporary folder (tshark). Phase 2 merges
    those filtered files (mergecap) into the output folder, either all into one
    file or one file per (device, IP) group. Intermediate filtered files are
    removed afterwards so only the merged result remains.
    """

    def __init__(
        self,
        items: list[CaptureFileItem],
        output_dir: str,
        display_filter: str,
        tshark_path: str,
        mergecap_path: str,
        output_format: OutputFormat = OutputFormat.PCAPNG,
        group_by_device: bool = False,
        on_progress: Callable[[CaptureFileItem], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self.items = items
        self.output_dir = output_dir
        self.display_filter = display_filter
        self.tshark_path = tshark_path
        self.mergecap_path = mergecap_path
        self.output_format = output_format
        self.group_by_device = group_by_device
        self.on_progress = on_progress or (lambda _: None)
        self.on_log = on_log or (lambda _: None)

        self._active: BatchProcessor | MergeProcessor | GroupedMergeProcessor | None = None
        self._canceled = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> BatchStats:
        """Filter all items, then merge the filtered outputs (blocking)."""
        self._canceled = False
        temp_dir = tempfile.mkdtemp(prefix="nettoolkit_filtered_")
        try:
            # Phase 1: filter into a temporary folder.
            self._log("Phase 1/2: filtering...")
            filter_proc = BatchProcessor(
                items=self.items,
                output_dir=temp_dir,
                display_filter=self.display_filter,
                tshark_path=self.tshark_path,
                output_format=self.output_format,
                on_progress=self.on_progress,
                on_log=self.on_log,
            )
            with self._lock:
                if self._canceled:
                    return _compute_batch_stats(self.items)
                self._active = filter_proc
            filter_proc.run()
            with self._lock:
                self._active = None
            if self._canceled:
                return _compute_batch_stats(self.items)

            # Collect files that filtered successfully; keep the original name so
            # device/IP grouping still works on the filtered copies.
            pairs: list[tuple[CaptureFileItem, CaptureFileItem]] = []
            for item in self.items:
                if (
                    item.status == FileStatus.DONE
                    and item.output_path
                    and os.path.exists(item.output_path)
                ):
                    merge_item = CaptureFileItem(
                        index=len(pairs),
                        input_path=item.output_path,
                        filename=item.filename,
                    )
                    pairs.append((item, merge_item))

            if not pairs:
                self._log("No files passed the filter; nothing to merge.")
                return _compute_batch_stats(self.items)

            # Phase 2: merge the filtered outputs.
            self._log(f"Phase 2/2: merging {len(pairs)} filtered file(s)...")
            merge_items = [mi for _, mi in pairs]
            if self.group_by_device:
                merge_proc: MergeProcessor | GroupedMergeProcessor = GroupedMergeProcessor(
                    items=merge_items,
                    output_dir=self.output_dir,
                    mergecap_path=self.mergecap_path,
                    output_format=self.output_format,
                    on_progress=lambda _item: None,
                    on_log=self.on_log,
                )
            else:
                merge_proc = MergeProcessor(
                    items=merge_items,
                    output_dir=self.output_dir,
                    mergecap_path=self.mergecap_path,
                    output_format=self.output_format,
                    on_progress=lambda _item: None,
                    on_log=self.on_log,
                )
            with self._lock:
                if self._canceled:
                    return _compute_batch_stats(self.items)
                self._active = merge_proc
            merge_proc.run()
            with self._lock:
                self._active = None

            # Reflect the merged result back onto the original table rows.
            for original, merged in pairs:
                original.output_path = merged.output_path
                if merged.status in (FileStatus.FAILED, FileStatus.CANCELED):
                    original.status = merged.status
                    original.error = merged.error
                self.on_progress(original)

            return _compute_batch_stats(self.items)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def request_cancel(self) -> None:
        """Cancel whichever phase is currently running."""
        with self._lock:
            self._canceled = True
            if self._active is not None:
                self._active.request_cancel()

    def toggle_pause(self) -> bool:
        """Pause/resume the active phase (only the filter phase can pause)."""
        with self._lock:
            if self._active is not None:
                return self._active.toggle_pause()
        return False

    def current_stats(self) -> BatchStats:
        """Return aggregate stats for the current item states."""
        return _compute_batch_stats(self.items)

    def _log(self, message: str) -> None:
        self.on_log(f"[{timestamp()}] {message}")


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
