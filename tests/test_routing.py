from datetime import time

import pytest

from job_reply_classifier.models import UNCLASSIFIED
from job_reply_classifier.routing import DROP, HELD, LOUD, QUIET, QuietHours, route

from .conftest import BERLIN, at

NIGHT = QuietHours(time(23, 0), time(7, 0), BERLIN)


def test_receipt_is_quiet():
    assert route("receipt", at("2026-10-02 12:00"), at("2026-10-02 12:01"), NIGHT).priority == QUIET


@pytest.mark.parametrize("kind", ["positive", "question"])
def test_positive_and_question_are_loud_even_at_night(kind):
    assert route(kind, at("2026-10-02 23:40"), at("2026-10-02 23:41"), NIGHT).priority == LOUD


def test_rejection_by_day_is_loud():
    assert route("negative", at("2026-10-02 16:05"), at("2026-10-02 16:06"), NIGHT).priority == LOUD


def test_rejection_at_night_is_held_until_quiet_hours_end():
    decided = route("negative", at("2026-10-02 23:37"), at("2026-10-02 23:50"), NIGHT)
    assert decided.priority == HELD
    assert decided.hold_until == at("2026-10-03 07:00")


def test_rejection_after_midnight_is_held_until_the_same_morning():
    decided = route("negative", at("2026-10-03 02:15"), at("2026-10-03 02:16"), NIGHT)
    assert decided.hold_until == at("2026-10-03 07:00")


def test_rejection_whose_hold_is_already_over_is_loud():
    # Arrived at 02:00, but the watcher was offline and only sees it at 07:30.
    assert route("negative", at("2026-10-03 02:00"), at("2026-10-03 07:30"), NIGHT).priority == LOUD


def test_without_quiet_hours_nothing_is_held():
    assert route("negative", at("2026-10-02 23:37"), at("2026-10-02 23:38"), None).priority == LOUD


def test_not_job_is_dropped_and_unclassified_is_logged_quietly():
    assert route("not_job", at("2026-10-02 12:00"), at("2026-10-02 12:00")).priority == DROP
    assert route(UNCLASSIFIED, at("2026-10-02 12:00"), at("2026-10-02 12:00")).priority == QUIET


def test_quiet_hours_parse_and_contains():
    night = QuietHours.parse("23:00-07:00", "Europe/Berlin")
    assert night.contains(at("2026-10-02 23:00"))
    assert night.contains(at("2026-10-03 06:59"))
    assert not night.contains(at("2026-10-03 07:00"))
    assert not night.contains(at("2026-10-02 22:59"))
    lunch = QuietHours.parse("12:00-13:00", "Europe/Berlin")
    assert lunch.contains(at("2026-10-02 12:30")) and not lunch.contains(at("2026-10-02 13:30"))
    assert QuietHours.parse("off", "Europe/Berlin") is None
    with pytest.raises(ValueError):
        QuietHours.parse("late", "Europe/Berlin")
