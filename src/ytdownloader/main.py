"""Application entry point."""

from __future__ import annotations

import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from . import utils
from .app import MainWindow


def main() -> int:
    # Make bundled ffmpeg/aria2c (if shipped in ./bin) discoverable.
    utils.add_bundled_tools_to_path()

    app = QApplication(sys.argv)
    app.setApplicationName("YT Downloader")

    icon_path = utils.app_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
