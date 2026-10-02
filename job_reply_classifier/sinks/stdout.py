from __future__ import annotations

import sys
from typing import Iterable, TextIO

from ..models import ReplyEvent
from ..routing import LOUD, QUIET
from .base import BaseSink


class StdoutSink(BaseSink):
    """One line per event. Handy under cron or systemd, where stdout ends up in the log."""

    name = "stdout"

    def __init__(self, stream: TextIO | None = None, priorities: Iterable[str] = (LOUD, QUIET)) -> None:
        super().__init__(priorities)
        self.stream = stream

    def deliver(self, event: ReplyEvent) -> None:
        mark = "LOUD " if event.priority == LOUD else "quiet"
        print(f"[{mark}] {event.title} | {event.summary}", file=self.stream or sys.stdout)
