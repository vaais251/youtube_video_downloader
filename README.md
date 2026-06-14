# YT Downloader

A clean, IDM-style desktop YouTube downloader.

- **GUI:** PyQt6
- **Engine:** [yt-dlp](https://github.com/yt-dlp/yt-dlp) (bundled as a dependency, one-click updatable)
- **Merging / MP3:** ffmpeg
- **Speed:** aria2c multi-connection downloads when available
- **Queue:** pause / resume / cancel / retry, per-item progress bars
- **History:** persistent, IDM-style download history you can clear or prune
- **Browser hand-off:** a Chrome extension with an in-player download button

## Features

- Paste a YouTube URL and fetch available qualities
- Pick a resolution (720p, 1080p, …) or **Audio only (MP3)**
- Multi-connection downloading via aria2c (toggle in the toolbar)
- Download queue with progress, speed, ETA, and pause/resume
- **Download history** in a separate tab — open file, open folder, re-download,
  delete from disk, remove from list, or clear all (persisted to
  `~/.ytdownloader/history.json`)
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
extension talks to it directly, so you can **pick a quality and download from the
browser without ever touching the desktop window**.

To install (unpacked):

1. Open `chrome://extensions`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked** and select the `extension/` folder

Ways to download (the desktop app must be running):

- **In-player button (IDM-style):** on any YouTube watch page a small
  **⬇ Download** button appears in the top-left of the video. Click it → a popup
  lets you pick a quality (or *Audio only (MP3)*) → **Download**. Nothing else to
  touch. (The content script routes requests through the extension's background
  worker, so YouTube's CSP doesn't block it.)
- **Popup (choose quality):** click the toolbar icon for the same picker for the
  current tab.
- **Right-click → Download (best quality):** true one-click at best quality.
- **Right-click → Download audio (MP3):** one-click audio extraction.

Endpoints used by the extension:

| Method | Path        | Purpose                                  |
|--------|-------------|------------------------------------------|
| GET    | `/ping`     | liveness check                           |
| POST   | `/formats`  | `{url}` → available quality options      |
| POST   | `/download` | `{url, selector, audio_only, title}`     |
| POST   | `/add`      | `{url}` → open it in the app to pick      |

> The extension references optional notification icons under `extension/icons/`.
> Notifications are best-effort; the extension works without the icon files.

## Project layout

```
src/ytdownloader/
  main.py              entry point
  app.py               PyQt6 window, tabs (Downloads/History), settings, updater
  download_manager.py  yt-dlp workers + queue/pause/resume/cancel, format helpers
  history.py           persistent download history (JSON)
  ipc_server.py        localhost server for the Chrome extension
  utils.py             ffmpeg/aria2c detection, helpers
extension/             Manifest V3 Chrome extension
  background.js        service worker: context menus + app relay
  content.js/.css      in-player download button + quality popup
  popup.html/.js       toolbar popup quality picker
```

## Notes & limitations

- **Pause** is most responsive with yt-dlp's native downloader. With **aria2c**,
  a download pauses between fragments/files rather than instantly mid-stream.
  Resuming continues from the partial `.part` file either way.
- Single videos only by default (`noplaylist=True`).
- Downloading is subject to YouTube's Terms of Service and copyright law — use
  it for content you have the right to download.
