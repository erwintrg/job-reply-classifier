"""Task board interface plus a CSV implementation.

In production the board is a shared sheet that an assistant agent works from: a row with
wake=True makes it act right away, a row without it waits for the next scheduled pass. Any board
with "add a card" fits behind `TaskBoard` (Trello, Notion, Linear, Jira, a Google Sheet).
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable, Protocol

from ..models import ReplyEvent
from ..routing import LOUD, QUIET
from .base import BaseSink


class TaskBoard(Protocol):
    def add_card(self, title: str, detail: str, wake: bool) -> str:
        """Create a card and return its id."""
        ...


class CsvTaskBoard:
    """A task board kept in a CSV file. Good enough for the demo and for a single user."""

    COLUMNS = ("id", "created", "title", "detail", "wake")

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def add_card(self, title: str, detail: str, wake: bool) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not self.path.exists() or self.path.stat().st_size == 0
        card_id = str(len(self.rows()) + 1)
        with self.path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if new_file:
                writer.writerow(self.COLUMNS)
            writer.writerow([card_id, datetime.now().isoformat(timespec="seconds"), title, detail, "yes" if wake else "no"])
        return card_id

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))


class TaskBoardSink(BaseSink):
    """Loud events become cards that wake the board's owner, quiet events become plain cards."""

    name = "taskboard"

    def __init__(self, board: TaskBoard, priorities: Iterable[str] = (LOUD, QUIET)) -> None:
        super().__init__(priorities)
        self.board = board

    def deliver(self, event: ReplyEvent) -> None:
        self.board.add_card(event.title, event.detail, wake=event.priority == LOUD)
