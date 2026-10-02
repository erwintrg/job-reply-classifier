from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from ..models import ReplyEvent
from ..routing import LOUD, QUIET
from .base import BaseSink


class JsonlSink(BaseSink):
    """Appends one JSON object per event. An audit log you can grep or load into a notebook."""

    name = "jsonl"

    def __init__(self, path: Path, priorities: Iterable[str] = (LOUD, QUIET)) -> None:
        super().__init__(priorities)
        self.path = Path(path)

    def deliver(self, event: ReplyEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"title": event.title, **event.to_dict()}, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
