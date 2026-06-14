"""Environment detection and small shared helpers."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


# Port the local IPC server listens on for the Chrome extension.
IPC_HOST = "127.0.0.1"
IPC_PORT = 8765


def find_executable(name: str) -> str | None:
    """Return the full path to ``name`` if it is on PATH, else None.

    On Windows ``shutil.which`` already appends ``.exe``/``.bat`` etc.
    """
    return shutil.which(name)


def ffmpeg_path() -> str | None:
    """Locate the ffmpeg binary (needed to merge video+audio streams)."""
    return find_executable("ffmpeg")


def ffmpeg_dir() -> str | None:
    """Directory containing ffmpeg, which is what yt-dlp wants."""
    p = ffmpeg_path()
    return str(Path(p).parent) if p else None


def aria2c_path() -> str | None:
    """Locate aria2c, used as an external multi-connection downloader."""
    return find_executable("aria2c")


def default_download_dir() -> str:
    """A sensible default output folder (the user's Downloads folder)."""
    home = Path.home()
    downloads = home / "Downloads"
    if downloads.exists():
        return str(downloads)
    return str(home)


def open_in_file_manager(path: str) -> None:
    """Reveal a file or folder in the OS file manager."""
    p = Path(path)
    target = p if p.is_dir() else p.parent
    try:
        if sys.platform.startswith("win"):
            if p.exists() and not p.is_dir():
                # /select highlights the file in Explorer.
                os.system(f'explorer /select,"{p}"')
            else:
                os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open "{target}"')
        else:
            os.system(f'xdg-open "{target}"')
    except Exception:
        pass


def human_size(num: float | int | None) -> str:
    if not num:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
