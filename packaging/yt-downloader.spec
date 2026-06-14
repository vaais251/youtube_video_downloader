# PyInstaller spec for YT Downloader (onedir build).
#
# Build with:
#   uv run --with pyinstaller pyinstaller packaging/yt-downloader.spec --noconfirm
#
# Bundles: the app, yt-dlp (incl. its lazy extractors), the Chrome extension
# folder, and any vendored binaries in packaging/vendor/bin (ffmpeg, aria2c).

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent  # packaging/ -> project root

datas = []
binaries = []
hiddenimports = []

# yt-dlp pulls extractors in lazily; collect everything so they all ship.
_d, _b, _h = collect_all("yt_dlp")
datas += _d
binaries += _b
hiddenimports += _h

# Ship the Chrome extension alongside the app so onboarding can point to it.
ext = ROOT / "extension"
if ext.is_dir():
    for f in ext.rglob("*"):
        if f.is_file():
            dest = Path("extension") / f.relative_to(ext).parent
            datas.append((str(f), str(dest)))

# Vendored ffmpeg / aria2c (place *.exe under packaging/vendor/bin) -> ./bin
vendor_bin = ROOT / "packaging" / "vendor" / "bin"
if vendor_bin.is_dir():
    for f in vendor_bin.glob("*"):
        if f.is_file():
            binaries.append((str(f), "bin"))

icon_file = ROOT / "packaging" / "app.ico"
icon = str(icon_file) if icon_file.exists() else None

# Ship the .ico so the running window/taskbar can use it too.
if icon_file.exists():
    datas.append((str(icon_file), "."))

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="YT Downloader",
    console=False,           # windowed app, no console
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="YT Downloader",
)
