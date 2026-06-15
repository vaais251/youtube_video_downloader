"""Download engine: wraps yt-dlp in Qt worker threads with a managed queue.

The :class:`DownloadManager` owns a ``QThreadPool``. Each :class:`DownloadTask`
is run by a :class:`DownloadWorker` (a ``QRunnable``). Concurrency is bounded by
the pool's max thread count, so extra tasks naturally wait their turn — that is
our download queue.

Pause / resume / cancel are cooperative: each task carries two
``threading.Event`` flags that the yt-dlp progress hook checks. Raising out of
the hook aborts the current download cleanly, leaving a ``.part`` file behind
that yt-dlp resumes from on the next run (``continuedl=True``).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from . import utils


# --- task model -----------------------------------------------------------

# Status values used throughout the UI.
QUEUED = "queued"
DOWNLOADING = "downloading"
PAUSED = "paused"
COMPLETED = "completed"
ERROR = "error"
CANCELED = "canceled"


# Engine that handles a task.
ENGINE_MEDIA = "media"   # yt-dlp (YouTube and other sites, format selection)
ENGINE_FILE = "file"     # direct download of any file (IDM-style capture)


@dataclass
class DownloadTask:
    url: str
    title: str
    format_selector: str
    audio_only: bool
    output_dir: str
    quality_label: str = ""
    engine: str = ENGINE_MEDIA
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    # Generic-file metadata (used when engine == ENGINE_FILE).
    out_name: str = ""        # suggested filename
    referrer: str = ""
    cookies: str = ""         # raw "Cookie:" header value
    user_agent: str = ""
    origin: str = ""
    mime: str = ""

    status: str = QUEUED
    progress: float = 0.0          # 0..100
    speed: str = ""
    eta: str = ""
    downloaded: str = ""
    total: str = ""
    filename: str = ""
    error: str = ""

    # Cooperative control flags (set from the GUI thread, read in the worker).
    pause_event: threading.Event = field(default_factory=threading.Event, repr=False)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)


def file_kind(name: str) -> str:
    """A short uppercase label for a filename's type, e.g. 'ZIP', 'PDF'."""
    import os

    ext = os.path.splitext(name or "")[1].lstrip(".").upper()
    return ext or "FILE"


# Fields persisted to disk so the queue survives restarts.
_PERSIST_FIELDS = (
    "url", "title", "format_selector", "audio_only", "output_dir",
    "quality_label", "engine", "id", "out_name", "referrer", "cookies",
    "user_agent", "origin", "mime", "status", "progress", "filename", "total",
)


def task_to_dict(task: "DownloadTask") -> dict:
    return {k: getattr(task, k) for k in _PERSIST_FIELDS}


def task_from_dict(d: dict) -> "DownloadTask":
    task = DownloadTask(
        url=d.get("url", ""),
        title=d.get("title", ""),
        format_selector=d.get("format_selector", ""),
        audio_only=bool(d.get("audio_only", False)),
        output_dir=d.get("output_dir", ""),
    )
    for k in _PERSIST_FIELDS:
        if k in d and k not in ("url", "title", "format_selector",
                                "audio_only", "output_dir"):
            setattr(task, k, d[k])
    return task


class _Paused(Exception):
    pass


class _Canceled(Exception):
    pass


# --- workers ---------------------------------------------------------------


class WorkerSignals(QObject):
    progress = pyqtSignal(str)        # task id
    finished = pyqtSignal(str)        # task id
    paused = pyqtSignal(str)          # task id
    canceled = pyqtSignal(str)        # task id
    error = pyqtSignal(str, str)      # task id, message


