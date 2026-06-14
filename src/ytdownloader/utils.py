"""Environment detection and small shared helpers."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


# Port the local IPC server listens on for the Chrome extension.
IPC_HOST = "127.0.0.1"
IPC_PORT = 8765


def _base_dirs() -> list[Path]:
    """Directories to search for bundled resources (bin/, extension/).

    Covers a PyInstaller build (frozen) and a normal source checkout.
    """
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(Path(meipass))          # onefile temp / onedir root
        dirs.append(Path(sys.executable).parent)  # the install directory
    else:
        # src/ytdownloader/utils.py -> project root is two parents up
        dirs.append(Path(__file__).resolve().parents[2])
    return dirs


def add_bundled_tools_to_path() -> None:
    """Prepend any bundled ``bin/`` folder (ffmpeg, aria2c) to PATH.

    After this runs, the normal ``shutil.which`` detection finds the bundled
    binaries automatically, so the rest of the app needs no changes.
    """
    for base in _base_dirs():
        bin_dir = base / "bin"
        if bin_dir.is_dir():
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def extension_dir() -> str | None:
    """Locate the bundled Chrome extension folder, if present."""
    for base in _base_dirs():
        ext = base / "extension"
        if (ext / "manifest.json").exists():
            return str(ext)
    return None


def app_icon_path() -> str | None:
    """Locate app.ico (bundled at the root when frozen, else packaging/)."""
    for base in _base_dirs():
        for cand in (base / "app.ico", base / "packaging" / "app.ico"):
            if cand.exists():
                return str(cand)
    return None


def find_chromium_browser() -> str | None:
    """Find a Chromium-based browser (Chrome, then Edge, then Brave) on Windows.

    Used to open ``chrome://extensions`` directly, which a normal
    ``webbrowser.open`` cannot do for the ``chrome://`` scheme.
    """
    if not sys.platform.startswith("win"):
        return shutil.which("google-chrome") or shutil.which("chromium")

    candidates = [
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
    ]
    for c in candidates:
        p = Path(os.path.expandvars(c))
        if p.exists():
            return str(p)
    return None


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
