"""What the watcher remembers between cycles: seen mail, failed classifications, held replies.

The file is small JSON, written atomically (temp file + rename), and bounded: seen ids expire after
`retention` and the newest `max_seen` are kept. Retention must stay longer than the lookback
window of the source, otherwise an old mail would expire from `seen` while still being listed
and come back as new.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from .models import ReplyEvent

log = logging.getLogger(__name__)


class State:
    def __init__(self, path: Path | None = None, retention: timedelta = timedelta(days=30), max_seen: int = 5000) -> None:
        self.path = path  # None keeps everything in memory (dry runs, tests)
        self.retention = retention
        self.max_seen = max_seen
        self.seen: dict[str, float] = {}  # key -> unix time first handled
        self.failures: dict[str, dict] = {}  # key -> {"count", "last", "error"}
        self.held: list[dict] = []  # ReplyEvent dicts waiting for quiet hours to end
        self.initialised = False
        self.last_run: str | None = None

    @classmethod
    def load(cls, path: Path | None, **kwargs) -> State:
        state = cls(path, **kwargs)
        if path is None or not path.exists():
            return state
        try:
            data = json.loads(path.read_text("utf-8"))
            state.seen = {str(k): float(v) for k, v in data.get("seen", {}).items()}
            state.failures = {str(k): dict(v) for k, v in data.get("failures", {}).items()}
            state.held = [dict(item) for item in data.get("held", [])]
            state.initialised = bool(data.get("initialised"))
            state.last_run = data.get("last_run")
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            backup = path.with_name(path.name + ".corrupt")
            path.replace(backup)
            log.warning("state file was unreadable (%s); moved it to %s and starting fresh", exc, backup.name)
            return cls(path, **kwargs)
        return state

    def is_seen(self, key: str) -> bool:
        return key in self.seen

    def mark_seen(self, key: str, now: datetime) -> None:
        self.seen[key] = now.timestamp()
        self.failures.pop(key, None)

    def record_failure(self, key: str, now: datetime, error: str) -> int:
        entry = self.failures.setdefault(key, {"count": 0})
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["last"] = now.timestamp()
        entry["error"] = error[:200]
        return entry["count"]

    def hold(self, event: ReplyEvent) -> None:
        self.held.append(event.to_dict())

    def release_due(self, now: datetime) -> list[ReplyEvent]:
        due, waiting = [], []
        for item in self.held:
            until = item.get("hold_until")  # missing in a hand-edited file: release rather than crash
            (due if not until or datetime.fromisoformat(until) <= now else waiting).append(item)
        self.held = waiting
        return [ReplyEvent.from_dict(item) for item in due]

    def prune(self, now: datetime) -> None:
        cutoff = (now - self.retention).timestamp()
        self.seen = {k: t for k, t in self.seen.items() if t >= cutoff}
        if len(self.seen) > self.max_seen:
            newest = sorted(self.seen.items(), key=lambda kv: kv[1], reverse=True)[: self.max_seen]
            self.seen = dict(newest)
        self.failures = {k: v for k, v in self.failures.items() if float(v.get("last", 0)) >= cutoff}

    def save(self) -> None:
        if self.path is None:
            return
        data = {
            "version": 1,
            "initialised": self.initialised,
            "last_run": self.last_run,
            "seen": self.seen,
            "failures": self.failures,
            "held": self.held,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False), "utf-8")
        os.replace(tmp, self.path)