class DownloadWorker(QRunnable):
    def __init__(self, task: DownloadTask, use_aria2c: bool, speed_limit_kbps: int = 0):
        super().__init__()
        self.task = task
        self.use_aria2c = use_aria2c
        self.speed_limit_kbps = speed_limit_kbps
        self.signals = WorkerSignals()

    def _hook(self, d: dict) -> None:
        task = self.task
        if task.cancel_event.is_set():
            raise _Canceled()
        if task.pause_event.is_set():
            raise _Paused()

        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes") or 0
            if total:
                task.progress = max(0.0, min(100.0, downloaded / total * 100))
                task.total = utils.human_size(total)
            task.downloaded = utils.human_size(downloaded)
            speed = d.get("speed")
            task.speed = f"{utils.human_size(speed)}/s" if speed else ""
            eta = d.get("eta")
            task.eta = f"{int(eta)}s" if eta else ""
            task.status = DOWNLOADING
            self.signals.progress.emit(task.id)
        elif status == "finished":
            # Stream done; ffmpeg merge / mp3 conversion may still follow.
            task.speed = ""
            task.eta = ""
            task.status = DOWNLOADING
            self.signals.progress.emit(task.id)

    def _build_opts(self) -> dict:
        import os

        task = self.task
        opts: dict = {
            "outtmpl": os.path.join(task.output_dir, "%(title)s.%(ext)s"),
            "progress_hooks": [self._hook],
            "continuedl": True,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": False,
            "retries": 5,
            "fragment_retries": 5,
        }

        ff_dir = utils.ffmpeg_dir()
        has_ffmpeg = bool(ff_dir)
        if ff_dir:
            opts["ffmpeg_location"] = ff_dir

        # Pass through the browser's headers for sniffed/protected streams.
        hdrs = {}
        if task.user_agent:
            hdrs["User-Agent"] = task.user_agent
        if task.referrer:
            hdrs["Referer"] = task.referrer
        if task.origin:
            hdrs["Origin"] = task.origin
        if task.cookies:
            hdrs["Cookie"] = task.cookies
        if hdrs:
            opts["http_headers"] = hdrs

        if self.speed_limit_kbps:
            opts["ratelimit"] = self.speed_limit_kbps * 1024  # bytes/sec

        if task.audio_only:
            if has_ffmpeg:
                opts["format"] = "bestaudio/best"
                opts["postprocessors"] = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ]
            else:
                # No ffmpeg: can't transcode to MP3, so grab best audio as-is
                # (usually .m4a/.webm). The file is still playable.
                opts["format"] = "bestaudio/best"
        elif has_ffmpeg:
            opts["format"] = task.format_selector
            opts["merge_output_format"] = "mp4"
        else:
            # No ffmpeg: separate video+audio streams can't be merged, so fall
            # back to a single pre-muxed (progressive) stream — no merge needed.
            # YouTube usually caps progressive streams at 720p.
            import re

            m = re.search(r"height<=(\d+)", task.format_selector or "")
            if m:
                h = m.group(1)
                opts["format"] = (
                    f"best[height<={h}][ext=mp4]/best[height<={h}]/best"
                )
            else:
                opts["format"] = "best[ext=mp4]/best"

        # NOTE: we deliberately do NOT set aria2c as yt-dlp's external downloader.
        # With an external downloader yt-dlp's progress_hooks stop firing, so the
        # UI would sit at "Queued" the whole time (this only bit the packaged
        # build, where aria2c is bundled on PATH). yt-dlp's native downloader
        # reports smooth progress. aria2c multi-connection is still used by the
        # generic file engine, where we parse its progress ourselves.
        return opts

    def run(self) -> None:
        import yt_dlp

        task = self.task
        if task.cancel_event.is_set():
            self.signals.canceled.emit(task.id)
            return

        # Reflect "in progress" immediately — extract_info can take a few seconds
        # before the first progress hook fires.
        task.status = DOWNLOADING
        self.signals.progress.emit(task.id)

        opts = self._build_opts()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(task.url, download=True)
                if info:
                    try:
                        task.filename = ydl.prepare_filename(info)
                        if task.audio_only:
                            task.filename = task.filename.rsplit(".", 1)[0] + ".mp3"
                    except Exception:
                        pass
            task.progress = 100.0
            task.status = COMPLETED
            self.signals.finished.emit(task.id)
        except BaseException as exc:  # noqa: BLE001
            # yt-dlp may wrap our hook exception in a DownloadError, so decide
            # the outcome from the control flags rather than the exception type.
            if task.cancel_event.is_set():
                task.status = CANCELED
                self.signals.canceled.emit(task.id)
            elif task.pause_event.is_set():
                task.status = PAUSED
                self.signals.paused.emit(task.id)
            else:
                task.status = ERROR
                task.error = str(exc)
                self.signals.error.emit(task.id, str(exc))


