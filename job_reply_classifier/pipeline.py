"""One watcher cycle: release held replies, list new mail, pre-filter, classify, route, deliver."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Sequence

from .classifiers.base import Classifier
from .errors import ConfigError
from .models import UNCLASSIFIED, Classification, Envelope, ReplyEvent
from .prefilter import PreFilter
from .routing import DROP, HELD, LOUD, QuietHours, Route, route
from .sinks.base import Sink
from .sources.base import Source
from .state import State

log = logging.getLogger(__name__)

SKIPPED, CLASSIFIED, RETRY, GAVE_UP = "skipped", "classified", "retry", "gave_up"


@dataclass
class Outcome:
    """What happened to one new mail in this cycle."""

    source: str
    envelope: Envelope
    status: str  # skipped | classified | retry | gave_up
    reason: str  # pre-filter decision, or the error that caused a retry
    classification: Classification | None = None
    route: Route | None = None
    delivered: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class Release:
    """A reply that was held overnight and delivered in this cycle."""

    event: ReplyEvent
    delivered: list[str]
    errors: list[str]


@dataclass
class RunReport:
    now: datetime
    outcomes: list[Outcome] = field(default_factory=list)
    released: list[Release] = field(default_factory=list)
    already_seen: int = 0
    source_errors: list[str] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == status)

    def routed(self, priority: str) -> int:
        return sum(1 for o in self.outcomes if o.route is not None and o.route.priority == priority)

    def summary_line(self) -> str:
        return (
            f"{self.now:%Y-%m-%d %H:%M} new {len(self.outcomes)} (seen before {self.already_seen}): "
            f"skipped {self.count(SKIPPED)}, classified {self.count(CLASSIFIED) + self.count(GAVE_UP)}, "
            f"retry {self.count(RETRY)} | loud {self.routed(LOUD)}, quiet {self.routed('quiet')}, held {self.routed(HELD)}, "
            f"dropped {self.routed(DROP)}, released {len(self.released)}"
            + (f" | source errors {len(self.source_errors)}" if self.source_errors else "")
        )


class Watcher:
    def __init__(
        self,
        sources: Sequence[Source],
        classifier: Classifier,
        sinks: Sequence[Sink],
        state: State,
        *,
        prefilter: PreFilter | None = None,
        quiet_hours: QuietHours | None = None,
        tz: tzinfo = timezone.utc,
        max_attempts: int = 3,
        lookback: timedelta = timedelta(hours=72),
        first_run_lookback: timedelta = timedelta(hours=24),
    ) -> None:
        window = max(lookback, first_run_lookback)
        if state.retention <= window:
            raise ValueError(
                f"the lookback window ({window.total_seconds() / 3600:.0f} h) must be shorter than the state retention "
                f"({state.retention.total_seconds() / 3600:.0f} h), otherwise old mail comes back as new"
            )
        self.sources = list(sources)
        self.classifier = classifier
        self.sinks = list(sinks)
        self.state = state
        self.prefilter = prefilter or PreFilter()
        self.quiet_hours = quiet_hours
        self.tz = tz
        self.max_attempts = max_attempts
        self.lookback = lookback
        self.first_run_lookback = first_run_lookback

    def run_once(self, now: datetime | None = None) -> RunReport:
        now = (now or datetime.now(timezone.utc)).astimezone(self.tz)
        report = RunReport(now)
        try:
            for event in self.state.release_due(now):
                event = replace(event, priority=LOUD, reason=f"released from night hold at {now:%H:%M}")
                report.released.append(Release(event, *self._deliver(event)))
            since = now - (self.lookback if self.state.initialised else self.first_run_lookback)
            for source in self.sources:
                try:
                    ids = source.list_ids(since)
                except ConfigError:
                    raise
                except Exception as exc:  # network, quota: try again next cycle
                    log.warning("listing %s failed: %s", source.name, exc)
                    report.source_errors.append(f"{source.name}: {exc}")
                    continue
                for msg_id in ids:
                    key = f"{source.name}/{msg_id}"
                    if self.state.is_seen(key):
                        report.already_seen += 1
                        continue
                    outcome = self._process(source, msg_id, key, now, report)
                    if outcome is not None:
                        report.outcomes.append(outcome)
            self.state.initialised = True
        finally:
            self.state.last_run = now.isoformat(timespec="seconds")
            self.state.prune(now)
            self.state.save()
        return report

    def _process(self, source: Source, msg_id: str, key: str, now: datetime, report: RunReport) -> Outcome | None:
        try:
            envelope = source.envelope(msg_id)
        except ConfigError:
            raise
        except Exception as exc:  # not marked seen, so it is picked up again next cycle
            log.warning("fetching %s failed: %s", key, exc)
            report.source_errors.append(f"{key}: {exc}")
            return None

        status, reason = CLASSIFIED, "pre-filter failed"
        try:
            decision = self.prefilter.check(envelope, lambda: source.thread(envelope))
            reason = decision.reason
            if not decision.candidate:
                self.state.mark_seen(key, now)
                return Outcome(source.name, envelope, SKIPPED, reason)
            classification = self.classifier.classify(envelope, source.body(envelope))
        except ConfigError:
            raise
        except Exception as exc:
            attempts = self.state.record_failure(key, now, f"{type(exc).__name__}: {exc}")
            if attempts < self.max_attempts:
                log.warning("%s failed (attempt %d of %d), retrying next cycle: %s", key, attempts, self.max_attempts, exc)
                return Outcome(source.name, envelope, RETRY, f"attempt {attempts}/{self.max_attempts} failed: {exc}")
            status = GAVE_UP
            classification = Classification(UNCLASSIFIED, summary=f"Could not classify after {attempts} attempts ({exc}).")

        self.state.mark_seen(key, now)
        decided = route(classification.kind, envelope.received, now, self.quiet_hours)
        outcome = Outcome(source.name, envelope, status, reason, classification, decided)
        if decided.priority == DROP:
            return outcome
        event = ReplyEvent(
            key=key,
            inbox=envelope.inbox,
            thread_id=envelope.thread_id,
            sender=envelope.sender,
            subject=envelope.subject,
            received=envelope.received.astimezone(self.tz).isoformat(timespec="seconds"),
            kind=classification.kind,
            company=classification.company,
            role=classification.role,
            summary=classification.summary,
            deadline=classification.deadline,
            priority=decided.priority,
            reason=decided.reason,
            created=now.isoformat(timespec="seconds"),
            hold_until=decided.hold_until.isoformat(timespec="seconds") if decided.hold_until else "",
        )
        if decided.priority == HELD:
            self.state.hold(event)
        else:
            outcome.delivered, outcome.errors = self._deliver(event)
        return outcome

    def _deliver(self, event: ReplyEvent) -> tuple[list[str], list[str]]:
        delivered, errors = [], []
        for sink in self.sinks:
            if not sink.accepts(event.priority):
                continue
            try:
                sink.deliver(event)
                delivered.append(sink.name)
            except Exception as exc:  # one broken sink must not block the others
                log.warning("sink %s failed for %s: %s", sink.name, event.key, exc)
                errors.append(f"{sink.name}: {exc}")
        return delivered, errors
