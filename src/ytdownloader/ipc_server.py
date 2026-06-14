"""Tiny localhost HTTP server so the Chrome extension can hand off URLs.

Runs a ``ThreadingHTTPServer`` on a daemon thread. Incoming POSTs are delivered
to the GUI thread via a Qt signal (queued connection), so it is safe to touch
widgets from the connected slot.

Endpoints:
    GET  /ping       -> {"ok": true}                 (extension liveness check)
    POST /add        body {"url": "..."}             -> fetch in the app UI
    POST /formats    body {"url": "..."}             -> available quality options
    POST /download   body {"url","selector",         -> queue + start immediately
                            "audio_only","title"}
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PyQt6.QtCore import QObject, pyqtSignal

from . import utils
from .download_manager import extract_formats


class IpcBridge(QObject):
    url_received = pyqtSignal(str)
    download_requested = pyqtSignal(dict)


def _make_handler(bridge: IpcBridge):
    class Handler(BaseHTTPRequestHandler):
        # Silence the default stderr request logging.
        def log_message(self, *_args):  # noqa: D401
            pass

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _json(self, code: int, payload: dict):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):  # noqa: N802
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):  # noqa: N802
            if self.path.rstrip("/") in ("/ping", ""):
                self._json(200, {"ok": True, "app": "yt-downloader"})
            else:
                self._json(404, {"ok": False, "error": "not found"})

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            return json.loads(raw.decode("utf-8")) if raw else {}

        def do_POST(self):  # noqa: N802
            route = self.path.rstrip("/")
            try:
                data = self._read_json()
            except Exception as exc:  # noqa: BLE001
                self._json(400, {"ok": False, "error": str(exc)})
                return

            url = (data.get("url") or "").strip()

            if route == "/add":
                if not url:
                    self._json(400, {"ok": False, "error": "missing url"})
                    return
                bridge.url_received.emit(url)
                self._json(200, {"ok": True})

            elif route == "/formats":
                if not url:
                    self._json(400, {"ok": False, "error": "missing url"})
                    return
                try:
                    result = extract_formats(url)
                except Exception as exc:  # noqa: BLE001
                    self._json(500, {"ok": False, "error": str(exc)})
                    return
                result["ok"] = True
                self._json(200, result)

            elif route == "/download":
                if not url:
                    self._json(400, {"ok": False, "error": "missing url"})
                    return
                bridge.download_requested.emit({
                    "url": url,
                    "selector": data.get("selector") or "bestvideo+bestaudio/best",
                    "audio_only": bool(data.get("audio_only")),
                    "title": data.get("title") or url,
                })
                self._json(200, {"ok": True})

            else:
                self._json(404, {"ok": False, "error": "not found"})

    return Handler


class IpcServer:
    def __init__(self, bridge: IpcBridge,
                 host: str = utils.IPC_HOST, port: int = utils.IPC_PORT):
        self.bridge = bridge
        self.host = host
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        try:
            self._httpd = ThreadingHTTPServer(
                (self.host, self.port), _make_handler(self.bridge)
            )
        except OSError:
            # Port already in use (another instance, perhaps). Non-fatal.
            return False
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