# --- info (format) fetching ------------------------------------------------


class InfoSignals(QObject):
    fetched = pyqtSignal(dict)        # info dict
    error = pyqtSignal(str)


class InfoWorker(QRunnable):
    """Fetches metadata + available formats without downloading."""

    def __init__(self, url: str):
        super().__init__()
        self.url = url
        self.signals = InfoSignals()

    def run(self) -> None:
        import yt_dlp

        opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
            self.signals.fetched.emit(info or {})
        except Exception as exc:  # noqa: BLE001
            self.signals.error.emit(str(exc))


# --- format options (shared by GUI and the browser extension) --------------

AUDIO_MP3 = "__audio_mp3__"  # sentinel selector meaning "audio only -> MP3"


def build_format_options(info: dict) -> list[dict]:
    """Turn a yt-dlp info dict into a list of pickable quality options.

    Each option is ``{"label", "selector", "audio_only"}``. Used both to fill
    the desktop combo box and to answer the extension's ``/formats`` request.
    """
    options: list[dict] = [
        {"label": "Best quality (auto)",
         "selector": "bestvideo+bestaudio/best",
         "audio_only": False}
    ]
    heights = set()
    for f in info.get("formats", []) or []:
        if f.get("vcodec") and f.get("vcodec") != "none" and f.get("height"):
            heights.add(int(f["height"]))
    for h in sorted(heights, reverse=True):
        options.append({
            "label": f"{h}p",
            "selector": f"bestvideo[height<={h}]+bestaudio/best[height<={h}]",
            "audio_only": False,
        })
    options.append({"label": "Audio only (MP3)",
                    "selector": AUDIO_MP3, "audio_only": True})
    return options


def quality_label(selector: str, audio_only: bool) -> str:
    """A short, human label for a format selector (for history/UI)."""
    import re

    if audio_only or selector == AUDIO_MP3:
        return "MP3"
    m = re.search(r"height<=(\d+)", selector or "")
    if m:
        return f"{m.group(1)}p"
    return "Best"


def extract_formats(url: str) -> dict:
    """Synchronously fetch metadata + quality options for a URL.

    Runs yt-dlp inline (no Qt), so it is safe to call from the IPC server
    thread. Returns ``{title, duration, webpage_url, options}``.
    """
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    info = info or {}
    return {
        "title": info.get("title", ""),
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url", url),
        "options": build_format_options(info),
    }


# --- generic file downloader (IDM-style capture) ---------------------------


