"""NetToolkit - unified desktop tool: URL downloader + PCAP filter/merge.

Combines two utilities into a single tabbed application:
  * URL Downloader    - concurrent file downloads from a URL list (httpx).
  * PCAP Filter/Merge - batch filter (tshark) or merge (mergecap) captures.
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import ttk

# Ensure ``src/`` is on the path so sibling modules / sub-packages import.
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# The PCAP tab only needs stdlib + an external tshark/mergecap install.
from pcap.tab import PcapTab
from theme import PALETTE, apply_theme

# The download tab needs httpx; import it defensively so a missing dependency
# does not take down the whole application (the PCAP tab still works).
try:
    import httpx  # noqa: F401 - presence check only
    from download_tab import DownloadTab

    _DOWNLOAD_IMPORT_ERROR = ""
except ImportError as exc:
    DownloadTab = None  # type: ignore[assignment]
    _DOWNLOAD_IMPORT_ERROR = str(exc)


class App(tk.Tk):
    """Main application window hosting both tools with a segmented tab bar."""

    def __init__(self) -> None:
        super().__init__()
        self.title("NetToolkit - Downloader & PCAP Filter")
        self.geometry("1040x740")
        self.minsize(860, 600)

        apply_theme(self)
        self._build_header()

        body = ttk.Frame(self, padding=(14, 12, 14, 14))
        body.pack(fill=tk.BOTH, expand=True)

        # Build the two tool panels.
        container = ttk.Frame(body)
        if DownloadTab is not None:
            download_panel: tk.Widget = DownloadTab(container)
        else:
            download_panel = self._missing_dep_tab(container, _DOWNLOAD_IMPORT_ERROR)
        pcap_panel = PcapTab(container)

        self._panels = {"download": download_panel, "pcap": pcap_panel}

        # Segmented tab bar — two buttons forced to exactly 50% width each.
        self._tab_buttons: dict[str, tk.Button] = {}
        tabbar = ttk.Frame(body)
        tabbar.pack(fill=tk.X)
        for col, (key, label) in enumerate(
            (("download", "Downloader"), ("pcap", "PCAP Filter / Merge"))
        ):
            btn = tk.Button(
                tabbar,
                text=label,
                relief="flat",
                borderwidth=0,
                cursor="hand2",
                pady=11,
                font=("Segoe UI", 10, "bold"),
                command=lambda k=key: self._select_tab(k),
            )
            btn.grid(row=0, column=col, sticky="nsew", padx=(0, 1) if col == 0 else (1, 0))
            tabbar.columnconfigure(col, weight=1, uniform="tabs")
            self._tab_buttons[key] = btn

        # Panels share one cell; the selected one is raised.
        container.pack(fill=tk.BOTH, expand=True, pady=(0, 0))
        for panel in self._panels.values():
            panel.grid(row=0, column=0, sticky="nsew")
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        self._select_tab("download")

    def _select_tab(self, key: str) -> None:
        p = PALETTE
        for k, btn in self._tab_buttons.items():
            selected = k == key
            btn.configure(
                background=p["accent"] if selected else p["track"],
                foreground="#ffffff" if selected else p["muted"],
                activebackground=p["accent_hover"] if selected else "#d6dde6",
                activeforeground="#ffffff" if selected else p["text"],
            )
        self._panels[key].tkraise()

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Header.TFrame", padding=(20, 14))
        header.pack(fill=tk.X)
        ttk.Label(header, text="NetToolkit", style="AppTitle.TLabel").pack(anchor=tk.W)
        ttk.Label(
            header,
            text="Concurrent URL downloads  ·  Wireshark PCAP filter & merge",
            style="AppSubtitle.TLabel",
        ).pack(anchor=tk.W, pady=(2, 0))
        tk.Frame(self, height=3, bg=PALETTE["accent"]).pack(fill=tk.X)

    @staticmethod
    def _missing_dep_tab(master: tk.Misc, error: str) -> ttk.Frame:
        frame = ttk.Frame(master, style="Card.TFrame", padding=24)
        msg = (
            "The URL Downloader requires the 'httpx' package, which is not "
            f"installed.\n\nImport error: {error}\n\n"
            "Install dependencies with:\n    pip install -r requirements.txt"
        )
        ttk.Label(
            frame, text=msg, justify=tk.LEFT, style="Danger.TLabel"
        ).pack(anchor=tk.W)
        return frame


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
