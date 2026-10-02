"""A source lists mail and fetches it in steps, cheapest first.

    list_ids   one call per cycle            which ids are in the window
    envelope   one call per NEW id           From, Subject, received time (enough to pre-filter)
    thread     only if headers found nothing who wrote in the thread, and with what subject
    body       only for candidates           full text for the classifier
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..models import Envelope, ThreadItem


class Source(Protocol):
    name: str  # unique per source; seen-state keys are "<name>/<message id>"

    def list_ids(self, since: datetime) -> list[str]: ...

    def envelope(self, msg_id: str) -> Envelope: ...

    def thread(self, envelope: Envelope) -> list[ThreadItem]: ...

    def body(self, envelope: Envelope) -> str: ...
