"""Persists the active download queue so it survives app restarts.

Only unfinished tasks (queued / downloading / paused / error) are saved;
completed ones live in the history. On the next launch the app reloads these
and leaves them paused so the user (or auto-resume) can continue them — the
partial ``.part`` / ``.aria2`` files on disk let downloads pick up where they
stopped.
"""

from __future__ import annotations

import json
from pathlib import Path


def queue_path() -> Path:
    d = Path.home() / ".ytdownloader"
    d.mkdir(parents=True, exist_ok=True)
    return d / "queue.json"


class QueueStore:
    def __init__(self, path: Path | None = None):
        self.path = path or queue_path()

    def load(self) -> list[dict]:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

    def save(self, entries: list[dict]) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(entries, fh, indent=2, ensure_ascii=False)
        except OSError:
            pass
