# Optional local speech recognition helper

The browser extension uses Bilibili or YouTube subtitles when they are available. For a public video without readable subtitles, this helper can download its audio and produce timestamped speech segments with [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [faster-whisper](https://github.com/SYSTRAN/faster-whisper). The extension then sends those segments to the language model you configured for its summary and chapter generation. The helper also saves full videos locally as MP4 when you click **下载视频** in the extension.

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

Video downloading needs `yt-dlp` and `ffmpeg`; it does not need a speech model or AI API Key. Files go to `~/Downloads/AI视频章节` (`C:\Users\<your user>\Downloads\AI视频章节` on a typical Windows installation). Names are `youtube_<video-id>.mp4` or `bilibili_<BV-id>_p<page>.mp4`. The helper reports the exact path on completion and reuses an existing nonempty file instead of overwriting it.

The first transcription downloads the selected Whisper model. By default, the helper uses `small` on CPU with `int8` compute and automatically detects the language. To change this, set environment variables before starting it:

```powershell
$env:BILI_ASR_MODEL = "medium"
$env:BILI_ASR_LANGUAGE = "zh"   # or "auto"
$env:BILI_ASR_DEVICE = "cpu"    # or "cuda" with a working CUDA setup
$env:BILI_ASR_COMPUTE_TYPE = "int8"
.\.venv\Scripts\python.exe server.py
```

## API

- `GET /health` returns a status, `protocolVersion: 3`, `platforms: ["bilibili", "youtube"]`, and `features.videoDownload: true`.
- `POST /transcribe` accepts JSON `{ "bvid": "BV1dRYP6oEtB", "p": 1 }`. Omit `p` for page 1. Alternatively send `cid` instead of `p`; the helper looks up the page through Bilibili's view API. Do not send both.
- For YouTube, `POST /transcribe` accepts `{ "youtubeId": "dQw4w9WgXcQ" }`. This must be an 11-character video ID; URLs and extra fields are rejected. The helper constructs the watch URL itself and checks the ID returned by yt-dlp.
- An uncached request returns HTTP 202 with `{ "job_id": "...", "status": "queued" | "running", "progress": 0...99, "stage": "..." }`.
- Poll `GET /jobs/<job_id>`. On success it returns `{ "status": "done", "source": "local-asr", "progress": 100, "segments": [{ "from": 0.0, "to": 3.2, "content": "..." }] }`. Failure returns `status: "error"` and an `error` message.
- A cached `POST /transcribe` returns HTTP 200 with the completed segments immediately.
- `POST /downloads` accepts the same video identity JSON as `/transcribe`. It returns a video download task with `job_id`, `status`, `progress`, `stage`, `path`, and `error`. No URL or output path may be supplied by the browser.
- Poll `GET /downloads/<job_id>` until `status` becomes `done` or `error`. On success, `path` is the saved MP4's absolute path. A repeated request for an already downloaded video returns HTTP 200 and the existing path.

Only one ASR job runs at a time; up to three can wait in the queue. Jobs for the same video and page share work. Completed transcripts are cached in `%LOCALAPPDATA%\bili-ai-summary\asr-cache` (or `~/.cache/bili-ai-summary/asr-cache` if `LOCALAPPDATA` is unavailable). The cache key includes the platform, video ID, model, and language setting.

Video downloads use a separate single worker with room for three queued videos; simultaneous requests for the same video share a task. Video files remain in the Downloads folder. The helper first downloads into a temporary folder under the destination and publishes only a completed MP4.

The helper limits input bodies to 4 KiB, videos to six hours, and temporary download storage to 750 MiB. Each download has a 20-minute timeout. Long videos may take several hours to transcribe on a CPU. The service requires access to the Bilibili or YouTube video and to the model files; videos requiring login, regional access, or unavailable audio may fail. Speech recognition describes spoken content only, so a silent or highly visual video may need subtitles or another input source.

Full video downloads have an 8 GiB temporary storage limit and a four-hour timeout. Availability depends on what Bilibili or YouTube exposes to `yt-dlp`; login-only, restricted, or protected videos may fail.

Run validation and API tests without installing the optional ASR packages:

```powershell
python -m unittest discover -s tests -v
```
