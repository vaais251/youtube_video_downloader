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
    AUDIO_MP3,
    CANCELED,
    COMPLETED,
    DOWNLOADING,
    ERROR,
    PAUSED,
    QUEUED,
    DownloadManager,
    DownloadTask,
    InfoWorker,
    build_format_options,
)
from .ipc_server import IpcBridge, IpcServer


# --- visual theme ----------------------------------------------------------

STYLE = """
* { font-family: 'Segoe UI', system-ui, sans-serif; }
QMainWindow, QWidget { background: #f4f5f7; color: #1f2328; font-size: 13px; }

QToolBar { background: #ffffff; border: none; border-bottom: 1px solid #e3e6ea;
           spacing: 8px; padding: 6px 10px; }
QToolBar QToolButton { padding: 6px 12px; border-radius: 8px; }
QToolBar QToolButton:hover { background: #f0f1f3; }

QLineEdit { background: #ffffff; border: 1px solid #d0d7de; border-radius: 9px;
            padding: 9px 12px; selection-background-color: #e53935; }
QLineEdit:focus { border: 1px solid #e53935; }
QLineEdit:read-only { background: #eef0f2; color: #4a4f55; }

QComboBox { background: #ffffff; border: 1px solid #d0d7de; border-radius: 9px;
            padding: 8px 12px; }
QComboBox:focus { border: 1px solid #e53935; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox QAbstractItemView { background: #ffffff; border: 1px solid #d0d7de;
            selection-background-color: #e53935; selection-color: #ffffff;
            outline: none; }

QPushButton { background: #ffffff; border: 1px solid #d0d7de; border-radius: 9px;
              padding: 8px 16px; }
QPushButton:hover { background: #f0f1f3; }
QPushButton:pressed { background: #e6e8eb; }
QPushButton:disabled { color: #9aa0a6; background: #f4f5f7; }

QPushButton#primary { background: #e53935; color: #ffffff; border: none;
                      font-weight: 600; }
QPushButton#primary:hover { background: #d32f2f; }
QPushButton#primary:pressed { background: #b71c1c; }
QPushButton#primary:disabled { background: #f1a9a7; color: #ffffff; }

QPushButton#ghost { border: none; background: transparent; padding: 6px 10px;
                    color: #57606a; }
QPushButton#ghost:hover { background: #eef0f2; color: #1f2328; }

QProgressBar { border: none; background: #e6e8eb; border-radius: 5px;
               min-height: 8px; max-height: 8px; text-align: center; }
QProgressBar::chunk { background: #e53935; border-radius: 5px; }

QFrame#queueItem { background: #ffffff; border: 1px solid #e7eaee;
                   border-radius: 14px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #c4c9cf; border-radius: 5px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #aab0b7; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }

QSpinBox { background: #ffffff; border: 1px solid #d0d7de; border-radius: 8px;
           padding: 4px 6px; }
QCheckBox { spacing: 6px; }
QStatusBar { background: #ffffff; border-top: 1px solid #e3e6ea; color: #57606a; }
QLabel#h1 { font-size: 15px; font-weight: 700; }
QLabel#section { font-size: 13px; font-weight: 600; color: #3a4047; }
"""


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
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # title + kind badge
        top = QHBoxLayout()
        top.setSpacing(8)
        self.title = QLabel(task.title or task.url)
        self.title.setStyleSheet("font-weight: 600; font-size: 13px;")
        self.title.setWordWrap(False)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self.title, 1)
        self.badge = QLabel("MP3" if task.audio_only else "Video")
        self.badge.setStyleSheet(
            "color: #57606a; background: #eef0f2; border-radius: 6px;"
            " padding: 2px 8px; font-size: 11px; font-weight: 600;"
        )
        top.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self.status = QLabel()
        self.status.setStyleSheet("color: #57606a; font-size: 12px;")
        bottom.addWidget(self.status, 1)

        self.btn_toggle = QPushButton("Pause")
        self.btn_toggle.setObjectName("ghost")
        self.btn_toggle.clicked.connect(self._toggle)
        bottom.addWidget(self.btn_toggle)

        self.btn_open = QPushButton("Open")
        self.btn_open.setObjectName("ghost")
        self.btn_open.clicked.connect(self._open)
        bottom.addWidget(self.btn_open)

        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setObjectName("ghost")
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

    def _set_bar_color(self, color: str) -> None:
        self.bar.setStyleSheet(
            "QProgressBar { border: none; background: #e6e8eb; border-radius: 5px;"
            " min-height: 8px; max-height: 8px; }"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 5px; }}"
        )

    # -- view
    def refresh(self):
        t = self.task
        self.bar.setValue(int(t.progress))
        self.title.setText(t.title or t.url)
        self.status.setStyleSheet("color: #57606a; font-size: 12px;")
        pct = f"{int(t.progress)}%"

        if t.status == DOWNLOADING:
            self._set_bar_color("#e53935")
            meta = [p for p in (
                t.downloaded and f"{t.downloaded} / {t.total}" or t.total,
                t.speed, t.eta and f"ETA {t.eta}") if p]
            tail = "  ·  ".join(meta)
            self.status.setText(f"Downloading {pct}" + (f"  ·  {tail}" if tail else "…"))
            self.btn_toggle.setText("Pause")
            self.btn_toggle.setEnabled(True)
        elif t.status == QUEUED:
            self._set_bar_color("#9aa0a6")
            self.status.setText("Queued")
            self.btn_toggle.setText("Pause")
            self.btn_toggle.setEnabled(True)
        elif t.status == PAUSED:
            self._set_bar_color("#f0a020")
            self.status.setText(f"Paused at {pct}")
            self.btn_toggle.setText("Resume")
            self.btn_toggle.setEnabled(True)
        elif t.status == COMPLETED:
            self._set_bar_color("#2e9e5b")
            self.status.setText("Completed")
            self.status.setStyleSheet("color: #2e9e5b; font-size: 12px; font-weight: 600;")
            self.btn_toggle.setText("Done")
            self.btn_toggle.setEnabled(False)
            self.bar.setValue(100)
        elif t.status == ERROR:
            self._set_bar_color("#d32f2f")
            self.status.setText(f"Error: {t.error[:120]}")
            self.status.setStyleSheet("color: #d32f2f; font-size: 12px;")
            self.btn_toggle.setText("Retry")
            self.btn_toggle.setEnabled(True)
        elif t.status == CANCELED:
            self._set_bar_color("#9aa0a6")
            self.status.setText("Canceled")
            self.btn_toggle.setText("Retry")
            self.btn_toggle.setEnabled(True)


