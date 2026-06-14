"""PyQt6 GUI: URL bar, format picker, output folder, and the download queue."""

from __future__ import annotations

import subprocess
import sys

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, QSettings, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import utils
from .download_manager import (
    CANCELED,
    COMPLETED,
    DOWNLOADING,
    ERROR,
    PAUSED,
    QUEUED,
    DownloadManager,
    DownloadTask,
    InfoWorker,
)
from .ipc_server import IpcBridge, IpcServer


AUDIO_MP3 = "__audio_mp3__"  # sentinel selector meaning "audio only -> MP3"


# --- yt-dlp self-update worker --------------------------------------------


class _UpdateSignals(QObject):
    done = pyqtSignal(bool, str)


class UpdateWorker(QRunnable):
    """Upgrades the yt-dlp package in the current environment."""

    def __init__(self):
        super().__init__()
        self.signals = _UpdateSignals()

    def run(self) -> None:
        attempts = [
            ["uv", "pip", "install", "--upgrade", "yt-dlp"],
            [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
        ]
        last = ""
        for cmd in attempts:
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=300
                )
                if proc.returncode == 0:
                    out = (proc.stdout or "").strip().splitlines()
                    tail = out[-1] if out else "yt-dlp is up to date."
                    self.signals.done.emit(True, tail)
                    return
                last = (proc.stderr or proc.stdout or "").strip()
            except FileNotFoundError:
                continue
            except Exception as exc:  # noqa: BLE001
                last = str(exc)
        self.signals.done.emit(False, last or "Could not run the updater.")


# --- per-download row widget ----------------------------------------------


class QueueItemWidget(QFrame):
    def __init__(self, task: DownloadTask, manager: DownloadManager):
        super().__init__()
        self.task = task
        self.manager = manager
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("queueItem")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        self.title = QLabel(task.title or task.url)
        self.title.setStyleSheet("font-weight: 600;")
        self.title.setWordWrap(False)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.title)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(True)
        layout.addWidget(self.bar)

        bottom = QHBoxLayout()
        self.status = QLabel()
        self.status.setStyleSheet("color: #555;")
        bottom.addWidget(self.status, 1)

        self.btn_toggle = QPushButton("Pause")
        self.btn_toggle.clicked.connect(self._toggle)
        bottom.addWidget(self.btn_toggle)

        self.btn_open = QPushButton("Open")
        self.btn_open.clicked.connect(self._open)
        bottom.addWidget(self.btn_open)

        self.btn_remove = QPushButton("Remove")
        self.btn_remove.clicked.connect(self._remove)
        bottom.addWidget(self.btn_remove)

        layout.addLayout(bottom)
        self.refresh()

    # -- actions
    def _toggle(self):
        s = self.task.status
        if s in (DOWNLOADING, QUEUED):
            self.manager.pause(self.task.id)
        elif s in (PAUSED, ERROR, CANCELED):
            if s in (ERROR, CANCELED):
                self.manager.retry(self.task.id)
            else:
                self.manager.resume(self.task.id)

    def _open(self):
        target = self.task.filename or self.task.output_dir
        utils.open_in_file_manager(target)

    def _remove(self):
        self.manager.remove(self.task.id)
        self.setParent(None)
        self.deleteLater()

    # -- view
    def refresh(self):
        t = self.task
        self.bar.setValue(int(t.progress))
        self.title.setText(t.title or t.url)

        if t.status == DOWNLOADING:
            parts = [p for p in (t.downloaded and f"{t.downloaded}/{t.total}" or t.total,
                                 t.speed, t.eta and f"ETA {t.eta}") if p]
            self.status.setText("Downloading  ·  " + "  ·  ".join(parts) if parts
                                else "Downloading…")
            self.btn_toggle.setText("Pause")
            self.btn_toggle.setEnabled(True)
        elif t.status == QUEUED:
            self.status.setText("Queued")
            self.btn_toggle.setText("Pause")
            self.btn_toggle.setEnabled(True)
        elif t.status == PAUSED:
            self.status.setText("Paused")
            self.btn_toggle.setText("Resume")
            self.btn_toggle.setEnabled(True)
        elif t.status == COMPLETED:
            self.status.setText("Completed")
            self.btn_toggle.setText("Done")
            self.btn_toggle.setEnabled(False)
            self.bar.setValue(100)
        elif t.status == ERROR:
            self.status.setText(f"Error: {t.error[:120]}")
            self.status.setStyleSheet("color: #c0392b;")
            self.btn_toggle.setText("Retry")
            self.btn_toggle.setEnabled(True)
        elif t.status == CANCELED:
            self.status.setText("Canceled")
            self.btn_toggle.setText("Retry")
            self.btn_toggle.setEnabled(True)


