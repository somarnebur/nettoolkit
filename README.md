# Concurrent URL File Downloader

A desktop application that downloads files from a user-provided list of URLs with configurable concurrency, a selectable output folder, and a live progress UI.

## Tech Stack

- **Python 3.12+**
- **httpx** – async HTTP downloads
- **tkinter** – cross-platform GUI (included with Python)

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

1. Click **Select URL file** and pick a `.txt` file containing one URL per line.
2. Click **Select output folder** to choose where downloaded files are saved.
3. Set the **Simultaneous downloads** value (1–50).
4. Click **Start** to begin downloading.
5. Use **Pause / Resume** and **Cancel** as needed.
6. Watch per-file progress in the table and timestamped messages in the log area.

### URL File Format

```text
# Lines starting with # are comments
https://example.com/file1.zip
https://example.com/file2.pdf

# Blank lines are ignored
https://example.com/file3.tar.gz
```

## Running Tests

```bash
pytest tests/ -v
```

## Project Structure

```
EverflowDownload/
├── README.md
├── requirements.txt
├── urls.txt              # Sample URL list
├── src/
│   ├── app.py            # Main GUI entry-point
│   ├── downloader.py     # Async download engine
│   ├── models.py         # Data classes (DownloadItem, DownloadStats)
│   └── utils.py          # URL parsing, filename helpers
└── tests/
    └── test_utils.py     # Unit tests (pytest)
```

## Features

- Configurable concurrency via `asyncio.Semaphore`
- Streaming (chunked) downloads – memory-efficient for large files
- Filename derived from `Content-Disposition` header, URL path, or fallback
- Duplicate filename handling (`file (1).ext`, `file (2).ext`, …)
- Temp-file strategy: partial downloads are cleaned up on failure
- Automatic retry (up to 2 attempts with backoff)
- Invalid URLs are reported and skipped
- UI stays responsive (downloads run in a background thread)
