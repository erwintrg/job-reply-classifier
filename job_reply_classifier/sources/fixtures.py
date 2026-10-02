"""Offline source: a folder of .eml files, plus an optional folder of your own sent mail.

Each file is one inbound mail. The inbox it belongs to comes from Delivered-To (or To), threads
come from Message-ID / In-Reply-To / References, so several inboxes and the "you started this
thread" check work the same way they do against Gmail.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from pathlib import Path

from ..models import Envelope, ThreadItem
from .mail_parse import body_text, header, parse_message, thread_root


class FixtureSource:
    def __init__(self, inbox_dir: Path, sent_dir: Path | None = None, name: str = "fixtures") -> None:
        self.name = name
        self._mail: dict[str, tuple[Envelope, EmailMessage]] = {}
        self._threads: dict[str, list[tuple[str, str]]] = {}  # thread root -> [(From, Subject)]
        for path in sorted(Path(inbox_dir).glob("*.eml")):
            msg = parse_message(path.read_bytes())
            envelope = Envelope(
                id=path.stem,
                inbox=_inbox_of(msg),
                thread_id=thread_root(msg) or path.stem,
                sender=header(msg, "From"),
                subject=header(msg, "Subject"),
                received=_date_of(msg),
            )
            self._mail[envelope.id] = (envelope, msg)
            self._threads.setdefault(envelope.thread_id, []).append((envelope.sender, envelope.subject))
        if sent_dir is not None:
            for path in sorted(Path(sent_dir).glob("*.eml")):
                msg = parse_message(path.read_bytes())
                self._threads.setdefault(thread_root(msg) or path.stem, []).append((header(msg, "From"), header(msg, "Subject")))

    def __len__(self) -> int:
        return len(self._mail)

    def list_ids(self, since: datetime) -> list[str]:
        envelopes = sorted((env for env, _ in self._mail.values() if env.received >= since), key=lambda env: env.received)
        return [env.id for env in envelopes]

    def envelope(self, msg_id: str) -> Envelope:
        return self._mail[msg_id][0]

    def thread(self, envelope: Envelope) -> list[ThreadItem]:
        me = envelope.inbox.lower()
        return [
            ThreadItem(sender, subject, parseaddr(sender)[1].lower() == me)
            for sender, subject in self._threads.get(envelope.thread_id, [])
        ]

    def body(self, envelope: Envelope) -> str:
        return body_text(self._mail[envelope.id][1])


def _inbox_of(msg: EmailMessage) -> str:
    delivered = header(msg, "Delivered-To")
    if delivered:
        return parseaddr(delivered)[1].lower()
    addresses = getaddresses([header(msg, "To")])
    return addresses[0][1].lower() if addresses else ""


def _date_of(msg: EmailMessage) -> datetime:
    value = header(msg, "Date")
    moment = parsedate_to_datetime(value) if value else datetime.fromtimestamp(0, timezone.utc)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
