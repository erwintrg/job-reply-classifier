from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from job_reply_classifier.models import Envelope

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "fixtures" / "inbox"
SENT = ROOT / "fixtures" / "sent"
BERLIN = ZoneInfo("Europe/Berlin")


def at(text: str) -> datetime:
    """'2026-10-02 23:37' in Berlin time."""
    return datetime.fromisoformat(text).replace(tzinfo=BERLIN)


def envelope(sender: str, subject: str, *, inbox: str = "you@example.com", received: str = "2026-10-02 12:00", id: str = "m1") -> Envelope:
    return Envelope(id=id, inbox=inbox, thread_id=f"t-{id}", sender=sender, subject=subject, received=at(received))


@pytest.fixture
def fixture_source():
    from job_reply_classifier.sources import FixtureSource

    return FixtureSource(INBOX, SENT)
