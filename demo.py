#!/usr/bin/env python3
"""Offline demo: the real watcher over 14 fictional mails, with a keyword mock instead of the LLM.

No account, no key, no network, no installs. Run: python demo.py
Files land in demo-output/ (task board CSV, JSONL log, state file). Webhook calls are captured,
not sent.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))  # works from a fresh clone without installing the package

from job_reply_classifier.classifiers import MockClassifier  # noqa: E402
from job_reply_classifier.pipeline import SKIPPED, Watcher  # noqa: E402
from job_reply_classifier.report import table  # noqa: E402
from job_reply_classifier.routing import DROP, HELD, LOUD, QuietHours  # noqa: E402
from job_reply_classifier.sinks import CsvTaskBoard, JsonlSink, TaskBoardSink, WebhookSink  # noqa: E402
from job_reply_classifier.sources import FixtureSource  # noqa: E402
from job_reply_classifier.state import State  # noqa: E402

TIMEZONE = "Europe/Berlin"
TZ = ZoneInfo(TIMEZONE)
NOW = datetime(2026, 10, 2, 23, 50, tzinfo=TZ)  # just after the last fixture arrived
MORNING = datetime(2026, 10, 3, 7, 2, tzinfo=TZ)  # first two-minute cycle after quiet hours
OUT = ROOT / "demo-output"


def sinks_label(names: list[str], priority: str) -> str:
    return ", ".join(f"{name} (wake)" if name == "taskboard" and priority == LOUD else name for name in names)


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()

    source = FixtureSource(ROOT / "fixtures" / "inbox", ROOT / "fixtures" / "sent")
    board = CsvTaskBoard(OUT / "task-board.csv")
    webhook_calls: list[dict] = []
    sinks = [
        TaskBoardSink(board),
        WebhookSink("https://hooks.example.com/job-replies", fmt="slack", post=lambda url, payload: webhook_calls.append(payload)),
        JsonlSink(OUT / "events.jsonl"),
    ]
    state = State(OUT / "state.json")
    watcher = Watcher(
        [source],
        MockClassifier(),
        sinks,
        state,
        quiet_hours=QuietHours.parse("23:00-07:00", TIMEZONE),
        tz=TZ,
        lookback=timedelta(days=7),
        first_run_lookback=timedelta(days=7),
    )

    report = watcher.run_once(NOW)
    outcomes = sorted(report.outcomes, key=lambda o: o.envelope.received)
    candidates = [o for o in outcomes if o.status != SKIPPED]
    inboxes = sorted({o.envelope.inbox for o in outcomes})

    print("Job reply classifier: offline demo")
    print(f"  {len(outcomes)} fictional mails in {len(inboxes)} inboxes ({', '.join(inboxes)}), plus 1 sent mail for thread checks")
    print("  classifier: mock (keyword rules standing in for Claude Haiku, no API calls)")
    print(f"  clock: {NOW:%a %Y-%m-%d %H:%M} {TIMEZONE}, quiet hours 23:00-07:00")

    print(f"\n1. Pre-filter (regex only, no LLM): {len(candidates)} of {len(outcomes)} mails go to the classifier")
    print(
        table(
            ["#", "From", "Subject", "Pre-filter"],
            [
                [o.envelope.id[:2], o.envelope.sender_name, o.envelope.subject, ("skip: " if o.status == SKIPPED else "candidate: ") + o.reason]
                for o in outcomes
            ],
            [2, 24, 38, 34],
        )
    )

    print(f"\n2. Classifier (mock), {len(candidates)} calls, and routing")
    rows = []
    for o in candidates:
        c, r = o.classification, o.route
        if r.priority == HELD:
            routed = f"held until {r.hold_until:%a %H:%M}"
        else:
            routed = {LOUD: "LOUD", DROP: "drop"}.get(r.priority, r.priority)
        rows.append([o.envelope.id[:2], c.kind, c.company or "-", c.role or "-", c.deadline or "-", routed])
    print(table(["#", "Kind", "Company", "Role", "Deadline", "Route"], rows, [2, 8, 22, 30, 16, 20]))

    print("\n3. Delivered tonight")
    order = {LOUD: 0, "quiet": 1, HELD: 2, DROP: 3}
    for o in sorted(candidates, key=lambda o: (order[o.route.priority], o.envelope.id)):
        priority = o.route.priority
        if priority == HELD:
            where = "nothing yet, waits for the morning"
        elif priority == DROP:
            where = "not routed"
        else:
            where = sinks_label(o.delivered, priority)
        print(f"  {o.envelope.id[:2]}  {'LOUD' if priority == LOUD else priority:<5}  {where}")
        print(f"      {o.classification.summary}")

    morning = watcher.run_once(MORNING)
    print(f"\n4. Next cycle, {MORNING:%a %Y-%m-%d %H:%M}, the first one after quiet hours")
    print(f"  new mail: {len(morning.outcomes)} ({morning.already_seen} seen before)")
    for release in morning.released:
        event = release.event
        print(f"  {event.key.split('/')[-1][:2]}  LOUD   {sinks_label(release.delivered, LOUD)}")
        print(f"      released: {event.title}")

    cards = board.rows()
    events = (OUT / "events.jsonl").read_text("utf-8").splitlines()
    saved = json.loads((OUT / "state.json").read_text("utf-8"))
    print("\nFiles in demo-output/")
    print(f"  task-board.csv  {len(cards)} cards, {sum(card['wake'] == 'yes' for card in cards)} with wake=yes")
    print(f"  events.jsonl    {len(events)} events")
    print(f"  state.json      {len(saved['seen'])} seen ids, {len(saved['held'])} held")
    print(f"\nWebhook, Slack format: {len(webhook_calls)} payloads captured, nothing sent. The first one reads:")
    for line in webhook_calls[0]["text"].splitlines():
        print(f"  | {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
