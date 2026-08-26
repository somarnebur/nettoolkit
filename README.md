# NetToolkit — URL Downloader & PCAP Filter/Merge

A single desktop application that combines two network utilities in a tabbed UI:

1. **URL Downloader** — downloads files from a user-provided list of URLs with
   configurable concurrency, a selectable output folder, and a live progress UI.
2. **PCAP Filter / Merge** — batch-processes Wireshark capture files
   (`.pcap` / `.pcapng`): apply a display filter with `tshark`, or merge many
   captures into one with `mergecap`.

## Tech Stack

- **Python 3.12+**
- **httpx** – async HTTP downloads (URL Downloader)
- **Wireshark CLI** – `tshark` / `mergecap` (PCAP tab; must be installed separately)
- **tkinter** – cross-platform GUI (included with Python)

## Prerequisites

The URL Downloader works out of the box. The **PCAP Filter / Merge** tab requires
Wireshark's command-line tools (`tshark` and `mergecap`) on your PATH:

```bash
tshark -v
mergecap -v
```

If not found, download Wireshark: <https://www.wireshark.org/download.html>.
On Windows they install alongside Wireshark (typically `C:\Program Files\Wireshark`);
the app also searches common install paths automatically.

## Quick Start

### 1. Create a virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the application

```bash
python src/app.py
```

## Usage

The app opens with two tabs.

### URL Downloader tab

1. Click **Select URL file** and pick a `.txt` file containing one URL per line.
2. Click **Select output folder** to choose where downloaded files are saved.
3. Set the **Simultaneous downloads** value (1–50).
4. Click **Start** to begin downloading.
5. Use **Pause / Resume** and **Cancel** as needed.
6. Watch per-file progress in the table and timestamped messages in the log area.

#### URL File Format

```text
# Lines starting with # are comments
https://example.com/file1.zip
https://example.com/file2.pdf

# Blank lines are ignored
https://example.com/file3.tar.gz
```

### PCAP Filter / Merge tab

1. Click **Input folder** — select a directory containing `.pcap` / `.pcapng` files.
2. Click **Output folder** — choose where results are saved.
3. Choose **Mode**:
   - **Filter (tshark)** — enter a Wireshark display filter; each file is filtered
     to `<name>_filtered.<ext>` (processed one at a time).
   - **Merge (mergecap)** — combines all captures into a single `merged.<ext>`.
4. Pick the **Output format** (`pcapng` or `pcap`).
5. Click **Start**, and use **Pause / Resume** (filter mode) and **Cancel** as needed.

#### Example Display Filters

| Filter | Description |
|---|---|
| `ip.addr == 10.0.0.5` | All traffic to/from a specific IP |
| `http && ip.src == 192.168.1.10` | HTTP traffic from a specific source |
| `tls.handshake.type == 1` | TLS Client Hello messages |
| `tcp.port == 443` | All TCP traffic on port 443 |
| `dns` | All DNS traffic |

The app quotes filters internally — no need to add quotes around the filter.

## Running Tests

```bash
pytest tests/ -v
```

## Project Structure

```
NetToolkit/
├── README.md
├── requirements.txt
├── urls.txt                  # Sample URL list
├── run_gui.pyw               # Double-click launcher (no console)
├── src/
│   ├── app.py                # Unified tabbed GUI entry-point
│   ├── download_tab.py       # URL Downloader tab (frame)
│   ├── downloader.py         # Async download engine (httpx)
│   ├── models.py             # Download data classes
│   ├── utils.py              # URL parsing, filename helpers
│   └── pcap/                 # PCAP filter / merge package
│       ├── tab.py            # PCAP Filter/Merge tab (frame)
│       ├── processor.py      # Batch (tshark) & merge (mergecap) processors
│       ├── tshark.py         # Tool detection & command-arg building
│       ├── models.py         # Capture data classes
│       └── utils.py          # Folder scanning, filename helpers
└── tests/
    ├── test_utils.py         # Download utils/models tests
    ├── test_pcap_utils.py    # PCAP utils/models tests
    └── test_tshark_args.py   # tshark/mergecap arg-building tests
```

## Features

### URL Downloader
- Configurable concurrency via `asyncio.Semaphore`
- Streaming (chunked) downloads – memory-efficient for large files
- Filename derived from `Content-Disposition` header, URL path, or fallback
- Duplicate filename handling (`file (1).ext`, `file (2).ext`, …)
- Temp-file strategy: partial downloads are cleaned up on failure
- Automatic retry (up to 2 attempts with backoff)
- Invalid URLs are reported and skipped

### PCAP Filter / Merge
- Sequential filtering with `tshark -r <in> -Y "<filter>" -w <out> -F <format>`
- Merge many captures into one with `mergecap`
- Automatic `tshark` / `mergecap` detection (PATH + common Windows paths)
- Output-format selection (`pcapng` / `pcap`) and collision-safe output names
- Refuses to run with an empty filter (avoids copying full captures)

### Shared
- UI stays responsive (work runs in background threads)
- Live per-item table and timestamped log; Pause/Cancel support

