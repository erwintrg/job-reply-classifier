import json
from datetime import timedelta

from job_reply_classifier.models import ReplyEvent
from job_reply_classifier.state import State

from .conftest import at


def event(hold_until: str) -> ReplyEvent:
    return ReplyEvent(
        key="fixtures/14", inbox="you@example.org", thread_id="t", sender="Muster <noreply@join.com>",
        subject="Ihre Bewerbung", received="2026-10-02T23:37:51+02:00", kind="negative", company="Muster Automation GmbH",
        role="", summary="Rejection.", deadline="", priority="held", reason="night", created="2026-10-02T23:50:00+02:00",
        hold_until=hold_until,
    )


def test_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    state = State(path)
    state.mark_seen("gmail:you@example.com/abc", at("2026-10-02 12:00"))
    state.record_failure("gmail:you@example.com/def", at("2026-10-02 12:00"), "timeout")
    state.hold(event("2026-10-03T07:00:00+02:00"))
    state.initialised = True
    state.save()

    loaded = State.load(path)
    assert loaded.is_seen("gmail:you@example.com/abc")
    assert loaded.failures["gmail:you@example.com/def"]["count"] == 1
    assert loaded.held[0]["company"] == "Muster Automation GmbH"
    assert loaded.initialised


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "data" / "state.json"
    State(path).save()
    assert path.exists()
    assert [p.name for p in path.parent.iterdir()] == ["state.json"]


def test_prune_drops_entries_older_than_retention():
    state = State(None, retention=timedelta(days=30))
    state.mark_seen("old", at("2026-08-01 12:00"))
    state.mark_seen("new", at("2026-10-01 12:00"))
    state.prune(at("2026-10-02 12:00"))
    assert list(state.seen) == ["new"]


def test_prune_keeps_only_the_newest_when_over_the_cap():
    state = State(None, max_seen=3)
    for minute in range(10):
        state.mark_seen(f"id{minute}", at(f"2026-10-02 12:{minute:02d}"))
    state.prune(at("2026-10-02 13:00"))
    assert sorted(state.seen) == ["id7", "id8", "id9"]


def test_failures_count_up_and_clear_once_seen():
    state = State(None)
    now = at("2026-10-02 12:00")
    assert state.record_failure("k", now, "boom") == 1
    assert state.record_failure("k", now, "boom") == 2
    state.mark_seen("k", now)
    assert "k" not in state.failures


def test_held_events_are_released_only_when_due():
    state = State(None)
    state.hold(event("2026-10-03T07:00:00+02:00"))
    assert state.release_due(at("2026-10-03 06:58")) == []
    released = state.release_due(at("2026-10-03 07:02"))
    assert [e.company for e in released] == ["Muster Automation GmbH"]
    assert state.held == []


def test_corrupt_state_file_is_moved_aside(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json", "utf-8")
    state = State.load(path)
    assert state.seen == {} and not state.initialised
    assert (tmp_path / "state.json.corrupt").exists()


def test_in_memory_state_never_writes(tmp_path):
    state = State(None)
    state.mark_seen("k", at("2026-10-02 12:00"))
    state.save()
    assert list(tmp_path.iterdir()) == []


def test_file_format_is_plain_json(tmp_path):
    path = tmp_path / "state.json"
    state = State(path)
    state.mark_seen("fixtures/01", at("2026-10-02 12:00"))
    state.save()
    data = json.loads(path.read_text("utf-8"))
    assert set(data) == {"version", "initialised", "last_run", "seen", "failures", "held"}