# --- main window -----------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YT Downloader")
        self.resize(820, 640)

        self.settings = QSettings("ytdownloader", "YTDownloader")
        self.output_dir = self.settings.value("output_dir", utils.default_download_dir())
        max_conc = int(self.settings.value("max_concurrent", 3))
        use_aria = self.settings.value("use_aria2c", True, type=bool)

        self.manager = DownloadManager(max_concurrent=max_conc, use_aria2c=use_aria)
        self.manager.task_changed.connect(self._on_task_changed)
        self.rows: dict[str, QueueItemWidget] = {}
        self._pending_info = None  # cached info dict after a fetch

        self._build_ui()
        self._start_ipc()
        self._report_environment()

    # -- UI construction
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # toolbar
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        act_update = QAction("Update yt-dlp", self)
        act_update.triggered.connect(self._update_ytdlp)
        tb.addAction(act_update)
        tb.addSeparator()
        tb.addWidget(QLabel("  Concurrent: "))
        self.spin_conc = QSpinBox()
        self.spin_conc.setRange(1, 10)
        self.spin_conc.setValue(self.manager.pool.maxThreadCount())
        self.spin_conc.valueChanged.connect(self._on_conc_changed)
        tb.addWidget(self.spin_conc)
        self.chk_aria = QCheckBox(" Use aria2c (multi-connection)")
        self.chk_aria.setChecked(self.manager.use_aria2c)
        self.chk_aria.toggled.connect(self._on_aria_toggled)
        tb.addWidget(self.chk_aria)

        # URL row
        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Paste a YouTube URL…")
        self.url_edit.returnPressed.connect(self._fetch)
        url_row.addWidget(self.url_edit, 1)
        self.btn_fetch = QPushButton("Fetch")
        self.btn_fetch.clicked.connect(self._fetch)
        url_row.addWidget(self.btn_fetch)
        root.addLayout(url_row)

        # format row
        fmt_row = QHBoxLayout()
        self.title_label = QLabel("")
        self.title_label.setStyleSheet("color: #333;")
        fmt_row.addWidget(self.title_label, 1)
        self.format_combo = QComboBox()
        self.format_combo.setMinimumWidth(240)
        self.format_combo.setEnabled(False)
        fmt_row.addWidget(self.format_combo)
        self.btn_add = QPushButton("Add to Queue")
        self.btn_add.setEnabled(False)
        self.btn_add.clicked.connect(self._add_to_queue)
        fmt_row.addWidget(self.btn_add)
        root.addLayout(fmt_row)

        # output folder row
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Save to:"))
        self.folder_edit = QLineEdit(self.output_dir)
        self.folder_edit.setReadOnly(True)
        out_row.addWidget(self.folder_edit, 1)
        btn_browse = QPushButton("Browse…")
        btn_browse.clicked.connect(self._choose_folder)
        out_row.addWidget(btn_browse)
        root.addLayout(out_row)

        # queue
        root.addWidget(self._hline())
        queue_label = QLabel("Downloads")
        queue_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        root.addWidget(queue_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        container = QWidget()
        self.queue_layout = QVBoxLayout(container)
        self.queue_layout.setContentsMargins(0, 0, 0, 0)
        self.queue_layout.setSpacing(8)
        self.queue_layout.addStretch(1)
        self.scroll.setWidget(container)
        root.addWidget(self.scroll, 1)

        self.statusBar()

    @staticmethod
    def _hline() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    # -- environment / ipc
    def _report_environment(self):
        msgs = []
        if not utils.ffmpeg_path():
            msgs.append("⚠ ffmpeg not found — merging/MP3 disabled. Install it and restart.")
        if self.manager.use_aria2c and not utils.aria2c_path():
            msgs.append("aria2c not found — using yt-dlp's downloader.")
        self.statusBar().showMessage("   ".join(msgs) if msgs
                                     else "Ready.  ffmpeg ✓  "
                                          + ("aria2c ✓" if utils.aria2c_path() else "aria2c ✗"))

    def _start_ipc(self):
        self.bridge = IpcBridge()
        self.bridge.url_received.connect(self._on_ipc_url)
        self.ipc = IpcServer(self.bridge)
        if not self.ipc.start():
            self.statusBar().showMessage(
                f"Note: extension port {utils.IPC_PORT} is busy — browser hand-off disabled."
            )

    def _on_ipc_url(self, url: str):
        # Bring the window forward and prefill, then auto-fetch.
        self.raise_()
        self.activateWindow()
        self.url_edit.setText(url)
        self._fetch()

    # -- fetch / formats
    def _fetch(self):
        url = self.url_edit.text().strip()
        if not url:
            return
        self.btn_fetch.setEnabled(False)
        self.btn_fetch.setText("Fetching…")
        self.title_label.setText("Fetching info…")
        worker = InfoWorker(url)
        worker.signals.fetched.connect(self._on_info)
        worker.signals.error.connect(self._on_info_error)
        QThreadPool.globalInstance().start(worker)

    def _on_info_error(self, msg: str):
        self.btn_fetch.setEnabled(True)
        self.btn_fetch.setText("Fetch")
        self.title_label.setText("")
        QMessageBox.warning(self, "Fetch failed", msg)

    def _on_info(self, info: dict):
        self.btn_fetch.setEnabled(True)
        self.btn_fetch.setText("Fetch")
        self._pending_info = info

        title = info.get("title", "")
        dur = info.get("duration")
        dur_s = f"  ({int(dur)//60}:{int(dur)%60:02d})" if dur else ""
        self.title_label.setText(f"{title}{dur_s}")

        self.format_combo.clear()
        self.format_combo.addItem("Best quality (auto)", "bestvideo+bestaudio/best")

        heights = set()
        for f in info.get("formats", []) or []:
            if f.get("vcodec") and f.get("vcodec") != "none" and f.get("height"):
                heights.add(int(f["height"]))
        for h in sorted(heights, reverse=True):
            sel = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]"
            self.format_combo.addItem(f"{h}p", sel)

        self.format_combo.addItem("Audio only (MP3)", AUDIO_MP3)
        self.format_combo.setEnabled(True)
        self.btn_add.setEnabled(True)

    # -- queue
    def _add_to_queue(self):
        if not self._pending_info:
            return
        url = self.url_edit.text().strip() or self._pending_info.get("webpage_url", "")
        selector = self.format_combo.currentData()
        audio_only = selector == AUDIO_MP3

        if audio_only and not utils.ffmpeg_path():
            QMessageBox.warning(self, "ffmpeg required",
                                "MP3 extraction needs ffmpeg, which was not found.")
            return

        task = DownloadTask(
            url=url,
            title=self._pending_info.get("title", url),
            format_selector="bestaudio/best" if audio_only else selector,
            audio_only=audio_only,
            output_dir=self.output_dir,
        )
        self.manager.add_task(task)
        self._add_row(task)

        # reset the input for the next URL
        self.url_edit.clear()
        self.title_label.setText("")
        self.format_combo.clear()
        self.format_combo.setEnabled(False)
        self.btn_add.setEnabled(False)
        self._pending_info = None

    def _add_row(self, task: DownloadTask):
        row = QueueItemWidget(task, self.manager)
        self.rows[task.id] = row
        # insert above the trailing stretch
        self.queue_layout.insertWidget(self.queue_layout.count() - 1, row)

    def _on_task_changed(self, task_id: str):
        row = self.rows.get(task_id)
        if row is not None:
            row.refresh()

    # -- settings handlers
    def _choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Choose output folder", self.output_dir)
        if d:
            self.output_dir = d
            self.folder_edit.setText(d)
            self.settings.setValue("output_dir", d)

    def _on_conc_changed(self, n: int):
        self.manager.set_max_concurrent(n)
        self.settings.setValue("max_concurrent", n)

    def _on_aria_toggled(self, checked: bool):
        self.manager.use_aria2c = checked
        self.settings.setValue("use_aria2c", checked)
        self._report_environment()

    def _update_ytdlp(self):
        self.statusBar().showMessage("Updating yt-dlp…")
        worker = UpdateWorker()
        worker.signals.done.connect(self._on_update_done)
        QThreadPool.globalInstance().start(worker)

    def _on_update_done(self, ok: bool, msg: str):
        self.statusBar().showMessage(msg)
        box = QMessageBox.information if ok else QMessageBox.warning
        box(self, "yt-dlp update", msg + ("\n\nRestart the app to use it." if ok else ""))

    # -- lifecycle
    def closeEvent(self, event):  # noqa: N802
        try:
            self.ipc.stop()
        except Exception:
            pass
        super().closeEvent(event)