# --- main window -----------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YT Downloader")
        self.resize(860, 680)
        self.setMinimumSize(640, 480)
        self.setStyleSheet(STYLE)

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
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(14)

        # toolbar
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        act_update = QAction("⟳  Update yt-dlp", self)
        act_update.triggered.connect(self._update_ytdlp)
        tb.addAction(act_update)
        tb.addSeparator()
        lbl_conc = QLabel("  Concurrent ")
        lbl_conc.setStyleSheet("color: #57606a;")
        tb.addWidget(lbl_conc)
        self.spin_conc = QSpinBox()
        self.spin_conc.setRange(1, 10)
        self.spin_conc.setValue(self.manager.pool.maxThreadCount())
        self.spin_conc.valueChanged.connect(self._on_conc_changed)
        tb.addWidget(self.spin_conc)
        spacer = QWidget()
        spacer.setFixedWidth(12)
        tb.addWidget(spacer)
        self.chk_aria = QCheckBox("aria2c (multi-connection)")
        self.chk_aria.setChecked(self.manager.use_aria2c)
        self.chk_aria.toggled.connect(self._on_aria_toggled)
        tb.addWidget(self.chk_aria)

        # header
        header = QLabel("YT Downloader")
        header.setObjectName("h1")
        root.addWidget(header)

        # --- input card ---
        card = QFrame()
        card.setObjectName("queueItem")  # reuse the white rounded-card style
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(16, 16, 16, 16)
        card_l.setSpacing(12)

        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Paste a YouTube URL…")
        self.url_edit.returnPressed.connect(self._fetch)
        url_row.addWidget(self.url_edit, 1)
        self.btn_fetch = QPushButton("Fetch")
        self.btn_fetch.setObjectName("primary")
        self.btn_fetch.clicked.connect(self._fetch)
        url_row.addWidget(self.btn_fetch)
        card_l.addLayout(url_row)

        self.title_label = QLabel("")
        self.title_label.setStyleSheet("color: #3a4047;")
        self.title_label.setWordWrap(True)
        self.title_label.hide()
        card_l.addWidget(self.title_label)

        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(8)
        quality_lbl = QLabel("Quality")
        quality_lbl.setStyleSheet("color: #57606a;")
        fmt_row.addWidget(quality_lbl)
        self.format_combo = QComboBox()
        self.format_combo.setMinimumWidth(220)
        self.format_combo.setEnabled(False)
        fmt_row.addWidget(self.format_combo, 1)
        self.btn_add = QPushButton("Add to Queue")
        self.btn_add.setObjectName("primary")
        self.btn_add.setEnabled(False)
        self.btn_add.clicked.connect(self._add_to_queue)
        fmt_row.addWidget(self.btn_add)
        card_l.addLayout(fmt_row)

        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        save_lbl = QLabel("Save to")
        save_lbl.setStyleSheet("color: #57606a;")
        out_row.addWidget(save_lbl)
        self.folder_edit = QLineEdit(self.output_dir)
        self.folder_edit.setReadOnly(True)
        out_row.addWidget(self.folder_edit, 1)
        btn_browse = QPushButton("Browse…")
        btn_browse.clicked.connect(self._choose_folder)
        out_row.addWidget(btn_browse)
        card_l.addLayout(out_row)

        root.addWidget(card)

        # queue
        queue_label = QLabel("Downloads")
        queue_label.setObjectName("section")
        root.addWidget(queue_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        container = QWidget()
        self.queue_layout = QVBoxLayout(container)
        self.queue_layout.setContentsMargins(0, 0, 0, 0)
        self.queue_layout.setSpacing(10)
        self.empty_label = QLabel("No downloads yet — fetch a URL above,\n"
                                  "or send one from the browser extension.")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #9aa0a6; padding: 28px;")
        self.queue_layout.addWidget(self.empty_label)
        self.queue_layout.addStretch(1)
        self.scroll.setWidget(container)
        root.addWidget(self.scroll, 1)

        self.statusBar()

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
        self.bridge.download_requested.connect(self._on_ipc_download)
        self.ipc = IpcServer(self.bridge)
        if not self.ipc.start():
            self.statusBar().showMessage(
                f"Note: extension port {utils.IPC_PORT} is busy — browser hand-off disabled."
            )

    def _on_ipc_url(self, url: str):
        # "Send to app" flow: bring the window forward, prefill, auto-fetch.
        self.raise_()
        self.activateWindow()
        self.url_edit.setText(url)
        self._fetch()

    def _on_ipc_download(self, payload: dict):
        """Direct download started from the extension — queue it silently."""
        url = (payload.get("url") or "").strip()
        if not url:
            return
        selector = payload.get("selector") or "bestvideo+bestaudio/best"
        audio_only = bool(payload.get("audio_only")) or selector == AUDIO_MP3
        title = payload.get("title") or url

        task = DownloadTask(
            url=url,
            title=title,
            format_selector="bestaudio/best" if audio_only else selector,
            audio_only=audio_only,
            output_dir=self.output_dir,
        )
        self.manager.add_task(task)
        self._add_row(task)
        self.statusBar().showMessage(f"Added from browser: {title[:60]}")

    # -- fetch / formats
    def _fetch(self):
        url = self.url_edit.text().strip()
        if not url:
            return
        self.btn_fetch.setEnabled(False)
        self.btn_fetch.setText("Fetching…")
        self.title_label.setText("Fetching info…")
        self.title_label.show()
        worker = InfoWorker(url)
        worker.signals.fetched.connect(self._on_info)
        worker.signals.error.connect(self._on_info_error)
        QThreadPool.globalInstance().start(worker)

    def _on_info_error(self, msg: str):
        self.btn_fetch.setEnabled(True)
        self.btn_fetch.setText("Fetch")
        self.title_label.hide()
        QMessageBox.warning(self, "Fetch failed", msg)

    def _on_info(self, info: dict):
        self.btn_fetch.setEnabled(True)
        self.btn_fetch.setText("Fetch")
        self._pending_info = info

        title = info.get("title", "")
        dur = info.get("duration")
        dur_s = f"  ·  {int(dur) // 60}:{int(dur) % 60:02d}" if dur else ""
        self.title_label.setText(f"<b>{title}</b>{dur_s}")
        self.title_label.show()

        self.format_combo.clear()
        for opt in build_format_options(info):
            self.format_combo.addItem(opt["label"], opt["selector"])
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
        self.title_label.hide()
        self.format_combo.clear()
        self.format_combo.setEnabled(False)
        self.btn_add.setEnabled(False)
        self._pending_info = None

    def _add_row(self, task: DownloadTask):
        self.empty_label.hide()
        row = QueueItemWidget(task, self.manager)
        self.rows[task.id] = row
        # insert above the empty label + trailing stretch
        self.queue_layout.insertWidget(0, row)

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
