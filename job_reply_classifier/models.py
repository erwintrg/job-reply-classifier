"""Plain data types shared by every stage of the pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime
from email.utils import parseaddr

KINDS = ("receipt", "positive", "negative", "question", "not_job")
# Used only when the classifier failed too often, so the mail is logged instead of lost.
UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class Envelope:
    """Headers of one inbound mail. Cheap to fetch and enough for the pre-filter."""

    id: str  # message id inside its source (Gmail id or fixture file name)
    inbox: str  # address the mail arrived in
    thread_id: str
    sender: str  # raw From header, e.g. 'Acme Robotics <jobs@acme-example.com>'
    subject: str
    received: datetime  # timezone-aware

    @property
    def sender_address(self) -> str:
        return parseaddr(self.sender)[1].lower()

    @property
    def sender_name(self) -> str:
        name, address = parseaddr(self.sender)
        return name or address


@dataclass(frozen=True)
class ThreadItem:
    """One message of a thread, reduced to what the thread check needs."""

    sender: str
    subject: str
    from_user: bool


@dataclass(frozen=True)
class Classification:
    kind: str
    company: str = ""
    role: str = ""
    summary: str = ""
    deadline: str = ""  # "YYYY-MM-DD", "YYYY-MM-DD HH:MM" or ""


@dataclass(frozen=True)
class ReplyEvent:
    """What the sinks receive: one classified reply plus its routing decision."""

    key: str  # "<source>/<message id>", unique across inboxes
    inbox: str
    thread_id: str
    sender: str
    subject: str
    received: str  # ISO 8601 in the configured time zone
    kind: str
    company: str
    role: str
    summary: str
    deadline: str
    priority: str  # "loud" or "quiet" once delivered, "held" while waiting for the morning
    reason: str  # why the router chose this priority
    created: str  # ISO 8601, when the watcher produced the event
    hold_until: str = ""

    @property
    def title(self) -> str:
        name, address = parseaddr(self.sender)
        who = self.company or name or address or "unknown sender"
        text = f"JOB REPLY {self.kind.upper()}: {who}"
        if self.role:
            text += f" - {self.role}"
        return text[:150]

    @property
    def detail(self) -> str:
        lines = [self.summary] if self.summary else []
        lines.append(f'Received {_short(self.received)} in {self.inbox}, from {self.sender}, subject "{self.subject}".')
        if self.deadline:
            lines.append(f"Deadline mentioned: {self.deadline}")
        if self.hold_until:
            lines.append(f"Arrived during quiet hours, held until {_short(self.hold_until)}.")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ReplyEvent:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


def _short(iso: str) -> str:
    """'2026-10-02T23:37:51+02:00' -> '2026-10-02 23:37'."""
    return iso[:16].replace("T", " ")
