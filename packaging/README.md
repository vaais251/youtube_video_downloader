# Packaging — building the Windows installer

This produces an **IDM-style single setup `.exe`** your users can run to install
everything (Python runtime, PyQt6, yt-dlp, and ffmpeg/aria2c are all bundled —
nothing else needs to be installed on the target machine).

## What you get

- `dist\YT Downloader\` — the standalone app folder (runs without Python)
- `packaging\dist_installer\YT-Downloader-Setup.exe` — the installer to share

## Prerequisites (build machine only)

- [UV](https://docs.astral.sh/uv/) (already used for development)
- [Inno Setup 6](https://jrsoftware.org/isdl.php) — for the installer step
  (`winget install JRSoftware.InnoSetup`)
- Internet access the first time (to download ffmpeg + aria2c)

## One command

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

This will:

1. Download **ffmpeg** and **aria2c** into `packaging\vendor\bin\`
2. Run **PyInstaller** (`yt-downloader.spec`) → `dist\YT Downloader\`
3. Run **Inno Setup** (`installer.iss`) → `YT-Downloader-Setup.exe`

Useful flags:

- `-SkipTools` — reuse already-downloaded `vendor\bin` binaries
- `-SkipInstaller` — build just the app folder (skip Inno Setup)

## Build steps individually

```powershell
# app folder only
uv run --with pyinstaller pyinstaller packaging\yt-downloader.spec --noconfirm --clean

# installer (after the app folder exists)
iscc packaging\installer.iss
```

## How the bundled tools are found

`utils.add_bundled_tools_to_path()` (called at startup) prepends the app's
`bin\` folder to `PATH`, so the normal ffmpeg/aria2c detection picks up the
bundled copies. If you ship without them, the app still works for users who have
them on PATH (and degrades to progressive/720p when ffmpeg is missing).

## The browser extension

The extension folder is bundled into the install (`{app}\extension`). On first
launch the app shows an onboarding dialog with:

- **Open chrome://extensions** — launches Chrome/Edge straight to the page
- **Open extension folder** — reveals `{app}\extension` to use with *Load unpacked*

> Chrome does not allow apps to silently enable unpacked extensions (a security
> restriction). The onboarding gets the user there in two clicks; the only manual
> step is toggling Developer mode + Load unpacked, once. Publishing to the Chrome
> Web Store later would let users install with a single click.

## Optional: app icon

Drop an `app.ico` into `packaging\` and both PyInstaller and Inno Setup will use
it automatically (the spec/iss check for its presence).

## Code signing (optional but recommended)

Unsigned installers trigger SmartScreen warnings. If you have a code-signing
certificate, sign both `dist\YT Downloader\YT Downloader.exe` and the final
`YT-Downloader-Setup.exe` with `signtool`.
