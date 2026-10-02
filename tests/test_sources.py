import base64
import io
import json
import urllib.parse
from datetime import timezone

import pytest

from job_reply_classifier.errors import ConfigError
from job_reply_classifier.sources import GmailSource

from .conftest import INBOX, at


def test_fixture_headers_are_decoded(fixture_source):
    stepstone = fixture_source.envelope("03-stepstone-jobagent")
    assert stepstone.subject == "Neue Stelle für Sie: Automation Engineer (m/w/d) und 9 weitere Jobs"  # RFC 2047, base64
    invite = fixture_source.envelope("09-initech-interview-de")
    assert invite.subject == "Ihre Bewerbung: Einladung zum Kennenlerngespräch"  # RFC 2047, quoted-printable
    assert invite.inbox == "you@example.com"
    assert invite.received == at("2026-10-02 09:40:12")


def test_html_only_mail_becomes_plain_text(fixture_source):
    body = fixture_source.body(fixture_source.envelope("01-globex-workday-receipt"))
    assert "We have received your application" in body
    assert "<" not in body and "font-family" not in body and "Application received" not in body


def test_quoted_printable_body_is_decoded(fixture_source):
    body = fixture_source.body(fixture_source.envelope("02-initech-personio-receipt"))
    assert "vielen Dank für Ihre Bewerbung als KI-Automatisierungsentwickler (m/w/d) bei der Initech Digital GmbH." in body


def test_quoted_history_of_a_reply_is_cut(fixture_source):
    body = fixture_source.body(fixture_source.envelope("12-hooli-salary-question"))
    assert body.endswith("Founder, Hooli Labs Inc.")
    assert "I would like to apply" not in body


def test_thread_includes_your_sent_mail(fixture_source):
    items = fixture_source.thread(fixture_source.envelope("12-hooli-salary-question"))
    assert [(i.subject, i.from_user) for i in items] == [
        ("Two quick questions before we talk", False),
        ("Application: n8n Automation Specialist", True),
    ]


# Gmail source against a fake HTTP layer -------------------------------------------------------


class FakeGoogle:
    """Answers the five Gmail/OAuth calls the source makes, and records the URLs."""

    def __init__(self, raw_mail: bytes):
        self.raw = base64.urlsafe_b64encode(raw_mail).decode().rstrip("=")
        self.urls = []

    def __call__(self, request, timeout):
        url = request.full_url
        self.urls.append(url)
        path = urllib.parse.urlsplit(url).path
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        if url.startswith("https://oauth2.googleapis.com/token"):
            body = {"access_token": "test-access", "expires_in": 3600}
        elif path.endswith("/messages"):
            body = {"messages": [{"id": "abc", "threadId": "t1"}]}
        elif path.endswith("/messages/abc") and query.get("format") == "raw":
            body = {"id": "abc", "raw": self.raw}
        elif path.endswith("/messages/abc"):
            body = {
                "id": "abc", "threadId": "t1", "internalDate": "1790926812000",
                "payload": {"headers": [{"name": "From", "value": "Mara <mara@hooli-example.com>"}, {"name": "Subject", "value": "Two quick questions"}]},
            }
        elif path.endswith("/threads/t1"):
            body = {"messages": [
                {"labelIds": ["SENT"], "payload": {"headers": [{"name": "From", "value": "Alex <you@example.org>"}, {"name": "Subject", "value": "Application: n8n"}]}},
                {"labelIds": ["INBOX"], "payload": {"headers": [{"name": "From", "value": "Mara <mara@hooli-example.com>"}, {"name": "Subject", "value": "Two quick questions"}]}},
            ]}
        else:
            raise AssertionError(f"unexpected call {url}")
        return io.BytesIO(json.dumps(body).encode())


def test_gmail_source_lists_fetches_and_parses_with_the_shared_parser():
    google = FakeGoogle((INBOX / "12-hooli-salary-question.eml").read_bytes())
    source = GmailSource("you@example.org", "client-id", "client-secret", "refresh", urlopen=google)
    since = at("2026-10-02 00:00")

    assert source.list_ids(since) == ["abc"]
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(google.urls[1]).query))
    assert f"after:{int(since.timestamp())}" in query["q"] and "-from:me" in query["q"]

    env = source.envelope("abc")
    assert (env.inbox, env.thread_id, env.subject) == ("you@example.org", "t1", "Two quick questions")
    assert env.received == at("2026-10-02 09:40:12") and env.received.tzinfo == timezone.utc
    assert [i.from_user for i in source.thread(env)] == [True, False]
    assert "salary expectations" in source.body(env)
    assert sum(url.startswith("https://oauth2") for url in google.urls) == 1  # token reused, not refreshed per call


def test_gmail_source_needs_all_credentials():
    with pytest.raises(ConfigError):
        GmailSource("you@example.com", "client-id", "", "refresh")
