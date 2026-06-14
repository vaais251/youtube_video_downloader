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


@dataclass
class DownloadTask:
    url: str
    title: str
    format_selector: str
    audio_only: bool
    output_dir: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

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
    def __init__(self, task: DownloadTask, use_aria2c: bool):
        super().__init__()
        self.task = task
        self.use_aria2c = use_aria2c
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

        if self.use_aria2c and utils.aria2c_path():
            opts["external_downloader"] = "aria2c"
            opts["external_downloader_args"] = {
                "aria2c": ["-x", "16", "-s", "16", "-k", "1M", "--console-log-level=warn"]
            }

        return opts

    def run(self) -> None:
        import yt_dlp

        task = self.task
        if task.cancel_event.is_set():
            self.signals.canceled.emit(task.id)
            return

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


# --- manager ---------------------------------------------------------------


class DownloadManager(QObject):
    """Owns the task list and the thread pool that runs downloads."""

    task_changed = pyqtSignal(str)    # task id -> UI should refresh that row

    def __init__(self, max_concurrent: int = 3, use_aria2c: bool = True):
        super().__init__()
        self.tasks: dict[str, DownloadTask] = {}
        self.use_aria2c = use_aria2c
        self.pool = QThreadPool.globalInstance()
        self.set_max_concurrent(max_concurrent)

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

        worker = DownloadWorker(task, self.use_aria2c)
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
