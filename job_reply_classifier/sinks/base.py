"""A sink receives routed events. Each sink picks which priorities it wants."""
from __future__ import annotations

from typing import Iterable, Protocol

from ..models import ReplyEvent
from ..routing import LOUD, QUIET


class Sink(Protocol):
    name: str

    def accepts(self, priority: str) -> bool: ...

    def deliver(self, event: ReplyEvent) -> None: ...


class BaseSink:
    name = "sink"

    def __init__(self, priorities: Iterable[str] = (LOUD, QUIET)) -> None:
        self.priorities = frozenset(priorities)

    def accepts(self, priority: str) -> bool:
        return priority in self.priorities

    def deliver(self, event: ReplyEvent) -> None:  # pragma: no cover - overridden
        raise NotImplementedError
