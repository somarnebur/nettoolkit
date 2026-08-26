"""PCAP Filter / Merge tab - batch tshark/mergecap UI as an embeddable frame."""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .models import BatchStats, CaptureFileItem, FileStatus, OutputFormat
from .processor import BatchProcessor, MergeProcessor
from .tshark import MergecapInfo, TsharkInfo, detect_mergecap, detect_tshark
from .utils import scan_capture_files


class PcapTab(ttk.Frame):
    """Batch PCAP filter (tshark) / merge (mergecap), embeddable in a Notebook."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)

        # State
        self._input_dir: str = ""
        self._output_dir: str = ""
        self._items: list[CaptureFileItem] = []
        self._processor: BatchProcessor | MergeProcessor | None = None
        self._thread: threading.Thread | None = None
        self._is_paused = False

        # Tool detection (runs once at startup).
        self._tshark: TsharkInfo = detect_tshark()
        self._mergecap: MergecapInfo = detect_mergecap()

        self._build_ui()
        self._report_tools()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        ctrl = ttk.Frame(self, padding=8)
        ctrl.pack(fill=tk.X)
        ctrl.columnconfigure(1, weight=1)

        # Input folder
        ttk.Button(ctrl, text="Input folder", command=self._pick_input).grid(
            row=0, column=0, sticky=tk.W, padx=(0, 4)
        )
        self._in_label = ttk.Label(ctrl, text="(no folder selected)", foreground="gray")
        self._in_label.grid(row=0, column=1, columnspan=3, sticky=tk.W)

        # Output folder
        ttk.Button(ctrl, text="Output folder", command=self._pick_output).grid(
            row=1, column=0, sticky=tk.W, padx=(0, 4), pady=(4, 0)
        )
        self._out_label = ttk.Label(
            ctrl, text="(no folder selected)", foreground="gray"
        )
        self._out_label.grid(row=1, column=1, columnspan=3, sticky=tk.W, pady=(4, 0))

        # Mode: Filter vs Merge
        ttk.Label(ctrl, text="Mode:").grid(row=2, column=0, sticky=tk.W, pady=(8, 0))
        self._mode_var = tk.StringVar(value="filter")
        mode_frame = ttk.Frame(ctrl)
        mode_frame.grid(row=2, column=1, sticky=tk.W, pady=(8, 0))
        ttk.Radiobutton(
            mode_frame,
            text="Filter (tshark)",
            variable=self._mode_var,
            value="filter",
            command=self._on_mode_change,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Radiobutton(
            mode_frame,
            text="Merge (mergecap)",
            variable=self._mode_var,
            value="merge",
            command=self._on_mode_change,
        ).pack(side=tk.LEFT)

        # Display filter
        ttk.Label(ctrl, text="Display filter:").grid(
            row=3, column=0, sticky=tk.NW, pady=(8, 0)
        )
        self._filter_text = tk.Text(ctrl, height=2, width=50, wrap=tk.WORD)
        self._filter_text.grid(
            row=3, column=1, columnspan=3, sticky=tk.EW, pady=(8, 0)
        )
        ttk.Label(
            ctrl,
            text="Wireshark display filter, e.g.  ip.addr == 10.0.0.5",
            foreground="gray",
        ).grid(row=4, column=1, columnspan=3, sticky=tk.W)

        # Output format
        ttk.Label(ctrl, text="Output format:").grid(
            row=5, column=0, sticky=tk.W, pady=(8, 0)
        )
        self._format_var = tk.StringVar(value="pcapng")
        fmt = ttk.Combobox(
            ctrl,
            textvariable=self._format_var,
            values=["pcapng", "pcap"],
            state="readonly",
            width=8,
        )
        fmt.grid(row=5, column=1, sticky=tk.W, pady=(8, 0))

        # Tool status
        self._tool_label = ttk.Label(ctrl, text="", foreground="gray")
        self._tool_label.grid(row=6, column=0, columnspan=4, sticky=tk.W, pady=(6, 0))

        # Action buttons
        btn_frame = ttk.Frame(ctrl)
        btn_frame.grid(row=7, column=0, columnspan=4, sticky=tk.W, pady=(8, 0))
        self._start_btn = ttk.Button(btn_frame, text="Start", command=self._on_start)
        self._start_btn.pack(side=tk.LEFT, padx=(0, 4))
        self._pause_btn = ttk.Button(
            btn_frame, text="Pause", command=self._on_pause, state=tk.DISABLED
        )
        self._pause_btn.pack(side=tk.LEFT, padx=(0, 4))
        self._cancel_btn = ttk.Button(
            btn_frame, text="Cancel", command=self._on_cancel, state=tk.DISABLED
        )
        self._cancel_btn.pack(side=tk.LEFT)

        # Overall progress bar
        prog_frame = ttk.Frame(self, padding=(8, 4))
        prog_frame.pack(fill=tk.X)
        self._overall_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(prog_frame, variable=self._overall_var, maximum=100).pack(
            fill=tk.X
        )
        self._stats_label = ttk.Label(prog_frame, text="")
        self._stats_label.pack(anchor=tk.W, pady=(2, 0))

        # File table
        table_frame = ttk.Frame(self, padding=(8, 0))
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("filename", "status", "output", "error")
        self._tree = ttk.Treeview(
            table_frame, columns=columns, show="headings", height=10
        )
        self._tree.heading("filename", text="Filename")
        self._tree.heading("status", text="Status")
        self._tree.heading("output", text="Output")
        self._tree.heading("error", text="Error")
        self._tree.column("filename", width=200)
        self._tree.column("status", width=90, anchor=tk.CENTER)
        self._tree.column("output", width=220)
        self._tree.column("error", width=220)

        vsb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Log area
        log_frame = ttk.LabelFrame(self, text="Log", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=False, padx=8, pady=(4, 8))
        self._log_text = tk.Text(log_frame, height=8, state=tk.DISABLED, wrap=tk.WORD)
        log_sb = ttk.Scrollbar(
            log_frame, orient=tk.VERTICAL, command=self._log_text.yview
        )
        self._log_text.configure(yscrollcommand=log_sb.set)
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._on_mode_change()

    # ------------------------------------------------------------------
    # Tool status
    # ------------------------------------------------------------------

    def _report_tools(self) -> None:
        parts = []
        if self._tshark.found:
            parts.append(f"tshark: {self._tshark.version}")
        else:
            parts.append("tshark: NOT FOUND")
        if self._mergecap.found:
            parts.append(f"mergecap: {self._mergecap.version}")
        else:
            parts.append("mergecap: NOT FOUND")
        found = self._tshark.found or self._mergecap.found
        self._tool_label.config(
            text="  |  ".join(parts),
            foreground="green" if found else "red",
        )
        if not self._tshark.found:
            self._append_log(self._tshark.error)
        if not self._mergecap.found:
            self._append_log(self._mergecap.error)

    # ------------------------------------------------------------------
    # Pickers / mode
    # ------------------------------------------------------------------

    def _pick_input(self) -> None:
        path = filedialog.askdirectory(title="Select input folder")
        if path:
            self._input_dir = path
            files = scan_capture_files(path)
            self._in_label.config(
                text=f"{path}   ({len(files)} capture files)", foreground="black"
            )

    def _pick_output(self) -> None:
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self._output_dir = path
            self._out_label.config(text=path, foreground="black")

    def _on_mode_change(self) -> None:
        is_filter = self._mode_var.get() == "filter"
        self._filter_text.config(state=tk.NORMAL if is_filter else tk.DISABLED)

    # ------------------------------------------------------------------
    # Start / Pause / Cancel
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        if not self._input_dir:
            messagebox.showwarning("Missing input", "Please select an input folder.")
            return
        if not self._output_dir:
            messagebox.showwarning("Missing output", "Please select an output folder.")
            return

        files = scan_capture_files(self._input_dir)
        if not files:
            messagebox.showinfo(
                "No files", "No .pcap / .pcapng files found in the input folder."
            )
            return

        mode = self._mode_var.get()
        output_format = (
            OutputFormat.PCAP if self._format_var.get() == "pcap" else OutputFormat.PCAPNG
        )

        if mode == "filter":
            if not self._tshark.found:
                messagebox.showerror("tshark missing", self._tshark.error)
                return
            display_filter = self._filter_text.get("1.0", tk.END).strip()
            if not display_filter:
                messagebox.showwarning(
                    "Empty filter",
                    "Please enter a Wireshark display filter (refusing to copy "
                    "full captures).",
                )
                return
        else:  # merge
            if not self._mergecap.found:
                messagebox.showerror("mergecap missing", self._mergecap.error)
                return
            if len(files) < 2:
                messagebox.showwarning(
                    "Not enough files", "Merge needs at least 2 capture files."
                )
                return
            display_filter = ""

        # Build items and populate table.
        self._items = [
            CaptureFileItem(index=i, input_path=p, filename=os.path.basename(p))
            for i, p in enumerate(files)
        ]
        self._tree.delete(*self._tree.get_children())
        for item in self._items:
            self._tree.insert(
                "",
                tk.END,
                iid=str(item.index),
                values=(item.filename, item.status.value, "", ""),
            )
        self._overall_var.set(0.0)
        self._stats_label.config(text=f"Total: {len(self._items)}")
        self._append_log(f"Loaded {len(self._items)} capture files from {self._input_dir}")

        # Build processor.
        if mode == "filter":
            self._processor = BatchProcessor(
                items=self._items,
                output_dir=self._output_dir,
                display_filter=display_filter,
                tshark_path=self._tshark.path,
                output_format=output_format,
                on_progress=self._on_item_progress,
                on_log=self._on_proc_log,
            )
        else:
            self._processor = MergeProcessor(
                items=self._items,
                output_dir=self._output_dir,
                mergecap_path=self._mergecap.path,
                output_format=output_format,
                on_progress=self._on_item_progress,
                on_log=self._on_proc_log,
            )

        self._start_btn.config(state=tk.DISABLED)
        self._pause_btn.config(
            state=tk.NORMAL if mode == "filter" else tk.DISABLED, text="Pause"
        )
        self._cancel_btn.config(state=tk.NORMAL)
        self._is_paused = False

        self._thread = threading.Thread(target=self._run_worker, daemon=True)
        self._thread.start()

    def _on_pause(self) -> None:
        if self._processor is None:
            return
        self._is_paused = self._processor.toggle_pause()
        self._pause_btn.config(text="Resume" if self._is_paused else "Pause")

    def _on_cancel(self) -> None:
        if self._processor is None:
            return
        self._processor.request_cancel()
        self._append_log("Cancel requested - stopping...")

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------

    def _run_worker(self) -> None:
        assert self._processor is not None
        try:
            stats = self._processor.run()
        except Exception as exc:
            self.after(0, self._append_log, f"Worker failed: {exc}")
            stats = self._processor.current_stats()
        self.after(0, self._on_finished, stats)

    def _on_finished(self, stats: BatchStats) -> None:
        self._start_btn.config(state=tk.NORMAL)
        self._pause_btn.config(state=tk.DISABLED)
        self._cancel_btn.config(state=tk.DISABLED)
        self._overall_var.set(stats.overall_pct)
        self._stats_label.config(
            text=(
                f"Total: {stats.total}  |  Succeeded: {stats.succeeded}  |  "
                f"Failed: {stats.failed}  |  Canceled: {stats.canceled}"
            )
        )
        self._append_log("Batch finished.")

    # ------------------------------------------------------------------
    # Callbacks (worker thread → UI thread)
    # ------------------------------------------------------------------

    def _on_item_progress(self, item: CaptureFileItem) -> None:
        idx = str(item.index)
        fname = item.filename
        status = item.status.value
        out = os.path.basename(item.output_path) if item.output_path else ""
        error = item.error
        self.after(0, self._update_row, idx, fname, status, out, error)

    def _on_proc_log(self, msg: str) -> None:
        self.after(0, self._append_log, msg)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def _update_row(
        self, iid: str, filename: str, status: str, output: str, error: str
    ) -> None:
        try:
            self._tree.item(iid, values=(filename, status, output, error))
        except tk.TclError:
            pass

        done = sum(
            1
            for it in self._items
            if it.status in (FileStatus.DONE, FileStatus.FAILED, FileStatus.CANCELED)
        )
        total = len(self._items)
        if total:
            self._overall_var.set((done / total) * 100)
            self._stats_label.config(
                text=(
                    f"Total: {total}  |  "
                    f"Succeeded: {sum(1 for i in self._items if i.status == FileStatus.DONE)}  |  "
                    f"Failed: {sum(1 for i in self._items if i.status == FileStatus.FAILED)}  |  "
                    f"Canceled: {sum(1 for i in self._items if i.status == FileStatus.CANCELED)}  |  "
                    f"Remaining: {total - done}"
                )
            )

    def _append_log(self, msg: str) -> None:
        self._log_text.config(state=tk.NORMAL)
        self._log_text.insert(tk.END, msg + "\n")
        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)
