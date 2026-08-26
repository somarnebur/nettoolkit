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

# Theme lives at src/theme.py (added to sys.path by the app entry point).
from theme import PALETTE, style_tree_tags


def _status_tag(status: str) -> str:
    """Map a status label to a Treeview color tag."""
    return {
        "Done": "done",
        "Failed": "failed",
        "Processing": "active",
        "Canceled": "canceled",
    }.get(status, "")


class PcapTab(ttk.Frame):
    """Batch PCAP filter (tshark) / merge (mergecap), embeddable in a Notebook."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, padding=(0, 12, 0, 0))

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
        card = ttk.Frame(self, style="Card.TFrame", padding=16)
        card.pack(fill=tk.X)
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="Configuration", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 12)
        )

        # Input folder
        ttk.Label(card, text="Input folder", style="Muted.TLabel").grid(
            row=1, column=0, sticky=tk.W, padx=(0, 12)
        )
        self._in_label = ttk.Label(card, text="No folder selected", style="Muted.TLabel")
        self._in_label.grid(row=1, column=1, sticky=tk.W)
        ttk.Button(card, text="Browse…", command=self._pick_input).grid(
            row=1, column=2, sticky=tk.E
        )

        # Output folder
        ttk.Label(card, text="Output folder", style="Muted.TLabel").grid(
            row=2, column=0, sticky=tk.W, padx=(0, 12), pady=(10, 0)
        )
        self._out_label = ttk.Label(card, text="No folder selected", style="Muted.TLabel")
        self._out_label.grid(row=2, column=1, sticky=tk.W, pady=(10, 0))
        ttk.Button(card, text="Browse…", command=self._pick_output).grid(
            row=2, column=2, sticky=tk.E, pady=(10, 0)
        )

        # Mode: Filter vs Merge
        ttk.Label(card, text="Mode", style="Muted.TLabel").grid(
            row=3, column=0, sticky=tk.W, padx=(0, 12), pady=(12, 0)
        )
        self._mode_var = tk.StringVar(value="filter")
        mode_frame = ttk.Frame(card, style="Card.TFrame")
        mode_frame.grid(row=3, column=1, columnspan=2, sticky=tk.W, pady=(12, 0))
        ttk.Radiobutton(
            mode_frame,
            text="Filter (tshark)",
            style="Card.TRadiobutton",
            variable=self._mode_var,
            value="filter",
            command=self._on_mode_change,
        ).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Radiobutton(
            mode_frame,
            text="Merge (mergecap)",
            style="Card.TRadiobutton",
            variable=self._mode_var,
            value="merge",
            command=self._on_mode_change,
        ).pack(side=tk.LEFT)

        # Display filter
        ttk.Label(card, text="Display filter", style="Muted.TLabel").grid(
            row=4, column=0, sticky=tk.NW, pady=(12, 0)
        )
        self._filter_text = tk.Text(
            card, height=2, width=50, wrap=tk.WORD, relief="flat",
            background=PALETTE["surface_alt"], foreground=PALETTE["text"],
            borderwidth=1, padx=8, pady=6, font=("Cascadia Mono", 9),
            highlightthickness=1, highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["accent"], insertbackground=PALETTE["text"],
        )
        self._filter_text.grid(row=4, column=1, columnspan=2, sticky=tk.EW, pady=(12, 0))
        ttk.Label(
            card,
            text="Wireshark display filter, e.g.  ip.addr == 10.0.0.5",
            style="Muted.TLabel",
        ).grid(row=5, column=1, columnspan=2, sticky=tk.W, pady=(4, 0))

        # Output format
        ttk.Label(card, text="Output format", style="Muted.TLabel").grid(
            row=6, column=0, sticky=tk.W, padx=(0, 12), pady=(12, 0)
        )
        self._format_var = tk.StringVar(value="pcapng")
        ttk.Combobox(
            card,
            textvariable=self._format_var,
            values=["pcapng", "pcap"],
            state="readonly",
            width=10,
        ).grid(row=6, column=1, sticky=tk.W, pady=(12, 0))

        # Tool status
        self._tool_label = ttk.Label(card, text="", style="Muted.TLabel")
        self._tool_label.grid(row=7, column=0, columnspan=3, sticky=tk.W, pady=(12, 0))

        # Action buttons
        btn_frame = ttk.Frame(card, style="Card.TFrame")
        btn_frame.grid(row=8, column=0, columnspan=3, sticky=tk.W, pady=(16, 0))
        self._start_btn = ttk.Button(
            btn_frame, text="Start", style="Accent.TButton", command=self._on_start
        )
        self._start_btn.pack(side=tk.LEFT, padx=(0, 8))
        self._pause_btn = ttk.Button(
            btn_frame, text="Pause", command=self._on_pause, state=tk.DISABLED
        )
        self._pause_btn.pack(side=tk.LEFT, padx=(0, 8))
        self._cancel_btn = ttk.Button(
            btn_frame, text="Cancel", style="Danger.TButton",
            command=self._on_cancel, state=tk.DISABLED,
        )
        self._cancel_btn.pack(side=tk.LEFT)

        # Overall progress card
        prog = ttk.Frame(self, style="Card.TFrame", padding=(16, 12))
        prog.pack(fill=tk.X, pady=(12, 0))
        self._overall_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(
            prog, variable=self._overall_var, maximum=100,
            style="Horizontal.TProgressbar",
        ).pack(fill=tk.X)
        self._stats_label = ttk.Label(prog, text="Idle", style="Muted.TLabel")
        self._stats_label.pack(anchor=tk.W, pady=(8, 0))

        # File table
        table_frame = ttk.Frame(self, style="Card.TFrame", padding=(12, 12))
        table_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

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
        style_tree_tags(self._tree)

        vsb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Log area
        log_frame = ttk.Frame(self, style="Card.TFrame", padding=(12, 10))
        log_frame.pack(fill=tk.BOTH, expand=False, pady=(12, 0))
        ttk.Label(log_frame, text="Activity log", style="Heading.TLabel").pack(
            anchor=tk.W, pady=(0, 8)
        )
        log_body = ttk.Frame(log_frame, style="Card.TFrame")
        log_body.pack(fill=tk.BOTH, expand=True)
        self._log_text = tk.Text(
            log_body, height=7, state=tk.DISABLED, wrap=tk.WORD,
            relief="flat", background=PALETTE["surface_alt"],
            foreground=PALETTE["text"], borderwidth=0,
            padx=10, pady=8, font=("Cascadia Mono", 9),
        )
        log_sb = ttk.Scrollbar(
            log_body, orient=tk.VERTICAL, command=self._log_text.yview
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
            text="   ·   ".join(parts),
            style="Success.TLabel" if found else "Danger.TLabel",
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
                text=f"{path}   ({len(files)} capture files)", style="Card.TLabel"
            )

    def _pick_output(self) -> None:
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self._output_dir = path
            self._out_label.config(text=path, style="Card.TLabel")

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
                tags=("even" if item.index % 2 else "odd",),
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
            stripe = "even" if int(iid) % 2 else "odd"
            self._tree.item(
                iid,
                values=(filename, status, output, error),
                tags=(stripe, _status_tag(status)),
            )
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
