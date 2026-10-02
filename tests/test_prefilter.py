from datetime import datetime, timezone

import pytest

from job_reply_classifier.models import ThreadItem
from job_reply_classifier.prefilter import PreFilter

from .conftest import envelope

pre = PreFilter()


@pytest.mark.parametrize(
    "sender",
    [
        "Globex Careers <globex@myworkday.com>",
        "Initech Digital GmbH <noreply@personio.de>",
        "Muster GmbH via JOIN <noreply@join.com>",
        "Acme Recruiting <no-reply@us.greenhouse-mail.io>",
        "Vandelay <no-reply@ashbyhq.com>",
        "Example <jobs@sample-example.com>",
    ],
)
def test_ats_senders_are_candidates(sender):
    decision = pre.check(envelope(sender, "Hello"))
    assert decision.candidate
    assert decision.reason.startswith("ATS sender")


@pytest.mark.parametrize(
    "subject",
    [
        "Ihre Bewerbung als Automation Engineer",
        "Your application for Data Engineer",
        "Einladung zum Vorstellungsgespräch",
        "Interview invitation: AI Engineer",
        "Absage",
        "Rückmeldung zu Ihrer Kandidatur",
    ],
)
def test_application_words_in_subject_german_and_english(subject):
    assert pre.check(envelope("Max Mustermann <max@firma-example.de>", subject)).candidate


def test_thread_check_runs_only_when_cheaper_checks_found_nothing():
    calls = []

    def thread():
        calls.append(1)
        return []

    pre.check(envelope("Globex <globex@myworkday.com>", "Hello"), thread)
    pre.check(envelope("Max <max@firma-example.de>", "Ihre Bewerbung"), thread)
    assert calls == []
    pre.check(envelope("Max <max@firma-example.de>", "Kurze Frage"), thread)
    assert calls == [1]


def test_reply_in_a_thread_you_started_with_an_application_is_a_candidate():
    items = [
        ThreadItem("Alex <you@example.com>", "Application: n8n Automation Specialist", from_user=True),
        ThreadItem("Mara <mara@hooli-example.com>", "Two quick questions", from_user=False),
    ]
    decision = pre.check(envelope("Mara <mara@hooli-example.com>", "Two quick questions"), lambda: items)
    assert decision.candidate
    assert decision.reason == "your application thread"


def test_thread_without_your_application_is_skipped():
    items = [
        ThreadItem("Alex <you@example.com>", "Lunch on Friday?", from_user=True),
        ThreadItem("Sam <sam@example.net>", "Re: Lunch on Friday?", from_user=False),
    ]
    assert not pre.check(envelope("Sam <sam@example.net>", "Re: Lunch on Friday?"), lambda: items).candidate


def test_your_own_mail_is_skipped():
    decision = pre.check(envelope("Alex <you@example.com>", "Application: Data Engineer"))
    assert (decision.candidate, decision.reason) == (False, "your own mail")


def test_plain_mail_without_signal_is_skipped():
    decision = pre.check(envelope("Parcel <tracking@parcel-example.com>", "Your package is on its way"), lambda: [])
    assert (decision.candidate, decision.reason) == (False, "no job signal")


def test_fixture_mails_split_into_candidates_and_skips(fixture_source):
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candidates = set()
    for msg_id in fixture_source.list_ids(since):
        env = fixture_source.envelope(msg_id)
        if pre.check(env, lambda env=env: fixture_source.thread(env)).candidate:
            candidates.add(msg_id[:2])
    assert candidates == {"01", "02", "04", "05", "09", "10", "12", "13", "14"}
