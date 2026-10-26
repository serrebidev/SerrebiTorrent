# Copyright (c) serrebidev and contributors
# SPDX-License-Identifier: MIT

"""Small persistent user-facing activity history."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import threading
import tempfile
import time

from app_paths import get_state_dir


_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(path) -> threading.Lock:
    """One lock per destination file, shared by every instance in-process."""
    key = str(path)
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.Lock())


DEFAULT_MAX_ENTRIES = 500
MAX_MESSAGE_CHARS = 2000


def filter_activity_entries(entries, query: str = "") -> list[dict[str, str]]:
    """Filter events without changing their chronological order."""
    needle = str(query or "").strip().casefold()
    if not needle:
        return list(entries)
    return [
        entry for entry in entries
        if needle in str(entry.get("message") or "").casefold()
        or needle in str(entry.get("timestamp") or "").casefold()
        or needle in str(entry.get("kind") or "").casefold()
    ]


def format_activity_entry(entry) -> str:
    """Format one entry for copying or text export."""
    timestamp = str(entry.get("timestamp") or "").replace("T", " ", 1)
    kind = str(entry.get("kind") or "info")
    message = str(entry.get("message") or "").replace("\r", " ").replace("\n", " ")
    return f"{timestamp} [{kind}] {message}"


def render_activity_export(entries) -> str:
    """Create a human-readable text export, newest entries first."""
    lines = [format_activity_entry(entry) for entry in entries]
    return "\n".join(lines) + ("\n" if lines else "")




class ActivityHistory:
    def __init__(self, path: str | None = None, max_entries: int = DEFAULT_MAX_ENTRIES):
        self.path = Path(path or os.path.join(get_state_dir(), "activity_history.json"))
        self.max_entries = max(1, int(max_entries))
        self._lock = threading.RLock()

    def _load_unlocked(self) -> list[dict[str, str]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        if not isinstance(raw, list):
            return []
        entries = []
        for item in raw[-self.max_entries :]:
            if not isinstance(item, dict):
                continue
            timestamp = str(item.get("timestamp") or "").strip()
            message = str(item.get("message") or "").strip()
            kind = str(item.get("kind") or "info").strip().lower()
            if not timestamp or not message:
                continue
            if kind not in {"info", "success", "error"}:
                kind = "info"
            entries.append(
                {
                    "timestamp": timestamp,
                    "kind": kind,
                    "message": message[:MAX_MESSAGE_CHARS],
                }
            )
        return entries

    def entries(self) -> list[dict[str, str]]:
        with self._lock:
            return list(self._load_unlocked())

    def append(
        self,
        message: str,
        *,
        kind: str = "info",
        timestamp: str | None = None,
    ) -> None:
        clean_message = str(message or "").strip()
        if not clean_message:
            return
        clean_kind = str(kind or "info").strip().lower()
        if clean_kind not in {"info", "success", "error"}:
            clean_kind = "info"
        stamp = timestamp or datetime.now().astimezone().isoformat(timespec="seconds")
        entry = {
            "timestamp": stamp,
            "kind": clean_kind,
            "message": clean_message[:MAX_MESSAGE_CHARS],
        }

        with self._lock:
            entries = self._load_unlocked()
            entries.append(entry)
            self._write_unlocked(entries[-self.max_entries :])

    def clear(self) -> None:
        with self._lock:
            self._write_unlocked([])

    def _write_unlocked(self, entries: list[dict[str, str]]) -> None:
        # Instances have separate locks; serialize writes to the same file
        # across instances or Windows rejects a concurrent os.replace
        # with PermissionError (WinError 5).
        with _path_lock(self.path):
            self._write_serialized(entries)

    def _write_serialized(self, entries: list[dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f"{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        temp = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(json.dumps(entries, ensure_ascii=False, indent=2))
            for attempt in range(10):
                try:
                    os.replace(temp, self.path)
                    break
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.05)
            if os.name != "nt":
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass
        finally:
            try:
                if temp.exists():
                    temp.unlink()
            except OSError:
                pass
