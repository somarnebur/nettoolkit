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
    """Main application window hosting both tools in a Notebook."""

    def __init__(self) -> None:
        super().__init__()
        self.title("NetToolkit - Downloader & PCAP Filter")
        self.geometry("980x700")
        self.minsize(820, 560)

        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True)

        if DownloadTab is not None:
            notebook.add(DownloadTab(notebook), text="URL Downloader")
        else:
            notebook.add(
                self._missing_dep_tab(notebook, _DOWNLOAD_IMPORT_ERROR),
                text="URL Downloader",
            )

        notebook.add(PcapTab(notebook), text="PCAP Filter / Merge")

    @staticmethod
    def _missing_dep_tab(master: tk.Misc, error: str) -> ttk.Frame:
        frame = ttk.Frame(master, padding=20)
        msg = (
            "The URL Downloader requires the 'httpx' package, which is not "
            f"installed.\n\nImport error: {error}\n\n"
            "Install dependencies with:\n    pip install -r requirements.txt"
        )
        ttk.Label(frame, text=msg, justify=tk.LEFT, foreground="red").pack(anchor=tk.W)
        return frame


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
