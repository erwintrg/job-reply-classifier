from datetime import timedelta

import pytest

from job_reply_classifier.classifiers import ClassificationError, ConfigError, MockClassifier
from job_reply_classifier.models import Envelope
from job_reply_classifier.pipeline import CLASSIFIED, GAVE_UP, RETRY, SKIPPED, Watcher
from job_reply_classifier.routing import QuietHours
from job_reply_classifier.sinks.base import BaseSink
from job_reply_classifier.state import State

from .conftest import BERLIN, at


class Recorder(BaseSink):
    def __init__(self, name="recorder", priorities=("loud", "quiet"), fail=False):
        super().__init__(priorities)
        self.name = name
        self.events = []
        self.fail = fail

    def deliver(self, event):
        if self.fail:
            raise RuntimeError("endpoint down")
        self.events.append(event)


def watcher(source, classifier, sinks, state=None, **kwargs):
    return Watcher(
        [source], classifier, sinks, state or State(None),
        quiet_hours=QuietHours.parse("23:00-07:00", "Europe/Berlin"), tz=BERLIN,
        lookback=timedelta(days=7), first_run_lookback=timedelta(days=7), **kwargs,
    )


def test_full_cycle_over_the_fixtures(fixture_source):
    sink = Recorder()
    w = watcher(fixture_source, MockClassifier(), [sink])

    night = w.run_once(at("2026-10-02 23:50"))
    assert len(night.outcomes) == 14
    assert night.count(SKIPPED) == 5 and night.count(CLASSIFIED) == 9
    assert (night.routed("loud"), night.routed("quiet"), night.routed("held"), night.routed("drop")) == (4, 2, 1, 2)
    assert sorted(e.kind for e in sink.events) == ["negative", "positive", "positive", "question", "receipt", "receipt"]

    again = w.run_once(at("2026-10-02 23:52"))
    assert again.outcomes == [] and again.already_seen == 14 and again.released == []

    morning = w.run_once(at("2026-10-03 07:02"))
    assert [r.event.company for r in morning.released] == ["Muster Automation GmbH"]
    assert sink.events[-1].priority == "loud"


class FlakySource:
    """One candidate mail, delivered every cycle until it is marked seen."""

    name = "flaky"

    def __init__(self):
        self.env = Envelope("m1", "you@example.com", "t1", "Acme <no-reply@greenhouse.io>", "Interview invitation", at("2026-10-02 12:00"))

    def list_ids(self, since):
        return ["m1"]

    def envelope(self, msg_id):
        return self.env

    def thread(self, env):
        return []

    def body(self, env):
        return "We would like to invite you to an interview."


class FailingClassifier:
    name = "failing"

    def __init__(self, error):
        self.error = error
        self.calls = 0

    def classify(self, envelope, body):
        self.calls += 1
        raise self.error


def test_failed_classification_is_retried_then_logged_as_unclassified():
    sink = Recorder()
    state = State(None)
    w = watcher(FlakySource(), FailingClassifier(ClassificationError("model timeout")), [sink], state, max_attempts=3)

    for minute, expected in ((0, RETRY), (2, RETRY)):
        report = w.run_once(at(f"2026-10-02 12:{minute + 1:02d}"))
        assert report.outcomes[0].status == expected
        assert not state.is_seen("flaky/m1")

    last = w.run_once(at("2026-10-02 12:05"))
    assert last.outcomes[0].status == GAVE_UP
    assert state.is_seen("flaky/m1")
    assert [(e.kind, e.priority) for e in sink.events] == [("unclassified", "quiet")]


def test_config_error_stops_the_cycle_without_using_up_retries():
    state = State(None)
    classifier = FailingClassifier(ConfigError("bad key"))
    w = watcher(FlakySource(), classifier, [Recorder()], state)
    with pytest.raises(ConfigError):
        w.run_once(at("2026-10-02 12:01"))
    assert state.failures == {} and not state.is_seen("flaky/m1")


def test_a_broken_sink_does_not_block_the_others():
    good, broken = Recorder("good"), Recorder("broken", fail=True)
    report = watcher(FlakySource(), MockClassifier(), [broken, good]).run_once(at("2026-10-02 12:01"))
    outcome = report.outcomes[0]
    assert outcome.delivered == ["good"]
    assert outcome.errors == ["broken: endpoint down"]


def test_first_run_looks_back_less_far_than_later_runs():
    seen_since = []

    class Spy(FlakySource):
        def list_ids(self, since):
            seen_since.append(since)
            return []

    w = Watcher([Spy()], MockClassifier(), [], State(None), tz=BERLIN, lookback=timedelta(hours=72), first_run_lookback=timedelta(hours=24))
    now = at("2026-10-02 12:00")
    w.run_once(now)
    w.run_once(now)
    assert [now - since for since in seen_since] == [timedelta(hours=24), timedelta(hours=72)]


def test_retention_shorter_than_lookback_is_rejected():
    with pytest.raises(ValueError):
        Watcher([], MockClassifier(), [], State(None, retention=timedelta(days=2)), lookback=timedelta(days=3))
