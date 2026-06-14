"""Persistent download history (IDM-style), stored as JSON on disk.

Entries survive restarts. The store is a thin wrapper over a list of plain
dicts so it serialises trivially and the GUI can render it directly.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def history_path() -> Path:
    d = Path.home() / ".ytdownloader"
    d.mkdir(parents=True, exist_ok=True)
    return d / "history.json"


class HistoryStore:
    def __init__(self, path: Path | None = None):
        self.path = path or history_path()
        self.entries: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

    def save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.entries, fh, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def add(self, *, id: str, title: str, url: str, quality_label: str,
            audio_only: bool, filepath: str, size: str, status: str) -> dict:
        entry = {
            "id": id,
            "title": title,
            "url": url,
            "quality_label": quality_label,
            "audio_only": audio_only,
            "filepath": filepath,
            "size": size,
            "status": status,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        }
        # newest first; drop any older entry with the same id
        self.entries = [e for e in self.entries if e.get("id") != id]
        self.entries.insert(0, entry)
        self.save()
        return entry

    def remove(self, entry_id: str) -> None:
        self.entries = [e for e in self.entries if e.get("id") != entry_id]
        self.save()

    def clear(self) -> None:
        self.entries = []
        self.save()
