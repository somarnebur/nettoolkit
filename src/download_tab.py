"""URL Downloader tab - concurrent download UI as an embeddable frame."""

from __future__ import annotations

import asyncio
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from downloader import DownloadEngine
from models import DownloadItem, DownloadStatus
from theme import PALETTE, style_tree_tags
from utils import parse_url_file


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

        # Output folder selection
        ttk.Label(card, text="Output folder", style="Muted.TLabel").grid(
            row=2, column=0, sticky=tk.W, padx=(0, 12), pady=(10, 0)
        )
        self._out_label = ttk.Label(card, text="No folder selected", style="Muted.TLabel")
        self._out_label.grid(row=2, column=1, sticky=tk.W, pady=(10, 0))
        ttk.Button(card, text="Browse…", command=self._pick_output).grid(
            row=2, column=2, sticky=tk.E, pady=(10, 0)
        )

        # Concurrency spinner
        ttk.Label(card, text="Simultaneous downloads", style="Muted.TLabel").grid(
            row=3, column=0, sticky=tk.W, padx=(0, 12), pady=(10, 0)
        )
        self._concurrency_var = tk.IntVar(value=5)
        ttk.Spinbox(
            card, from_=1, to=50, textvariable=self._concurrency_var, width=6
        ).grid(row=3, column=1, sticky=tk.W, pady=(10, 0))

        # Action buttons
        btn_frame = ttk.Frame(card, style="Card.TFrame")
        btn_frame.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=(16, 0))
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

        # ── Download table ────────────────────────────────────────────
        table_frame = ttk.Frame(self, style="Card.TFrame", padding=(12, 12))
        table_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        columns = ("filename", "url", "status", "progress", "bytes", "error")
        self._tree = ttk.Treeview(
            table_frame, columns=columns, show="headings", height=10
        )
        self._tree.heading("filename", text="Filename")
        self._tree.heading("url", text="URL")
        self._tree.heading("status", text="Status")
        self._tree.heading("progress", text="Progress %")
        self._tree.heading("bytes", text="Bytes")
        self._tree.heading("error", text="Error")

        self._tree.column("filename", width=160)
        self._tree.column("url", width=280)
        self._tree.column("status", width=90, anchor=tk.CENTER)
        self._tree.column("progress", width=80, anchor=tk.CENTER)
        self._tree.column("bytes", width=100, anchor=tk.E)
        self._tree.column("error", width=160)
        style_tree_tags(self._tree)

        vsb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self._tree.yview)
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
    # Button handlers
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        if not self._url_file:
            messagebox.showwarning("Missing input", "Please select a URL file first.")
            return
        if not self._output_dir:
            messagebox.showwarning(
                "Missing output", "Please select an output folder first."
            )
            return

        try:
            urls = parse_url_file(self._url_file)
        except Exception as exc:
            messagebox.showerror("Error", f"Cannot read URL file:\n{exc}")
            return

        if not urls:
            messagebox.showinfo("Empty", "The URL file contains no URLs.")
            return

        # Build DownloadItem list and populate table.
        self._items = [DownloadItem(index=i, url=u) for i, u in enumerate(urls)]
        self._tree.delete(*self._tree.get_children())
        for item in self._items:
            self._tree.insert(
                "",
                tk.END,
                iid=str(item.index),
                values=("", item.url, item.status.value, "0", "", ""),
                tags=("even" if item.index % 2 else "odd",),
            )
        self._overall_var.set(0.0)
        self._stats_label.config(text=f"Total: {len(self._items)}")
        self._append_log(f"Loaded {len(self._items)} URLs from {self._url_file}")

        # Disable start, enable pause/cancel.
        self._start_btn.config(state=tk.DISABLED)
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
            on_progress=self._on_item_progress,
            on_log=self._on_engine_log,
        )

        # Run downloads in a background thread with its own event-loop.
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

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
        self._start_btn.config(state=tk.NORMAL)
        self._pause_btn.config(state=tk.DISABLED)
        self._cancel_btn.config(state=tk.DISABLED)
        self._overall_var.set(stats.overall_pct)
        self._stats_label.config(
            text=(
                f"Total: {stats.total}  |  Done: {stats.completed}  |  "
                f"Failed: {stats.failed}  |  Canceled: {stats.canceled}"
            )
        )
        self._append_log("All downloads finished.")

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
            self._tree.item(
                iid,
                values=(filename, url, status, pct, dl_bytes, error),
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
