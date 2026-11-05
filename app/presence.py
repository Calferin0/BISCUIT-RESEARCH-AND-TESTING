"""Who's on BRT right now, so CF doesn't shut the server down mid-review.

Kept in memory, not in SQLite: presence is transient ("seen in the last minute"), so persisting it
would mean a disk write per heartbeat for data that's meaningless after a restart (and after a
restart nobody *is* connected). Waitress serves requests on several threads, so access is behind a lock.

Fed by two things: every agent page load (before_request) and a JS heartbeat every ~25 s while
a tab is visible, which also reports whether a form has unsaved input ("mid-review").
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

LIVE_WINDOW_S = 70  # ~2.5 missed heartbeats before someone counts as gone


@dataclass
class Seen:
    name: str
    avatar: str
    where: str
    editing: bool
    at: float


class Presence:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[int, Seen] = {}

    def touch(self, member, where: str, editing: bool = False) -> None:
        with self._lock:
            self._seen[member["id"]] = Seen(member["name"], member["avatar"], where, editing, time.monotonic())

    def live(self, window_s: float = LIVE_WINDOW_S) -> list[dict]:
        now = time.monotonic()  # monotonic: immune to the PC clock being changed
        with self._lock:
            # Forget stale entries here too, so the dict can't grow forever.
            self._seen = {k: v for k, v in self._seen.items() if now - v.at <= window_s}
            rows = [{"name": v.name, "avatar": v.avatar, "where": v.where, "editing": v.editing,
                     "seconds_ago": int(now - v.at)} for v in self._seen.values()]
        return sorted(rows, key=lambda r: (not r["editing"], r["name"].lower()))
