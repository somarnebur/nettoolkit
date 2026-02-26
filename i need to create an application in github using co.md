<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# i need to create an application in github using copilot that is capable of automate downloads. i will provide a file with an uncertain amount of URLS that contain files to be downloaded. i wanna be able to select how many of those urls are downloaded simultaneosly , and also where it will be saved. need a box where i can be updated about the progress. generate a md file i can use as prompt to github copilot

Below is a ready-to-paste Markdown prompt you can give to GitHub Copilot Chat. It’s structured to be specific, broken into steps, and includes clear requirements and acceptance criteria (which improves Copilot output quality).[^1][^2][^3]

```md
# Copilot Prompt: Concurrent URL File Downloader (GitHub repo)

You are GitHub Copilot acting as a senior engineer. Build a small desktop application that downloads files from a user-provided list of URLs, with configurable concurrency, a selectable output folder, and a live progress UI.

## Tech stack (choose one and implement fully)
Preferred: **Python 3.12** + `aiohttp` for async downloads + `tkinter` for UI (no web browser required).
- Keep it cross-platform (Windows/macOS/Linux).
- Use a virtual environment and provide `requirements.txt`.

(If you pick a different stack, explain why and keep it simple + cross-platform.)

## Core user story
As a user, I can:
1. Select a text file containing an unknown number of URLs (one URL per line).
2. Choose an output folder where downloaded files will be saved.
3. Set "Simultaneous downloads" (concurrency) as an integer (min 1, max 50).
4. Start / pause / resume / cancel downloads.
5. See progress updates in the UI (overall + per-file), including:
   - total files, completed, failed, remaining
   - per-file status (Queued / Downloading / Done / Failed / Canceled)
   - bytes downloaded (if server provides Content-Length), speed is optional
   - a scrolling log/console area with timestamped messages

## Input format
- The URL file is plain text, one URL per line.
- Ignore blank lines and lines starting with `#`.
- Trim whitespace.
- Validate URL scheme is http/https; mark invalid URLs as failed and continue.

## Download rules
- Use streaming downloads (chunked reads) to avoid loading whole files into memory.
- Concurrency must be enforced with a semaphore/worker pool.
- Derive filename:
  - Prefer `Content-Disposition` filename if present.
  - Else use the URL path basename.
  - If still empty, use `download_<index>.bin`.
- Handle duplicate filenames by auto-suffixing like `file (1).ext`.
- Timeouts: sensible defaults (connect + read). Retries: optional, but if implemented do max 2 retries with backoff.
- If a download fails, record error message and continue others.
- Save partial downloads to a temporary file and only rename to final name on success.

## UI requirements (tkinter)
Create a window with:
- "Select URL file" button + label showing chosen path
- "Select output folder" button + label showing chosen folder
- Concurrency input (Spinbox or Entry with validation)
- Buttons: Start, Pause/Resume (toggle), Cancel
- Overall progress bar
- Table/list showing each URL with columns: Filename, URL, Status, Progress %, Bytes (optional), Error (if any)
- Log text box (read-only) with auto-scroll

UI must stay responsive during downloads (do not block the main thread).
- Use `asyncio` running in a background thread OR another safe architecture.
- All UI updates must be marshaled back to the tkinter thread.

## Project structure (create these files)
- `README.md` (how to run, dependencies, usage, screenshots optional)
- `requirements.txt`
- `src/app.py` (main entrypoint)
- `src/downloader.py` (download logic, concurrency, retries, naming)
- `src/models.py` (dataclasses for download item/state)
- `src/utils.py` (filename sanitization, URL parsing, helpers)
- `tests/` (at least a couple unit tests for filename derivation + URL parsing; use pytest)

## Acceptance criteria
- Can download 100+ URLs without freezing the UI.
- Concurrency setting actually limits parallel downloads.
- Output folder selection works.
- Progress UI updates at least a few times per second while downloading.
- Cancel stops active downloads quickly and marks remaining queued items as canceled.
- App handles invalid URLs and HTTP errors gracefully and continues.

## Implementation notes
- Use `aiohttp.ClientSession` shared across downloads.
- Use `asyncio.Semaphore(concurrency)` to enforce max simultaneous downloads.
- Use chunk size e.g. 64KB.
- Provide clear, readable code with type hints.
- Add docstrings to public functions/classes.

## Deliverables
1. Generate all code files.
2. Include a brief README with exact commands:
   - create venv
   - install requirements
   - run the app
3. Include a small sample `urls.txt` in the repo root with a few example URLs (use placeholder or safe public URLs).

Now implement it.
```

If you tell me your preferred language (Python vs Rust vs C\#) and whether you need pause/resume to persist after app restart, I can tailor the prompt to that.
<span style="display:none">[^10][^11][^12][^13][^14][^15][^4][^5][^6][^7][^8][^9]</span>

<div align="center">⁂</div>

[^1]: https://docs.github.com/en/copilot/get-started/best-practices

[^2]: https://docs.github.com/en/copilot/concepts/prompting/prompt-engineering

[^3]: https://github.blog/developer-skills/github/how-to-write-better-prompts-for-github-copilot/

[^4]: https://www.reddit.com/r/GithubCopilot/comments/1lfz0wt/guidance_on_efficient_use_of_copilotinstructionsmd/

[^5]: https://github.com/orgs/community/discussions/153746

[^6]: https://snippets.dft.codes/snippets/2025-09-14.html

[^7]: https://github.com/bigb4ng/file-retriever

[^8]: https://darioairoldi.github.io/Learn/tech/PromptEngineering/01. how_github_copilot_uses_markdown_and_prompt_folders.html

[^9]: https://dev.to/ndrbrt/python-upload-multiple-files-concurrently-with-aiohttp-and-show-progress-bars-with-tqdm-32l7?comments_sort=oldest

[^10]: https://patshaughnessy.net/2020/1/20/downloading-100000-files-using-async-rust

[^11]: https://docs.github.com/en/enterprise-cloud@latest/copilot/get-started/best-practices

[^12]: https://www.andreabertoloni.com/blog/python-upload-multiple-files-concurrently-with-aiohttp-and-show-progress-bars-with-tqdm

[^13]: https://jonas.pleyer.org/posts/2025-09-02-download-file-progress-bar-rust/

[^14]: https://docs.github.com/en/copilot/concepts/prompting

[^15]: https://andreabertoloni.com/blog/python-upload-multiple-files-concurrently-with-aiohttp-and-show-progress-bars-with-tqdm

