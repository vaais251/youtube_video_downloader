# YT Downloader 2.1

A clean, IDM-style desktop **download manager** — videos *and any file*.

- **General downloads:** the browser extension intercepts downloads of any type
  (zip, exe, pdf, music, movies, …) and downloads them through the app — just
  like IDM. Cookies/referrer are passed so authenticated downloads work.
- **Media sniffing:** detects HLS/DASH streams on any site and downloads them
  with the browser's real headers.
- **GUI:** PyQt6, light **and dark** themes.
- **Media engine:** [yt-dlp](https://github.com/yt-dlp/yt-dlp) (bundled, one-click updatable)
- **File engine:** aria2c multi-connection (with a pure-Python resumable fallback)
- **Merging / MP3:** ffmpeg
- **Queue:** pause / resume / cancel / retry, per-item progress bars, and it now
  **persists across restarts** (optional auto-resume)
- **Categories:** auto-sorts into **Video / Music / Documents / Compressed / Programs**
- **History:** persistent, deletable download history
- **System tray:** close-to-tray, start-with-Windows, pause/resume all
- **Extras:** speed limit, duplicate detection, filename-collision handling,
  clipboard link watching, and a popup **"Grab links on this page"** batch tool

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

- **Automatic capture (the IDM behaviour):** with **Capture browser downloads**
  enabled (toolbar popup), any file you download in the browser — zip, exe, pdf,
  mp3, mp4, … — is intercepted and downloaded through the app instead, with the
  page's cookies/referrer attached. Toggle it off anytime.
- **In-player button (any site):** a **⬇ Download** button floats over videos on
  any website. Click it → pick a quality or a **detected stream** → **Download**.
- **Media sniffing (IDM-style):** the extension watches the page's network
  requests and detects media streams — including **HLS (`.m3u8`)** and **DASH
  (`.mpd`)** — capturing the exact referer/cookies/user-agent the browser used.
  These appear in the button's menu (marked with ●) and download with the right
  headers (HLS/DASH are assembled by yt-dlp + ffmpeg). This is what makes tricky
  streaming sites work.
- **Popup (choose quality):** click the toolbar icon for the same picker.
- **Right-click → Download video / audio (MP3):** one-click media download.
- **Right-click a link → Download this link with YT Downloader:** capture any
  direct link as a file.

Capturing needs broader permissions (`downloads`, `cookies`, all-sites host
access) so the extension can see downloads and read cookies for the file's site.
Images are excluded by default so it doesn't grab every inline picture.

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
  download_manager.py  media (yt-dlp) + file (aria2c/python) workers, queue, formats
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