class FileDownloadWorker(QRunnable):
    """Downloads any direct URL (zip, pdf, exe, media, …).

    Prefers aria2c for multi-connection speed + resume; falls back to a
    pure-Python resumable downloader. Carries cookies/referrer/user-agent so
    authenticated/session downloads captured from the browser work.
    """

    def __init__(self, task: DownloadTask, use_aria2c: bool, speed_limit_kbps: int = 0):
        super().__init__()
        self.task = task
        self.use_aria2c = use_aria2c
        self.speed_limit_kbps = speed_limit_kbps
        self.signals = WorkerSignals()
        self.proc = None

    # -- header helpers
    def _out_path(self) -> str:
        import os

        name = self.task.out_name or self.task.title or "download"
        return os.path.join(self.task.output_dir, name)

    def _resolve_name(self) -> None:
        """Avoid clobbering an existing finished file: foo.zip -> foo (1).zip.
        Runs once before downloading; skips if a partial download is resuming."""
        import os

        path = self._out_path()
        if os.path.exists(path + ".part") or os.path.exists(path + ".aria2"):
            return  # resuming an in-progress download — keep the name
        if not os.path.exists(path):
            return
        root, ext = os.path.splitext(path)
        i = 1
        while os.path.exists(f"{root} ({i}){ext}"):
            i += 1
        self.task.out_name = os.path.basename(f"{root} ({i}){ext}")

    def _request_headers(self) -> dict:
        """Headers to replay the browser request. A sane Referer/Origin is what
        gets past hotlink-protected CDNs that return 403 to bare requests."""
        from urllib.parse import urlparse

        t = self.task
        h = {"User-Agent": t.user_agent or "Mozilla/5.0"}
        referer = t.referrer
        if not referer:
            p = urlparse(t.url)
            referer = f"{p.scheme}://{p.netloc}/"
        h["Referer"] = referer
        origin = t.origin
        if not origin:
            p = urlparse(referer)
            origin = f"{p.scheme}://{p.netloc}"
        h["Origin"] = origin
        if t.cookies:
            h["Cookie"] = t.cookies
        return h

    def _emit_progress(self, done: int, total: int, speed_bps: float, eta_s):
        t = self.task
        if total:
            t.progress = max(0.0, min(100.0, done / total * 100))
            t.total = utils.human_size(total)
        t.downloaded = utils.human_size(done)
        t.speed = f"{utils.human_size(speed_bps)}/s" if speed_bps else ""
        t.eta = f"{int(eta_s)}s" if eta_s else ""
        t.status = DOWNLOADING
        self.signals.progress.emit(t.id)

    # -- aria2c path
    def _run_aria2c(self) -> bool:
        import os
        import re
        import subprocess

        task = self.task
        out_name = os.path.basename(self._out_path())
        cmd = [
            utils.aria2c_path(),
            "--continue=true",
            "--max-connection-per-server=16",
            "--split=16",
            "--min-split-size=1M",
            "--summary-interval=1",
            "--show-console-readout=false",
            "--console-log-level=warn",
            "--auto-file-renaming=false",
            f"--dir={task.output_dir}",
            f"--out={out_name}",
        ]
        if self.speed_limit_kbps:
            cmd.append(f"--max-overall-download-limit={self.speed_limit_kbps}K")
        hdrs = self._request_headers()
        cmd.append(f"--referer={hdrs['Referer']}")
        cmd.append(f"--user-agent={hdrs['User-Agent']}")
        cmd.append(f"--header=Origin: {hdrs['Origin']}")
        if hdrs.get("Cookie"):
            cmd.append(f"--header=Cookie: {hdrs['Cookie']}")
        cmd.append(task.url)

        creationflags = 0x08000000 if os.name == "nt" else 0  # no console window
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, creationflags=creationflags,
        )

        prog_re = re.compile(
            r"\(([\d.]+)%\).*?DL:([\d.]+\s*\w+).*?ETA:(\w+)", re.IGNORECASE)
        size_re = re.compile(r"([\d.]+\s*\w+)/([\d.]+\s*\w+)\(([\d.]+)%\)")
        for line in self.proc.stdout:
            if task.cancel_event.is_set() or task.pause_event.is_set():
                self.proc.terminate()
                break
            sm = size_re.search(line)
            pm = prog_re.search(line)
            if sm or pm:
                t = self.task
                if sm:
                    t.downloaded, t.total = sm.group(1), sm.group(2)
                    t.progress = float(sm.group(3))
                if pm:
                    t.progress = float(pm.group(1))
                    t.speed = pm.group(2) + "/s"
                    t.eta = pm.group(3)
                t.status = DOWNLOADING
                self.signals.progress.emit(t.id)
        rc = self.proc.wait()
        return rc == 0 and not task.cancel_event.is_set() and not task.pause_event.is_set()

    # -- pure-python fallback
    def _run_python(self) -> bool:
        import os
        import time
        import urllib.request

        task = self.task
        out = self._out_path()
        part = out + ".part"
        existing = os.path.getsize(part) if os.path.exists(part) else 0

        headers = self._request_headers()
        if existing:
            headers["Range"] = f"bytes={existing}-"

        req = urllib.request.Request(task.url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=30)
        # If the server ignored Range, restart from scratch.
        if existing and resp.status == 200:
            existing = 0
        total = int(resp.headers.get("Content-Length", 0) or 0) + existing
        mode = "ab" if existing else "wb"

        limit_bps = self.speed_limit_kbps * 1024 if self.speed_limit_kbps else 0
        done = existing
        last_t, last_b = time.time(), done
        rate_t, rate_b = time.time(), done
        with open(part, mode) as fh:
            while True:
                if task.cancel_event.is_set():
                    return False
                if task.pause_event.is_set():
                    return False
                chunk = resp.read(262144)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                now = time.time()
                # throttle to the speed limit
                if limit_bps:
                    elapsed = now - rate_t
                    expected = (done - rate_b) / limit_bps
                    if expected > elapsed:
                        time.sleep(expected - elapsed)
                if now - last_t >= 0.5:
                    speed = (done - last_b) / (now - last_t)
                    eta = (total - done) / speed if speed and total else 0
                    self._emit_progress(done, total, speed, eta)
                    last_t, last_b = now, done
        os.replace(part, out)
        return True

    def run(self) -> None:
        task = self.task
        if task.cancel_event.is_set():
            self.signals.canceled.emit(task.id)
            return
        self._resolve_name()
        try:
            ok = (self._run_aria2c() if (self.use_aria2c and utils.aria2c_path())
                  else self._run_python())
            if ok:
                task.progress = 100.0
                task.filename = self._out_path()
                task.status = COMPLETED
                self.signals.finished.emit(task.id)
            elif task.cancel_event.is_set():
                task.status = CANCELED
                self.signals.canceled.emit(task.id)
            elif task.pause_event.is_set():
                task.status = PAUSED
                self.signals.paused.emit(task.id)
            else:
                task.status = ERROR
                task.error = "Download did not complete."
                self.signals.error.emit(task.id, task.error)
        except Exception as exc:  # noqa: BLE001
            if task.cancel_event.is_set():
                task.status = CANCELED
                self.signals.canceled.emit(task.id)
            elif task.pause_event.is_set():
                task.status = PAUSED
                self.signals.paused.emit(task.id)
            else:
                task.status = ERROR
                task.error = str(exc)
                self.signals.error.emit(task.id, str(exc))


