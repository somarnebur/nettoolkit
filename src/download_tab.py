"""URL Downloader tab - concurrent download UI as an embeddable frame."""

from __future__ import annotations

import asyncio
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import filedialog, messagebox, ttk

from downloader import DownloadEngine
from models import DownloadItem, DownloadStatus
from theme import PALETTE, style_tree_tags
from utils import UrlEntry, parse_url_entries, parse_url_entries_file

CHECKED = "\u2611"  # ballot box with check
UNCHECKED = "\u2610"  # empty ballot box


def _status_tag(status: str) -> str:
    """Map a status label to a Treeview color tag."""
    return {
        "Done": "done",
        "Failed": "failed",
        "Downloading": "active",
        "Canceled": "canceled",
        "Paused": "canceled",
    }.get(status, "")


class DownloadTab(ttk.Frame):
    """Concurrent URL file downloader, embeddable in a Notebook."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, padding=(0, 12, 0, 0))

        # State
        self._url_file: str = ""
        self._output_dir: str = ""
        self._engine: DownloadEngine | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._is_paused = False
        self._items: list[DownloadItem] = []
        self._entries: list[UrlEntry] = []
        self._running = False
        self._sort_col: str = ""
        self._sort_reverse = False

        # Throughput sampling (real-time combined speed).
        self._speed_samples: deque[float] = deque(maxlen=180)
        self._sample_after: str | None = None
        self._last_sample_time = 0.0
        self._last_sample_bytes = 0
        self._peak_speed = 0.0
        self._job_start_time = 0.0

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ── Configuration card ────────────────────────────────────────
        card = ttk.Frame(self, style="Card.TFrame", padding=16)
        card.pack(fill=tk.X)
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="Configuration", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 12)
        )

        # URL file selection
        ttk.Label(card, text="URL list file", style="Muted.TLabel").grid(
            row=1, column=0, sticky=tk.W, padx=(0, 12)
        )
        self._url_label = ttk.Label(card, text="No file selected", style="Muted.TLabel")
        self._url_label.grid(row=1, column=1, sticky=tk.W)
        ttk.Button(card, text="Browse…", command=self._pick_url_file).grid(
            row=1, column=2, sticky=tk.E
        )

        # Paste URLs directly (alternative to a file)
        ttk.Label(card, text="Or paste URLs", style="Muted.TLabel").grid(
            row=2, column=0, sticky=tk.NW, padx=(0, 12), pady=(10, 0)
        )
        self._paste_text = tk.Text(
            card, height=4, wrap=tk.NONE, relief="flat",
            background=PALETTE["surface_alt"], foreground=PALETTE["text"],
            borderwidth=1, padx=8, pady=6, font=("Cascadia Mono", 9),
            highlightthickness=1, highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["accent"], insertbackground=PALETTE["text"],
        )
        self._paste_text.grid(row=2, column=1, columnspan=2, sticky=tk.EW, pady=(10, 0))
        ttk.Label(
            card, text="One URL per line. Takes priority over the file above.",
            style="Muted.TLabel",
        ).grid(row=3, column=1, columnspan=2, sticky=tk.W, pady=(4, 0))

        # Output folder selection
        ttk.Label(card, text="Output folder", style="Muted.TLabel").grid(
            row=4, column=0, sticky=tk.W, padx=(0, 12), pady=(10, 0)
        )
        self._out_label = ttk.Label(card, text="No folder selected", style="Muted.TLabel")
        self._out_label.grid(row=4, column=1, sticky=tk.W, pady=(10, 0))
        ttk.Button(card, text="Browse…", command=self._pick_output).grid(
            row=4, column=2, sticky=tk.E, pady=(10, 0)
        )

        # Concurrency spinner
        ttk.Label(card, text="Simultaneous downloads", style="Muted.TLabel").grid(
            row=5, column=0, sticky=tk.W, padx=(0, 12), pady=(10, 0)
        )
        self._concurrency_var = tk.IntVar(value=5)
        ttk.Spinbox(
            card, from_=1, to=50, textvariable=self._concurrency_var, width=6
        ).grid(row=5, column=1, sticky=tk.W, pady=(10, 0))

        # Connections-per-file spinner (parallel range segments for big files)
        conn_frame = ttk.Frame(card, style="Card.TFrame")
        conn_frame.grid(row=5, column=2, sticky=tk.E, pady=(10, 0))
        ttk.Label(conn_frame, text="Connections/file", style="Muted.TLabel").pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self._conns_per_file_var = tk.IntVar(value=4)
        ttk.Spinbox(
            conn_frame, from_=1, to=16, textvariable=self._conns_per_file_var, width=5
        ).pack(side=tk.LEFT)

        # Action buttons
        btn_frame = ttk.Frame(card, style="Card.TFrame")
        btn_frame.grid(row=6, column=0, columnspan=3, sticky=tk.W, pady=(16, 0))
        self._load_btn = ttk.Button(
            btn_frame, text="Load list", command=self._on_load_list
        )
        self._load_btn.pack(side=tk.LEFT, padx=(0, 8))
        self._start_btn = ttk.Button(
            btn_frame, text="Start download", style="Accent.TButton", command=self._on_start
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

        # ── Progress card ─────────────────────────────────────────────
        prog = ttk.Frame(self, style="Card.TFrame", padding=(16, 12))
        prog.pack(fill=tk.X, pady=(12, 0))
        self._overall_var = tk.DoubleVar(value=0.0)
        ttk.Progressbar(
            prog, variable=self._overall_var, maximum=100,
            style="Horizontal.TProgressbar",
        ).pack(fill=tk.X)
        self._stats_label = ttk.Label(prog, text="Idle", style="Muted.TLabel")
        self._stats_label.pack(anchor=tk.W, pady=(8, 0))

        # ── Throughput card ───────────────────────────────────────────
        thr = ttk.Frame(self, style="Card.TFrame", padding=(16, 12))
        thr.pack(fill=tk.X, pady=(12, 0))
        thr_head = ttk.Frame(thr, style="Card.TFrame")
        thr_head.pack(fill=tk.X)
        ttk.Label(thr_head, text="Throughput", style="Heading.TLabel").pack(
            side=tk.LEFT
        )
        self._speed_label = ttk.Label(
            thr_head, text="0 B/s", style="Heading.TLabel"
        )
        self._speed_label.pack(side=tk.RIGHT)
        self._peak_label = ttk.Label(thr, text="Peak: 0 B/s", style="Muted.TLabel")
        self._peak_label.pack(anchor=tk.W, pady=(2, 6))
        self._chart = tk.Canvas(
            thr, height=110, highlightthickness=0,
            background=PALETTE["surface_alt"],
        )
        self._chart.pack(fill=tk.X)
        self._chart.bind("<Configure>", lambda _e: self._draw_chart())

        # ── Download table ────────────────────────────────────────────
        table_frame = ttk.Frame(self, style="Card.TFrame", padding=(12, 12))
        table_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        # Selection toolbar
        sel_bar = ttk.Frame(table_frame, style="Card.TFrame")
        sel_bar.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(sel_bar, text="Files", style="Heading.TLabel").pack(side=tk.LEFT)
        self._sel_count_label = ttk.Label(
            sel_bar, text="Paste URLs and click Load list", style="Muted.TLabel"
        )
        self._sel_count_label.pack(side=tk.LEFT, padx=(12, 0))

        tree_container = ttk.Frame(table_frame, style="Card.TFrame")
        tree_container.pack(fill=tk.BOTH, expand=True)

        columns = ("sel", "role", "filename", "status", "progress", "bytes", "error")
        self._tree = ttk.Treeview(
            tree_container, columns=columns, show="headings", height=10
        )
        self._tree.heading("sel", text="\u2713", command=self._toggle_all)
        self._tree.heading(
            "role", text="Role instance", command=lambda: self._sort_by("role")
        )
        self._tree.heading(
            "filename", text="Filename", command=lambda: self._sort_by("filename")
        )
        self._tree.heading(
            "status", text="Status", command=lambda: self._sort_by("status")
        )
        self._tree.heading("progress", text="Progress %")
        self._tree.heading("bytes", text="Bytes")
        self._tree.heading("error", text="Error")

        self._tree.column("sel", width=34, minwidth=34, stretch=False, anchor=tk.CENTER)
        self._tree.column("role", width=220)
        self._tree.column("filename", width=220)
        self._tree.column("status", width=90, anchor=tk.CENTER)
        self._tree.column("progress", width=80, anchor=tk.CENTER)
        self._tree.column("bytes", width=100, anchor=tk.E)
        self._tree.column("error", width=160)
        style_tree_tags(self._tree)
        self._tree.bind("<Button-1>", self._on_tree_click)

        vsb = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # ── Log area ─────────────────────────────────────────────────
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

    # ------------------------------------------------------------------
    # File / folder pickers
    # ------------------------------------------------------------------

    def _pick_url_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select URL list",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self._url_file = path
            self._url_label.config(text=path, style="Card.TLabel")

    def _pick_output(self) -> None:
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self._output_dir = path
            self._out_label.config(text=path, style="Card.TLabel")

    # ------------------------------------------------------------------
    # List loading / selection / sorting
    # ------------------------------------------------------------------

    def _on_load_list(self) -> None:
        """Parse pasted URLs (or the file) and preview them for selection."""
        if self._running:
            return
        pasted = self._paste_text.get("1.0", tk.END).strip()
        if pasted:
            entries = parse_url_entries(pasted)
            source = "pasted list"
        elif self._url_file:
            try:
                entries = parse_url_entries_file(self._url_file)
            except Exception as exc:
                messagebox.showerror("Error", f"Cannot read URL file:\n{exc}")
                return
            source = self._url_file
        else:
            messagebox.showwarning(
                "Missing input",
                "Paste one or more URLs, or select a URL file first.",
            )
            return

        if not entries:
            messagebox.showinfo("Empty", "No URLs found in the input.")
            return

        self._populate_list(entries)
        self._append_log(f"Loaded {len(entries)} URLs from {source}")

    def _populate_list(self, entries: list[UrlEntry]) -> None:
        """Fill the table with every entry, all checked by default."""
        self._entries = list(entries)
        self._sort_col = ""
        self._tree.delete(*self._tree.get_children())
        for i, entry in enumerate(entries):
            self._tree.insert(
                "",
                tk.END,
                iid=str(i),
                values=(CHECKED, entry.role_instance, "", "", "", "", ""),
                tags=("even" if i % 2 else "odd",),
            )
        self._update_sel_count()

    def _on_tree_click(self, event: tk.Event) -> str | None:
        """Toggle a row's checkbox when its select column is clicked."""
        if self._running:
            return None
        if self._tree.identify_region(event.x, event.y) != "cell":
            return None
        if self._tree.identify_column(event.x) != "#1":
            return None
        row = self._tree.identify_row(event.y)
        if not row:
            return None
        current = self._tree.set(row, "sel")
        self._tree.set(row, "sel", UNCHECKED if current == CHECKED else CHECKED)
        self._update_sel_count()
        return "break"

    def _toggle_all(self) -> None:
        """Header checkbox: check all rows, or uncheck all if already full."""
        if self._running:
            return
        rows = self._tree.get_children()
        if not rows:
            return
        all_checked = all(self._tree.set(iid, "sel") == CHECKED for iid in rows)
        new_state = UNCHECKED if all_checked else CHECKED
        for iid in rows:
            self._tree.set(iid, "sel", new_state)
        self._update_sel_count()

    def _selected_entries(self) -> list[UrlEntry]:
        return [
            self._entries[int(iid)]
            for iid in self._tree.get_children()
            if self._tree.set(iid, "sel") == CHECKED
        ]

    def _update_sel_count(self) -> None:
        rows = self._tree.get_children()
        if not rows:
            self._sel_count_label.config(text="Paste URLs and click Load list")
            return
        selected = sum(1 for iid in rows if self._tree.set(iid, "sel") == CHECKED)
        self._sel_count_label.config(text=f"{selected} of {len(rows)} selected")

    def _sort_by(self, col: str) -> None:
        """Sort table rows by a column, toggling direction on repeat clicks."""
        if self._running:
            return
        self._sort_reverse = not self._sort_reverse if self._sort_col == col else False
        self._sort_col = col
        rows = [(self._tree.set(iid, col).lower(), iid) for iid in self._tree.get_children()]
        rows.sort(reverse=self._sort_reverse)
        for pos, (_, iid) in enumerate(rows):
            self._tree.move(iid, "", pos)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        if not self._output_dir:
            messagebox.showwarning(
                "Missing output", "Please select an output folder first."
            )
            return

        # Auto-load from paste/file if the user hasn't clicked Load list yet.
        if not self._tree.get_children():
            self._on_load_list()
            if not self._tree.get_children():
                return

        selected = self._selected_entries()
        if not selected:
            messagebox.showinfo(
                "Nothing selected",
                "Please tick at least one file to download.",
            )
            return

        # Build DownloadItem list from the chosen entries and rebuild table.
        self._items = [
            DownloadItem(index=i, url=e.url, role_instance=e.role_instance)
            for i, e in enumerate(selected)
        ]
        self._entries = list(selected)
        self._tree.delete(*self._tree.get_children())
        for item in self._items:
            self._tree.insert(
                "",
                tk.END,
                iid=str(item.index),
                values=(
                    CHECKED, item.role_instance, "",
                    item.status.value, "0", "", "",
                ),
                tags=("even" if item.index % 2 else "odd",),
            )
        self._update_sel_count()
        self._overall_var.set(0.0)
        self._stats_label.config(text=f"Total: {len(self._items)}")
        self._append_log(f"Downloading {len(self._items)} selected file(s)")

        # Disable start, enable pause/cancel.
        self._running = True
        self._start_btn.config(state=tk.DISABLED)
        self._load_btn.config(state=tk.DISABLED)
        self._pause_btn.config(state=tk.NORMAL)
        self._cancel_btn.config(state=tk.NORMAL)
        self._is_paused = False
        self._pause_btn.config(text="Pause")

        # Create engine.
        concurrency = self._concurrency_var.get()
        self._engine = DownloadEngine(
            items=self._items,
            output_dir=self._output_dir,
            concurrency=concurrency,
            connections_per_file=self._conns_per_file_var.get(),
            on_progress=self._on_item_progress,
            on_log=self._on_engine_log,
        )

        # Run downloads in a background thread with its own event-loop.
        self._job_start_time = time.monotonic()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        self._start_throughput()

    def _on_pause(self) -> None:
        if self._engine is None:
            return
        self._is_paused = self._engine.toggle_pause()
        self._pause_btn.config(text="Resume" if self._is_paused else "Pause")

    def _on_cancel(self) -> None:
        if self._engine is None:
            return
        self._engine.request_cancel()
        self._append_log("Cancel requested - stopping downloads...")

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        assert self._loop is not None and self._engine is not None
        asyncio.set_event_loop(self._loop)
        try:
            stats = self._loop.run_until_complete(self._engine.run())
        except Exception as exc:
            self.after(0, self._append_log, f"Download worker failed: {exc}")
            stats = self._engine.current_stats()
        finally:
            self._loop.close()
        # Notify UI that we're done.
        self.after(0, self._on_finished, stats)

    def _on_finished(self, stats) -> None:
        self._running = False
        self._stop_throughput()
        self._start_btn.config(state=tk.NORMAL)
        self._load_btn.config(state=tk.NORMAL)
        self._pause_btn.config(state=tk.DISABLED)
        self._cancel_btn.config(state=tk.DISABLED)
        self._overall_var.set(stats.overall_pct)
        self._stats_label.config(
            text=(
                f"Total: {stats.total}  |  Done: {stats.completed}  |  "
                f"Failed: {stats.failed}  |  Canceled: {stats.canceled}"
            )
        )
        self._report_job_summary()

    def _report_job_summary(self) -> None:
        """Log duration, data transferred, and average/peak speed for the run."""
        duration = max(0.0, time.monotonic() - self._job_start_time)
        transferred = sum(it.downloaded_bytes for it in self._items)
        avg_speed = transferred / duration if duration > 0 else 0.0
        self._append_log("All downloads finished.")
        self._append_log(
            "Summary  \u2014  "
            f"duration: {self._fmt_duration(duration)}  |  "
            f"transferred: {self._fmt_bytes(transferred)}  |  "
            f"avg speed: {self._fmt_bytes(int(avg_speed))}/s  |  "
            f"peak: {self._fmt_bytes(int(self._peak_speed))}/s"
        )

    # ------------------------------------------------------------------
    # Callbacks (called from asyncio thread → marshalled to UI thread)
    # ------------------------------------------------------------------

    def _on_item_progress(self, item: DownloadItem) -> None:
        """Called from the download thread; schedule a UI update."""
        idx = str(item.index)
        fname = item.filename
        url = item.url
        status = item.status.value
        pct = f"{item.progress_pct:.0f}"
        dl_bytes = self._fmt_bytes(item.downloaded_bytes)
        error = item.error
        self.after(0, self._update_row, idx, fname, url, status, pct, dl_bytes, error)

    def _on_engine_log(self, msg: str) -> None:
        self.after(0, self._append_log, msg)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def _update_row(
        self,
        iid: str,
        filename: str,
        url: str,
        status: str,
        pct: str,
        dl_bytes: str,
        error: str,
    ) -> None:
        try:
            stripe = "even" if int(iid) % 2 else "odd"
            sel = self._tree.set(iid, "sel") or CHECKED
            role = self._tree.set(iid, "role")
            self._tree.item(
                iid,
                values=(sel, role, filename, status, pct, dl_bytes, error),
                tags=(stripe, _status_tag(status)),
            )
        except tk.TclError:
            pass  # row may have been removed

        # Recompute overall progress.
        done = sum(
            1
            for it in self._items
            if it.status
            in (DownloadStatus.DONE, DownloadStatus.FAILED, DownloadStatus.CANCELED)
        )
        total = len(self._items)
        if total:
            self._overall_var.set((done / total) * 100)
            self._stats_label.config(
                text=(
                    f"Total: {total}  |  Done: {sum(1 for i in self._items if i.status == DownloadStatus.DONE)}  |  "
                    f"Failed: {sum(1 for i in self._items if i.status == DownloadStatus.FAILED)}  |  "
                    f"Canceled: {sum(1 for i in self._items if i.status == DownloadStatus.CANCELED)}  |  "
                    f"Remaining: {total - done}"
                )
            )

    def _append_log(self, msg: str) -> None:
        self._log_text.config(state=tk.NORMAL)
        self._log_text.insert(tk.END, msg + "\n")
        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Real-time throughput chart
    # ------------------------------------------------------------------

    _SAMPLE_MS = 1000  # sampling interval

    def _start_throughput(self) -> None:
        self._speed_samples.clear()
        self._peak_speed = 0.0
        self._last_sample_time = time.monotonic()
        self._last_sample_bytes = sum(it.downloaded_bytes for it in self._items)
        self._speed_label.config(text="0 B/s")
        self._peak_label.config(text="Peak: 0 B/s")
        self._draw_chart()
        self._sample_after = self.after(self._SAMPLE_MS, self._sample_throughput)

    def _stop_throughput(self) -> None:
        if self._sample_after is not None:
            try:
                self.after_cancel(self._sample_after)
            except Exception:
                pass
            self._sample_after = None
        self._sample_throughput(final=True)

    def _sample_throughput(self, final: bool = False) -> None:
        now = time.monotonic()
        total = sum(it.downloaded_bytes for it in self._items)
        dt = now - self._last_sample_time
        speed = (total - self._last_sample_bytes) / dt if dt > 0 else 0.0
        speed = max(0.0, speed)
        self._last_sample_time = now
        self._last_sample_bytes = total

        self._speed_samples.append(speed)
        self._peak_speed = max(self._peak_speed, speed)
        self._speed_label.config(text=f"{self._fmt_bytes(int(speed))}/s")
        self._peak_label.config(
            text=f"Peak: {self._fmt_bytes(int(self._peak_speed))}/s"
        )
        self._draw_chart()

        if not final and self._running:
            self._sample_after = self.after(self._SAMPLE_MS, self._sample_throughput)

    def _draw_chart(self) -> None:
        c = self._chart
        c.delete("all")
        width = c.winfo_width() or c.winfo_reqwidth()
        height = int(c.cget("height"))
        pad = 6
        plot_w = max(1, width - 2 * pad)
        plot_h = max(1, height - 2 * pad)
        baseline = height - pad

        # Baseline axis.
        c.create_line(
            pad, baseline, width - pad, baseline, fill=PALETTE["border"]
        )

        samples = list(self._speed_samples)
        if len(samples) < 2:
            return

        peak = max(samples) or 1.0
        n = len(samples)
        step = plot_w / (n - 1)
        points: list[float] = []
        for i, s in enumerate(samples):
            x = pad + i * step
            y = baseline - (s / peak) * plot_h
            points.extend((x, y))

        # Filled area under the curve.
        area = [pad, baseline, *points, width - pad, baseline]
        c.create_polygon(area, fill=PALETTE["track"], outline="")
        c.create_line(*points, fill=PALETTE["accent"], width=2, smooth=True)

    @staticmethod
    def _fmt_bytes(n: int) -> str:
        if n < 1024:
            return f"{n} B"
        elif n < 1024 * 1024:
            return f"{n / 1024:.1f} KB"
        elif n < 1024 * 1024 * 1024:
            return f"{n / (1024 * 1024):.1f} MB"
        else:
            return f"{n / (1024 * 1024 * 1024):.2f} GB"

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.1f}s"
        total = int(round(seconds))
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h {m}m {s}s"
        return f"{m}m {s}s"
