# Optional local speech recognition helper

The browser extension uses Bilibili or YouTube subtitles when they are available. For a public video without readable subtitles, this helper can download its audio and produce timestamped speech segments with [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [faster-whisper](https://github.com/SYSTRAN/faster-whisper). The extension then sends those segments to the language model you configured for its summary and chapter generation.

## Install and run (Windows PowerShell)

Install standard CPython 3.11 or 3.12 and [FFmpeg](https://ffmpeg.org/download.html); make sure `ffmpeg -version` works in a new terminal. Check `python -c "import sys; print(sys.executable)"` before creating the virtual environment. On Windows, an Anaconda-based environment may conflict with the native speech recognition libraries; use a standalone CPython interpreter if model loading exits unexpectedly. From this `helper` directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe server.py
```

Leave the terminal running while using the extension. The service listens **only** on `http://127.0.0.1:8765`. It accepts requests from a Chrome extension origin or a local client with no `Origin` header. It does not accept arbitrary media URLs.

For later runs, `.\start.ps1` starts the same virtual environment, adds its `Scripts` directory to `PATH`, and reuses a model stored in this checkout's `.cache/models/faster-whisper-small` directory when available. If PowerShell blocks local scripts, use `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1` instead; this changes policy only for that process. You can also start `server.py` directly as above.

Check it with `Invoke-RestMethod http://127.0.0.1:8765/health`. After updating the helper files, stop the old process and start it again; a running Python process does not reload `server.py` automatically. The health response should list `youtube` under `platforms`.

The first transcription downloads the selected Whisper model. By default, the helper uses `small` on CPU with `int8` compute and automatically detects the language. To change this, set environment variables before starting it:

```powershell
$env:BILI_ASR_MODEL = "medium"
$env:BILI_ASR_LANGUAGE = "zh"   # or "auto"
$env:BILI_ASR_DEVICE = "cpu"    # or "cuda" with a working CUDA setup
$env:BILI_ASR_COMPUTE_TYPE = "int8"
.\.venv\Scripts\python.exe server.py
```

## API

- `GET /health` returns a status, `protocolVersion: 2`, and `platforms: ["bilibili", "youtube"]`.
- `POST /transcribe` accepts JSON `{ "bvid": "BV1dRYP6oEtB", "p": 1 }`. Omit `p` for page 1. Alternatively send `cid` instead of `p`; the helper looks up the page through Bilibili's view API. Do not send both.
- For YouTube, `POST /transcribe` accepts `{ "youtubeId": "dQw4w9WgXcQ" }`. This must be an 11-character video ID; URLs and extra fields are rejected. The helper constructs the watch URL itself and checks the ID returned by yt-dlp.
- An uncached request returns HTTP 202 with `{ "job_id": "...", "status": "queued" | "running", "progress": 0...99, "stage": "..." }`.
- Poll `GET /jobs/<job_id>`. On success it returns `{ "status": "done", "source": "local-asr", "progress": 100, "segments": [{ "from": 0.0, "to": 3.2, "content": "..." }] }`. Failure returns `status: "error"` and an `error` message.
- A cached `POST /transcribe` returns HTTP 200 with the completed segments immediately.

Only one ASR job runs at a time; up to three can wait in the queue. Jobs for the same video and page share work. Completed transcripts are cached in `%LOCALAPPDATA%\bili-ai-summary\asr-cache` (or `~/.cache/bili-ai-summary/asr-cache` if `LOCALAPPDATA` is unavailable). The cache key includes the platform, video ID, model, and language setting.

The helper limits input bodies to 4 KiB, videos to six hours, and temporary download storage to 750 MiB. Each download has a 20-minute timeout. Long videos may take several hours to transcribe on a CPU. The service requires access to the Bilibili or YouTube video and to the model files; videos requiring login, regional access, or unavailable audio may fail. Speech recognition describes spoken content only, so a silent or highly visual video may need subtitles or another input source.

Run validation and API tests without installing the optional ASR packages:

```powershell
python -m unittest discover -s tests -v
```
