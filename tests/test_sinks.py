import json

from job_reply_classifier.models import ReplyEvent
from job_reply_classifier.sinks import CsvTaskBoard, JsonlSink, TaskBoardSink, WebhookSink


def event(priority="loud", company="Acme Robotics"):
    return ReplyEvent(
        key="fixtures/04", inbox="you@example.com", thread_id="t", sender="Acme Robotics Recruiting <no-reply@greenhouse.io>",
        subject="Interview invitation", received="2026-10-01T10:47:21+02:00", kind="positive", company=company,
        role="AI Workflow Engineer", summary="Invites you to an interview.", deadline="2026-10-07 14:00",
        priority=priority, reason="positive: ping now", created="2026-10-02T23:50:00+02:00",
    )


def test_jsonl_sink_writes_one_line_per_event(tmp_path):
    sink = JsonlSink(tmp_path / "events.jsonl")
    sink.deliver(event())
    sink.deliver(event("quiet"))
    lines = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text("utf-8").splitlines()]
    assert [line["priority"] for line in lines] == ["loud", "quiet"]
    assert lines[0]["title"] == "JOB REPLY POSITIVE: Acme Robotics - AI Workflow Engineer"


def test_task_board_wakes_only_for_loud_events(tmp_path):
    board = CsvTaskBoard(tmp_path / "board.csv")
    sink = TaskBoardSink(board)
    sink.deliver(event("loud"))
    sink.deliver(event("quiet"))
    rows = board.rows()
    assert [(row["id"], row["wake"]) for row in rows] == [("1", "yes"), ("2", "no")]
    assert "Deadline mentioned: 2026-10-07 14:00" in rows[0]["detail"]


def test_webhook_sends_loud_events_only_by_default():
    sink = WebhookSink("https://hooks.example.com/x", post=lambda url, payload: None)
    assert sink.accepts("loud") and not sink.accepts("quiet")


def test_webhook_json_payload_carries_the_whole_event():
    sent = []
    WebhookSink("https://hooks.example.com/x", post=lambda url, payload: sent.append((url, payload))).deliver(event())
    url, payload = sent[0]
    assert url == "https://hooks.example.com/x"
    assert payload["type"] == "job_reply" and payload["deadline"] == "2026-10-07 14:00"


def test_slack_payload_escapes_text_from_the_mail():
    sent = []
    sink = WebhookSink("https://hooks.example.com/x", fmt="slack", post=lambda url, payload: sent.append(payload))
    sink.deliver(event(company="<!channel> Acme & Co"))
    text = sent[0]["text"]
    assert "<!channel>" not in text
    assert "&lt;!channel&gt; Acme &amp; Co" in text
