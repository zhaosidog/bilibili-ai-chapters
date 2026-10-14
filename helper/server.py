"""Optional loopback ASR and video download service for Bilibili and YouTube.

Run with ``python server.py`` after installing requirements.txt and ffmpeg.
The browser extension never sends arbitrary media URLs to this service.
"""

from __future__ import annotations

import hashlib
import http.client
import importlib.util
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable


HOST = "127.0.0.1"
PORT = 8765
MAX_REQUEST_BYTES = 4096
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_CACHE_BYTES = 20 * 1024 * 1024
MAX_DURATION_SECONDS = 6 * 60 * 60
MAX_TEMP_BYTES = 750 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 20 * 60
MAX_VIDEO_DOWNLOAD_BYTES = 8 * 1024 * 1024 * 1024
VIDEO_DOWNLOAD_TIMEOUT_SECONDS = 4 * 60 * 60
MODEL = os.environ.get("BILI_ASR_MODEL", "small")
_language_setting = os.environ.get("BILI_ASR_LANGUAGE", "auto")
LANGUAGE = None if _language_setting in {"", "auto"} else _language_setting
DEVICE = os.environ.get("BILI_ASR_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("BILI_ASR_COMPUTE_TYPE", "int8")
BVID_RE = re.compile(r"^BV[a-zA-Z0-9]{10}$")
YOUTUBE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")
ORIGIN_RE = re.compile(r"^chrome-extension://[a-p]{32}$")
JOB_RE = re.compile(r"^/jobs/([0-9a-f]{32})$")
DOWNLOAD_JOB_RE = re.compile(r"^/downloads/([0-9a-f]{32})$")
VIDEO_PROGRESS_RE = re.compile(r"download:\s*(\d+(?:\.\d+)?)%")


class ClientError(Exception):
    """An error that can safely be returned to the local client."""


class QueueFullError(ClientError):
    """ASR capacity is temporarily exhausted."""


@dataclass(frozen=True)
class VideoRequest:
    bvid: str | None
    page: int = 1
    youtube_id: str | None = None

    @property
    def platform(self) -> str:
        return "youtube" if self.youtube_id is not None else "bilibili"


def _positive_int(value: Any, name: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ClientError(f"{name} must be an integer from 1 to {maximum}")
    return value


def validate_request(payload: Any) -> tuple[str, int | None, int | None]:
    """Validate untrusted JSON before it reaches a URL or subprocess argument."""
    if not isinstance(payload, dict):
        raise ClientError("request body must be a JSON object")
    if set(payload) - {"bvid", "p", "cid"}:
        raise ClientError("unknown request field")
    bvid = payload.get("bvid")
    if not isinstance(bvid, str) or not BVID_RE.fullmatch(bvid):
        raise ClientError("bvid must be a 12-character BV id")
    if "p" in payload and "cid" in payload:
        raise ClientError("provide p or cid, not both")
    page = _positive_int(payload["p"], "p", 1000) if "p" in payload else None
    cid = _positive_int(payload["cid"], "cid", 9_007_199_254_740_991) if "cid" in payload else None
    return bvid, page, cid


def parse_video_request(payload: Any) -> VideoRequest:
    """Accept only platform IDs, never a client-supplied download URL."""
    if isinstance(payload, dict) and "youtubeId" in payload:
        if set(payload) != {"youtubeId"}:
            raise ClientError("youtubeId cannot be combined with other request fields")
        youtube_id = payload["youtubeId"]
        if not isinstance(youtube_id, str) or not YOUTUBE_ID_RE.fullmatch(youtube_id):
            raise ClientError("youtubeId must be an 11-character YouTube video id")
        return VideoRequest(None, youtube_id=youtube_id)
    bvid, page, cid = validate_request(payload)
    return VideoRequest(bvid, resolve_page(bvid, cid) if cid is not None else page or 1)


def allowed_origin(origin: str | None) -> bool:
    return origin is None or bool(ORIGIN_RE.fullmatch(origin))


def resolve_page(bvid: str, cid: int) -> int:
    """Map a CID to its 1-based page using Bilibili's fixed view endpoint."""
    url = "https://api.bilibili.com/x/web-interface/view?" + urllib.parse.urlencode({"bvid": bvid})
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read(MAX_METADATA_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, http.client.HTTPException) as exc:
        raise ClientError(f"could not resolve CID from Bilibili: {exc}") from exc
    if len(raw) > MAX_METADATA_BYTES:
        raise ClientError("Bilibili view response was too large")
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClientError("Bilibili returned an invalid view response") from exc
    if not isinstance(data, dict) or data.get("code") != 0 or not isinstance(data.get("data"), dict):
        raise ClientError("Bilibili could not find this video")
    video = data["data"]
    if video.get("bvid") != bvid:
        raise ClientError("Bilibili returned a different video")
    pages = video.get("pages")
    if not isinstance(pages, list):
        raise ClientError("Bilibili did not return video pages")
    for index, page in enumerate(pages, 1):
        if isinstance(page, dict) and page.get("cid") == cid:
            return index
    raise ClientError("CID was not found in this video")


def cache_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / ".cache") / "bili-ai-summary" / "asr-cache"


def cache_path(root: Path, video: VideoRequest) -> Path:
    config = json.dumps([MODEL, LANGUAGE], ensure_ascii=False).encode("utf-8")
    suffix = hashlib.sha256(config).hexdigest()[:12]
    if video.youtube_id is not None:
        return root / f"youtube_{video.youtube_id}_{suffix}.json"
    return root / f"{video.bvid}_p{video.page}_{suffix}.json"


def read_cache(root: Path, video: VideoRequest) -> list[dict[str, Any]] | None:
    path = cache_path(root, video)
    try:
        if path.stat().st_size > MAX_CACHE_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    if video.youtube_id is not None:
        if data.get("platform") != "youtube" or data.get("youtubeId") != video.youtube_id:
            return None
    elif data.get("bvid") != video.bvid or data.get("p") != video.page:
        return None
    segments = data.get("segments")
    if not isinstance(segments, list):
        return None
    for segment in segments:
        if not isinstance(segment, dict) or not {"from", "to", "content"} <= set(segment):
            return None
    return segments


def write_cache(root: Path, video: VideoRequest, segments: list[dict[str, Any]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    target = cache_path(root, video)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        identity = (
            {"platform": "youtube", "youtubeId": video.youtube_id}
            if video.youtube_id is not None
            else {"bvid": video.bvid, "p": video.page}
        )
        temporary.write_text(
            json.dumps({"version": 1, **identity, "segments": segments}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _check_dependencies() -> None:
    if importlib.util.find_spec("yt_dlp") is None:
        raise ClientError("yt-dlp is missing; install helper/requirements.txt")
    if importlib.util.find_spec("faster_whisper") is None:
        raise ClientError("faster-whisper is missing; install helper/requirements.txt")
    if shutil.which("ffmpeg") is None:
        raise ClientError("ffmpeg is missing from PATH")


def _run_metadata(url: str) -> dict[str, Any]:
    command = [
        sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist", "--no-warnings", "--no-colors",
        "--socket-timeout", "15", "--retries", "2", "--fragment-retries", "2",
        "--skip-download", "--dump-single-json", url,
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=45, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ClientError("yt-dlp timed out while reading video metadata") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace")[-400:].strip()
        raise ClientError(f"yt-dlp could not read video metadata: {detail or 'unknown error'}")
    if len(result.stdout) > MAX_METADATA_BYTES:
        raise ClientError("yt-dlp metadata was too large")
    try:
        data = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClientError("yt-dlp returned invalid video metadata") from exc
    if not isinstance(data, dict):
        raise ClientError("yt-dlp returned invalid video metadata")
    duration = data.get("duration")
    if not isinstance(duration, (int, float)) or not 0 < duration <= MAX_DURATION_SECONDS:
        raise ClientError(f"video duration is unknown or exceeds {MAX_DURATION_SECONDS // 60} minutes")
    return data


def _temp_bytes(folder: Path) -> int:
    try:
        return sum(file.stat().st_size for file in folder.rglob("*") if file.is_file())
    except OSError:
        return MAX_TEMP_BYTES + 1


def _error_tail(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 4096))
            return stream.read().decode("utf-8", errors="replace")[-400:].strip()
    except OSError:
        return "unknown error"


def _kill_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=10,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _download_audio(url: str, folder: Path, update: Callable[[int, str], None]) -> Path:
    command = [
        sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist", "--no-warnings", "--no-colors",
        "--no-progress", "--socket-timeout", "15", "--retries", "2", "--fragment-retries", "2",
        "--max-filesize", "500M", "-f", "bestaudio/best", "--extract-audio",
        "--audio-format", "mp3", "--audio-quality", "5", "-o", "audio.%(ext)s", url,
    ]
    error_log = folder / "yt-dlp-error.log"
    with error_log.open("wb") as error_file:
        process = subprocess.Popen(
            command, cwd=folder, stdout=subprocess.DEVNULL, stderr=error_file,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        started = time.monotonic()
        try:
            while process.poll() is None:
                if time.monotonic() - started > DOWNLOAD_TIMEOUT_SECONDS:
                    raise ClientError("audio download timed out")
                if _temp_bytes(folder) > MAX_TEMP_BYTES:
                    raise ClientError("audio download exceeded 750 MiB temporary storage limit")
                time.sleep(0.5)
        except BaseException:
            _kill_process_tree(process)
            raise
    if process.returncode:
        detail = _error_tail(error_log)
        raise ClientError(f"yt-dlp could not download audio: {detail or 'unknown error'}")
    audio = folder / "audio.mp3"
    if not audio.is_file() or audio.stat().st_size == 0:
        raise ClientError("yt-dlp did not create an MP3 audio file")
    if _temp_bytes(folder) > MAX_TEMP_BYTES:
        raise ClientError("audio download exceeded 750 MiB temporary storage limit")
    update(25, "transcribing")
    return audio


@lru_cache(maxsize=1)
def _get_model():
    from faster_whisper import WhisperModel

    return WhisperModel(MODEL, device=DEVICE, compute_type=COMPUTE_TYPE)


def transcribe_video(video: VideoRequest, update: Callable[[int, str], None]) -> list[dict[str, Any]]:
    _check_dependencies()
    url = (
        f"https://www.youtube.com/watch?v={video.youtube_id}"
        if video.youtube_id is not None
        else f"https://www.bilibili.com/video/{video.bvid}/?p={video.page}"
    )
    update(5, "reading metadata")
    metadata = _run_metadata(url)
    if video.youtube_id is not None:
        if metadata.get("id") != video.youtube_id:
            raise ClientError("yt-dlp returned a different YouTube video")
    else:
        expected_ids = {video.bvid, f"{video.bvid}_p{video.page}"}
        if metadata.get("id") not in expected_ids or (video.page > 1 and metadata.get("id") == video.bvid):
            raise ClientError("yt-dlp returned a different Bilibili page")
    duration = float(metadata["duration"])
    update(10, "downloading audio")
    with tempfile.TemporaryDirectory(prefix="video-ai-asr-") as temporary:
        audio = _download_audio(url, Path(temporary), update)
        update(25, "loading ASR model")
        model = _get_model()
        update(26, "transcribing")
        raw_segments, _info = model.transcribe(
            str(audio), language=LANGUAGE, vad_filter=True, beam_size=5, word_timestamps=False
        )
        segments: list[dict[str, Any]] = []
        for item in raw_segments:
            content = item.text.strip()
            if not content:
                continue
            start = max(0.0, float(item.start))
            end = max(start, float(item.end))
            segments.append({"from": round(start, 2), "to": round(end, 2), "content": content})
            update(max(26, min(98, 25 + int(73 * end / duration))), "transcribing")
    if not segments:
        raise ClientError("speech recognition found no spoken content")
    return segments


def download_root() -> Path:
    """Video files have one local destination; callers cannot choose a path."""
    return Path.home() / "Downloads" / "AI视频章节"


def download_path(root: Path, video: VideoRequest) -> Path:
    if video.youtube_id is not None:
        name = f"youtube_{video.youtube_id}.mp4"
    else:
        name = f"bilibili_{video.bvid}_p{video.page}.mp4"
    return root / name


def existing_download(root: Path, video: VideoRequest) -> Path | None:
    path = download_path(root, video)
    try:
        return path.resolve() if not path.is_symlink() and path.is_file() and path.stat().st_size > 0 else None
    except OSError:
        return None


def _check_video_dependencies() -> None:
    if importlib.util.find_spec("yt_dlp") is None:
        raise ClientError("yt-dlp is missing; install helper/requirements.txt")
    if shutil.which("ffmpeg") is None:
        raise ClientError("ffmpeg is missing from PATH")


def _video_temp_bytes(folder: Path) -> int:
    try:
        return sum(file.stat().st_size for file in folder.rglob("*") if file.is_file())
    except OSError:
        return MAX_VIDEO_DOWNLOAD_BYTES + 1


def download_video(video: VideoRequest, root: Path, update: Callable[[int, str], None]) -> Path:
    """Download one verified public video into a temporary directory, then publish atomically."""
    _check_video_dependencies()
    url = (
        f"https://www.youtube.com/watch?v={video.youtube_id}"
        if video.youtube_id is not None
        else f"https://www.bilibili.com/video/{video.bvid}/?p={video.page}"
    )
    update(5, "reading metadata")
    metadata = _run_metadata(url)
    if video.youtube_id is not None:
        if metadata.get("id") != video.youtube_id:
            raise ClientError("yt-dlp returned a different YouTube video")
    else:
        expected_ids = {video.bvid, f"{video.bvid}_p{video.page}"}
        if metadata.get("id") not in expected_ids or (video.page > 1 and metadata.get("id") == video.bvid):
            raise ClientError("yt-dlp returned a different Bilibili page")

    root.mkdir(parents=True, exist_ok=True)
    target = download_path(root, video)
    if target.exists() or target.is_symlink():
        existing = existing_download(root, video)
        if existing is not None:
            return existing
        raise ClientError("download destination already exists but is not a valid video file")

    update(10, "downloading video")
    with tempfile.TemporaryDirectory(prefix=".video-ai-download-", dir=root) as temporary:
        folder = Path(temporary)
        command = [
            sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist", "--no-warnings", "--no-colors",
            "--no-overwrites", "--newline", "--progress", "--progress-template", "download:download:%(progress._percent_str)s",
            "--socket-timeout", "15", "--retries", "2", "--fragment-retries", "2", "--max-filesize", "8G",
            "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
            "--merge-output-format", "mp4", "--remux-video", "mp4", "-o", "video.%(ext)s", url,
        ]
        error_log = folder / "yt-dlp-error.log"
        with error_log.open("wb") as error_file:
            process = subprocess.Popen(
                command, cwd=folder, stdout=subprocess.PIPE, stderr=error_file,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )

            def report_progress() -> None:
                if process.stdout is None:
                    return
                for line in process.stdout:
                    match = VIDEO_PROGRESS_RE.search(line)
                    if match:
                        percent = min(100.0, float(match.group(1)))
                        update(10 + int(percent * 0.8), "downloading video")

            reader = threading.Thread(target=report_progress, daemon=True, name="video-download-progress")
            reader.start()
            started = time.monotonic()
            try:
                while process.poll() is None:
                    if time.monotonic() - started > VIDEO_DOWNLOAD_TIMEOUT_SECONDS:
                        raise ClientError("video download timed out")
                    if _video_temp_bytes(folder) > MAX_VIDEO_DOWNLOAD_BYTES:
                        raise ClientError("video download exceeded 8 GiB temporary storage limit")
                    time.sleep(0.5)
            except BaseException:
                _kill_process_tree(process)
                raise
            finally:
                reader.join(timeout=2)
                if process.stdout is not None:
                    process.stdout.close()
        if process.returncode:
            detail = _error_tail(error_log)
            raise ClientError(f"yt-dlp could not download video: {detail or 'unknown error'}")
        update(92, "saving video")
        source = folder / "video.mp4"
        if not source.is_file() or source.is_symlink() or source.stat().st_size == 0:
            raise ClientError("yt-dlp did not create an MP4 video file")
        if _video_temp_bytes(folder) > MAX_VIDEO_DOWNLOAD_BYTES:
            raise ClientError("video download exceeded 8 GiB temporary storage limit")
        try:
            os.link(source, target)
        except FileExistsError as exc:
            existing = existing_download(root, video)
            if existing is None:
                raise ClientError("download destination already exists but is not a valid video file") from exc
            return existing
        return target.resolve()


@dataclass
class Job:
    id: str
    video: VideoRequest
    status: str = "queued"
    progress: int = 0
    stage: str = "queued"
    segments: list[dict[str, Any]] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)

    def response(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "job_id": self.id, "status": self.status, "progress": self.progress,
            "stage": self.stage, "source": "local-asr",
        }
        if self.segments is not None:
            data["segments"] = self.segments
        if self.error is not None:
            data["error"] = self.error
        return data


class JobManager:
    def __init__(self, root: Path | None = None, worker: Callable = transcribe_video):
        self.root = root or cache_root()
        self.worker = worker
        self.jobs: dict[str, Job] = {}
        self.active_by_video: dict[VideoRequest, str] = {}
        self.lock = threading.Lock()
        self.pending: queue.Queue[Job] = queue.Queue(maxsize=3)
        threading.Thread(target=self._run, daemon=True, name="bili-asr-worker").start()

    def submit(self, video: VideoRequest) -> tuple[dict[str, Any], int]:
        with self.lock:
            cached = read_cache(self.root, video)
            if cached is not None:
                return {"status": "done", "progress": 100, "source": "local-asr", "segments": cached}, HTTPStatus.OK
            active = self.active_by_video.get(video)
            if active:
                return self.jobs[active].response(), HTTPStatus.ACCEPTED
            job = Job(uuid.uuid4().hex, video)
            try:
                self.pending.put_nowait(job)
            except queue.Full as exc:
                raise QueueFullError("ASR queue is full; try again later") from exc
            self.jobs[job.id] = job
            self.active_by_video[video] = job.id
            self._prune()
            return job.response(), HTTPStatus.ACCEPTED

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return job.response() if job else None

    def _prune(self) -> None:
        # Bound memory while retaining enough terminal jobs for recent clients.
        terminal = sorted((j for j in self.jobs.values() if j.status in {"done", "error"}), key=lambda j: j.created_at)
        for old in terminal[: max(0, len(self.jobs) - 64)]:
            self.jobs.pop(old.id, None)

    def _run(self) -> None:
        while True:
            job = self.pending.get()
            with self.lock:
                job.status = "running"
                job.stage = "starting"

            def update(progress: int, stage: str) -> None:
                with self.lock:
                    job.progress = min(99, max(0, progress))
                    job.stage = stage

            try:
                segments = self.worker(job.video, update)
                try:
                    write_cache(self.root, job.video, segments)
                except OSError:
                    # The result remains available through this job even if cache storage fails.
                    pass
                with self.lock:
                    job.segments = segments
                    job.status = "done"
                    job.progress = 100
                    job.stage = "done"
            except Exception as exc:
                with self.lock:
                    job.status = "error"
                    job.stage = "error"
                    job.error = str(exc)[:600] or type(exc).__name__
            finally:
                with self.lock:
                    self.active_by_video.pop(job.video, None)
                self.pending.task_done()


@dataclass
class DownloadJob:
    id: str
    video: VideoRequest
    status: str = "queued"
    progress: int = 0
    stage: str = "queued"
    path: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)

    def response(self) -> dict[str, Any]:
        return {
            "job_id": self.id, "status": self.status, "progress": self.progress,
            "stage": self.stage, "path": self.path, "error": self.error,
        }


class DownloadManager:
    def __init__(self, root: Path | None = None, worker: Callable = download_video):
        self.root = root if root is not None else download_root()
        self.worker = worker
        self.jobs: dict[str, DownloadJob] = {}
        self.active_by_video: dict[VideoRequest, str] = {}
        self.lock = threading.Lock()
        self.pending: queue.Queue[DownloadJob] = queue.Queue(maxsize=3)
        threading.Thread(target=self._run, daemon=True, name="video-download-worker").start()

    def submit(self, video: VideoRequest) -> tuple[dict[str, Any], int]:
        with self.lock:
            active = self.active_by_video.get(video)
            if active:
                return self.jobs[active].response(), HTTPStatus.ACCEPTED
            cached = existing_download(self.root, video)
            if cached is not None:
                job = DownloadJob(uuid.uuid4().hex, video, status="done", progress=100, stage="done", path=str(cached))
                self.jobs[job.id] = job
                self._prune()
                return job.response(), HTTPStatus.OK
            job = DownloadJob(uuid.uuid4().hex, video)
            try:
                self.pending.put_nowait(job)
            except queue.Full as exc:
                raise QueueFullError("video download queue is full; try again later") from exc
            self.jobs[job.id] = job
            self.active_by_video[video] = job.id
            self._prune()
            return job.response(), HTTPStatus.ACCEPTED

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return job.response() if job else None

    def _prune(self) -> None:
        terminal = sorted((j for j in self.jobs.values() if j.status in {"done", "error"}), key=lambda j: j.created_at)
        for old in terminal[: max(0, len(self.jobs) - 64)]:
            self.jobs.pop(old.id, None)

    def _run(self) -> None:
        while True:
            job = self.pending.get()
            with self.lock:
                job.status = "running"
                job.stage = "starting"

            def update(progress: int, stage: str) -> None:
                with self.lock:
                    job.progress = min(99, max(job.progress, progress))
                    job.stage = stage

            try:
                path = self.worker(job.video, self.root, update)
                with self.lock:
                    job.path = str(path.resolve())
                    job.status = "done"
                    job.progress = 100
                    job.stage = "done"
            except Exception as exc:
                with self.lock:
                    job.status = "error"
                    job.stage = "error"
                    job.error = str(exc)[:600] or type(exc).__name__
            finally:
                with self.lock:
                    self.active_by_video.pop(job.video, None)
                self.pending.task_done()


class Handler(BaseHTTPRequestHandler):
    manager: JobManager
    downloads: DownloadManager

    def _permitted(self) -> bool:
        origin = self.headers.get("Origin")
        expected_host = f"{HOST}:{self.server.server_port}"
        if self.headers.get("Host") != expected_host or not allowed_origin(origin):
            self._json(HTTPStatus.FORBIDDEN, {"error": "request origin or host is not allowed"}, cors=False)
            return False
        return True

    def _json(self, status: int, data: dict[str, Any], *, cors: bool = True) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self.headers.get("Origin")
        if cors and origin and allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        if not self._permitted():
            return
        if self.path not in {"/transcribe", "/health", "/downloads"} and not JOB_RE.fullmatch(self.path) and not DOWNLOAD_JOB_RE.fullmatch(self.path):
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Content-Length", "0")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self) -> None:
        if not self._permitted():
            return
        if self.path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok", "source": "local-asr",
                                       "protocolVersion": 3, "platforms": ["bilibili", "youtube"],
                                       "features": {"videoDownload": True}})
            return
        download_match = DOWNLOAD_JOB_RE.fullmatch(self.path)
        if download_match:
            job = self.downloads.get(download_match.group(1))
            self._json(HTTPStatus.OK if job else HTTPStatus.NOT_FOUND, job or {"error": "job not found"})
            return
        match = JOB_RE.fullmatch(self.path)
        if match:
            job = self.manager.get(match.group(1))
            self._json(HTTPStatus.OK if job else HTTPStatus.NOT_FOUND, job or {"error": "job not found"})
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._permitted():
            return
        if self.path not in {"/transcribe", "/downloads"}:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Content-Type must be application/json"})
            return
        if self.headers.get("Transfer-Encoding"):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "chunked request bodies are not supported"})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request body must be at most 4096 bytes"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
            video = parse_video_request(payload)
            data, status = (self.downloads if self.path == "/downloads" else self.manager).submit(video)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON"})
            return
        except QueueFullError as exc:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
            return
        except ClientError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._json(status, data)


def main() -> None:
    Handler.manager = JobManager()
    Handler.downloads = DownloadManager()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"Video helper listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
