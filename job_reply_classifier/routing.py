"""Routing rules: which replies ping you now, which are only logged, and which wait for the morning.

    positive, question   loud    ping now (questions often carry a deadline)
    negative             loud    ping now, unless it arrived during quiet hours: then held
                                 and released by the first cycle after quiet hours end
    receipt              quiet   logged (task board row without a wake-up), no ping
    unclassified         quiet   classifier kept failing; logged so nothing disappears silently
    not_job              drop    not routed anywhere
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .models import UNCLASSIFIED

LOUD, QUIET, HELD, DROP = "loud", "quiet", "held", "drop"


@dataclass(frozen=True)
class QuietHours:
    start: time
    end: time
    tz: ZoneInfo

    @classmethod
    def parse(cls, spec: str, tz: str) -> QuietHours | None:
        """'23:00-07:00' -> QuietHours; '', 'off' or 'none' -> None (no night hold)."""
        spec = (spec or "").strip().lower()
        if spec in ("", "off", "none"):
            return None
        try:
            start, end = (time.fromisoformat(part.strip()) for part in spec.split("-"))
        except ValueError as exc:
            raise ValueError(f"QUIET_HOURS must look like 23:00-07:00, got {spec!r}") from exc
        return cls(start, end, ZoneInfo(tz))

    def contains(self, moment: datetime) -> bool:
        local = moment.astimezone(self.tz).time()
        if self.start <= self.end:
            return self.start <= local < self.end
        return local >= self.start or local < self.end  # window crosses midnight

    def end_after(self, moment: datetime) -> datetime:
        """The first end of quiet hours after `moment`."""
        local = moment.astimezone(self.tz)
        end = datetime.combine(local.date(), self.end, tzinfo=self.tz)
        return end if end > local else end + timedelta(days=1)


@dataclass(frozen=True)
class Route:
    priority: str
    reason: str
    hold_until: datetime | None = None


def route(kind: str, received: datetime, now: datetime, quiet_hours: QuietHours | None = None) -> Route:
    if kind == "not_job":
        return Route(DROP, "not about a job application")
    if kind == "receipt":
        return Route(QUIET, "receipt: logged, no ping")
    if kind == UNCLASSIFIED:
        return Route(QUIET, "classifier kept failing: logged for a manual look")
    if kind == "negative" and quiet_hours is not None and quiet_hours.contains(received):
        until = quiet_hours.end_after(received)
        if now < until:
            return Route(HELD, f"rejection arrived at night: held until {until:%a %H:%M}", until)
    reasons = {
        "positive": "positive: ping now",
        "question": "question: ping now, they are waiting for an answer",
        "negative": "rejection: ping now",
    }
    return Route(LOUD, reasons.get(kind, "ping now"))
