# YT Downloader

A clean, IDM-style desktop YouTube downloader.

- **GUI:** PyQt6
- **Engine:** [yt-dlp](https://github.com/yt-dlp/yt-dlp) (bundled as a dependency, one-click updatable)
- **Merging / MP3:** ffmpeg
- **Speed:** aria2c multi-connection downloads when available
- **Queue:** pause / resume / cancel / retry, per-item progress bars
- **Browser hand-off:** a small Chrome extension sends the current tab's URL to the app

## Features

- Paste a YouTube URL and fetch available qualities
- Pick a resolution (720p, 1080p, …) or **Audio only (MP3)**
- Multi-connection downloading via aria2c (toggle in the toolbar)
- Download queue with progress, speed, ETA, and pause/resume
- Choose the output folder (remembered between runs)
- **Update yt-dlp** button — YouTube breaks downloaders often; update without reinstalling

## Requirements

- Python 3.10+
- [UV](https://docs.astral.sh/uv/) for environment management
- **ffmpeg** on your PATH (required to merge video+audio and to make MP3s)
- **aria2c** on your PATH (optional, for faster multi-connection downloads)

### Installing ffmpeg / aria2c on Windows

```powershell
winget install Gyan.FFmpeg
winget install aria2.aria2
```

Restart the app afterwards so it picks them up. The status bar shows what was detected.

## Setup & run (UV)

```powershell
# from the project root
uv sync
uv run yt-downloader
```

Or without installing the script entry point:

```powershell
uv run python -m ytdownloader
```

## Updating yt-dlp

Click **Update yt-dlp** in the toolbar (runs `uv pip install --upgrade yt-dlp`),
or from a shell:

```powershell
uv pip install --upgrade yt-dlp
```

## Chrome extension

The desktop app runs a tiny local server on `http://127.0.0.1:8765`. The
extension POSTs the current tab's URL there; the app pops to the front and
fetches its formats automatically.

To install (unpacked):

1. Open `chrome://extensions`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked** and select the `extension/` folder

Then either click the toolbar icon → **Send current tab**, or right-click a page,
link, or video → **Send to YT Downloader**. The desktop app must be running.

> The extension references optional notification icons under `extension/icons/`.
> Notifications are best-effort; the extension works without the icon files.

## Project layout

```
src/ytdownloader/
  main.py              entry point
  app.py               PyQt6 window, queue rows, settings, yt-dlp updater
  download_manager.py  yt-dlp workers + queue/pause/resume/cancel
  ipc_server.py        localhost server for the Chrome extension
  utils.py             ffmpeg/aria2c detection, helpers
extension/             Manifest V3 Chrome extension
```

## Notes & limitations

- **Pause** is most responsive with yt-dlp's native downloader. With **aria2c**,
  a download pauses between fragments/files rather than instantly mid-stream.
  Resuming continues from the partial `.part` file either way.
- Single videos only by default (`noplaylist=True`).
- Downloading is subject to YouTube's Terms of Service and copyright law — use
  it for content you have the right to download.