# --- manager ---------------------------------------------------------------


class DownloadManager(QObject):
    """Owns the task list and the thread pool that runs downloads."""

    task_changed = pyqtSignal(str)    # task id -> UI should refresh that row

    def __init__(self, max_concurrent: int = 3, use_aria2c: bool = True,
                 speed_limit_kbps: int = 0):
        super().__init__()
        self.tasks: dict[str, DownloadTask] = {}
        self.use_aria2c = use_aria2c
        self.speed_limit_kbps = speed_limit_kbps
        self.pool = QThreadPool.globalInstance()
        self.set_max_concurrent(max_concurrent)

    def restore_task(self, task: DownloadTask) -> None:
        """Re-add a task loaded from disk without starting it (paused)."""
        if task.status in (DOWNLOADING, QUEUED):
            task.status = PAUSED
        self.tasks[task.id] = task

    def resume_all(self) -> None:
        for tid, task in list(self.tasks.items()):
            if task.status in (PAUSED, ERROR, QUEUED):
                self._start(task)

    def pause_all(self) -> None:
        for tid in list(self.tasks):
            self.pause(tid)

    def set_max_concurrent(self, n: int) -> None:
        self.pool.setMaxThreadCount(max(1, n))

    def add_task(self, task: DownloadTask) -> DownloadTask:
        self.tasks[task.id] = task
        self._start(task)
        return task

    def _start(self, task: DownloadTask) -> None:
        task.pause_event.clear()
        task.cancel_event.clear()
        task.status = QUEUED
        task.error = ""
        self.task_changed.emit(task.id)

        if task.engine == ENGINE_FILE:
            worker = FileDownloadWorker(task, self.use_aria2c, self.speed_limit_kbps)
        else:
            worker = DownloadWorker(task, self.use_aria2c, self.speed_limit_kbps)
        worker.signals.progress.connect(self.task_changed)
        worker.signals.finished.connect(self.task_changed)
        worker.signals.paused.connect(self.task_changed)
        worker.signals.canceled.connect(self.task_changed)
        worker.signals.error.connect(lambda tid, _msg: self.task_changed.emit(tid))
        self.pool.start(worker)

    def pause(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if task and task.status in (DOWNLOADING, QUEUED):
            task.pause_event.set()

    def resume(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if task and task.status in (PAUSED, ERROR):
            self._start(task)

    def cancel(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if task:
            task.cancel_event.set()
            # If it was paused (not actively running) flip the status now.
            if task.status in (PAUSED, QUEUED):
                task.status = CANCELED
                self.task_changed.emit(task.id)

    def retry(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if task and task.status in (ERROR, CANCELED):
            task.progress = 0.0
            self._start(task)

    def remove(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if task:
            task.cancel_event.set()
            self.tasks.pop(task_id, None)
