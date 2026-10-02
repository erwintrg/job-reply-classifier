"""Settings from environment variables (and an optional .env file), and the factory that wires them up."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

from .classifiers import AnthropicClassifier, ClaudeCliClassifier, MockClassifier
from .errors import ConfigError
from .pipeline import Watcher
from .routing import QuietHours
from .sinks import CsvTaskBoard, JsonlSink, StdoutSink, TaskBoardSink, WebhookSink
from .sources import FixtureSource, GmailSource
from .state import State


def load_env_file(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines, # comments, optional quotes. Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


@dataclass
class Settings:
    source: str = "gmail"
    classifier: str = "anthropic"
    sinks: list[str] = field(default_factory=lambda: ["stdout", "jsonl"])
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_inboxes: list[tuple[str, str]] = field(default_factory=list)  # (address, refresh token)
    fixtures_dir: Path = Path("fixtures/inbox")
    fixtures_sent_dir: Path = Path("fixtures/sent")
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5"
    claude_cli: str = "claude"
    claude_cli_model: str = "haiku"
    claude_cli_json_schema: bool = True
    jsonl_path: Path = Path("data/events.jsonl")
    taskboard_csv: Path = Path("data/task-board.csv")
    webhook_url: str = ""
    webhook_format: str = "json"
    webhook_priorities: list[str] = field(default_factory=lambda: ["loud"])
    state_path: Path = Path("data/state.json")
    timezone: str = "UTC"
    quiet_hours: str = ""
    poll_seconds: int = 120
    max_attempts: int = 3
    lookback_hours: int = 72
    first_run_lookback_hours: int = 24

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        def get(name: str, default: str = "") -> str:
            return env.get(name, default).strip()

        def items(name: str, default: str) -> list[str]:
            return [part.strip().lower() for part in get(name, default).split(",") if part.strip()]

        inboxes = []
        for n in range(1, 10):
            address = get(f"GMAIL_INBOX_{n}")
            if address:
                inboxes.append((address, get(f"GMAIL_REFRESH_TOKEN_{n}")))
        try:
            return cls(
                source=get("SOURCE", "gmail").lower(),
                classifier=get("CLASSIFIER", "anthropic").lower(),
                sinks=items("SINKS", "stdout,jsonl"),
                gmail_client_id=get("GMAIL_CLIENT_ID"),
                gmail_client_secret=get("GMAIL_CLIENT_SECRET"),
                gmail_inboxes=inboxes,
                fixtures_dir=Path(get("FIXTURES_DIR", "fixtures/inbox")),
                fixtures_sent_dir=Path(get("FIXTURES_SENT_DIR", "fixtures/sent")),
                anthropic_api_key=get("ANTHROPIC_API_KEY"),
                anthropic_model=get("ANTHROPIC_MODEL", "claude-haiku-4-5"),
                claude_cli=get("CLAUDE_CLI", "claude"),
                claude_cli_model=get("CLAUDE_CLI_MODEL", "haiku"),
                claude_cli_json_schema=get("CLAUDE_CLI_JSON_SCHEMA", "1") not in ("0", "false", "no"),
                jsonl_path=Path(get("JSONL_PATH", "data/events.jsonl")),
                taskboard_csv=Path(get("TASKBOARD_CSV", "data/task-board.csv")),
                webhook_url=get("WEBHOOK_URL"),
                webhook_format=get("WEBHOOK_FORMAT", "json").lower(),
                webhook_priorities=items("WEBHOOK_PRIORITIES", "loud"),
                state_path=Path(get("STATE_PATH", "data/state.json")),
                timezone=get("TIMEZONE", "UTC"),
                quiet_hours=get("QUIET_HOURS"),
                poll_seconds=int(get("POLL_SECONDS", "120")),
                max_attempts=int(get("MAX_ATTEMPTS", "3")),
                lookback_hours=int(get("LOOKBACK_HOURS", "72")),
                first_run_lookback_hours=int(get("FIRST_RUN_LOOKBACK_HOURS", "24")),
            )
        except ValueError as exc:
            raise ConfigError(f"a numeric setting is not a number: {exc}") from exc


def build_sources(s: Settings) -> list:
    if s.source == "fixtures":
        return [FixtureSource(s.fixtures_dir, s.fixtures_sent_dir)]
    if s.source == "gmail":
        if not s.gmail_inboxes:
            raise ConfigError("set GMAIL_INBOX_1 and GMAIL_REFRESH_TOKEN_1 (and _2, _3 ... for more inboxes)")
        return [GmailSource(address, s.gmail_client_id, s.gmail_client_secret, token) for address, token in s.gmail_inboxes]
    raise ConfigError(f"unknown SOURCE {s.source!r}; use gmail or fixtures")


def build_classifier(s: Settings):
    if s.classifier == "anthropic":
        return AnthropicClassifier(model=s.anthropic_model, api_key=s.anthropic_api_key or None)
    if s.classifier in ("claude-cli", "cli"):
        return ClaudeCliClassifier(executable=s.claude_cli, model=s.claude_cli_model, use_json_schema=s.claude_cli_json_schema)
    if s.classifier == "mock":
        return MockClassifier()
    raise ConfigError(f"unknown CLASSIFIER {s.classifier!r}; use anthropic, claude-cli or mock")


def build_sinks(s: Settings) -> list:
    sinks = []
    for name in s.sinks:
        if name == "stdout":
            sinks.append(StdoutSink())
        elif name == "jsonl":
            sinks.append(JsonlSink(s.jsonl_path))
        elif name == "taskboard":
            sinks.append(TaskBoardSink(CsvTaskBoard(s.taskboard_csv)))
        elif name == "webhook":
            if not s.webhook_url:
                raise ConfigError("the webhook sink needs WEBHOOK_URL")
            sinks.append(WebhookSink(s.webhook_url, fmt=s.webhook_format, priorities=s.webhook_priorities))
        else:
            raise ConfigError(f"unknown sink {name!r}; use stdout, jsonl, webhook or taskboard")
    return sinks


def build_watcher(s: Settings, *, dry_run: bool = False) -> Watcher:
    """Dry run: same sources and classifier, results only printed, state not written."""
    try:
        tz = ZoneInfo(s.timezone)
        quiet = QuietHours.parse(s.quiet_hours, s.timezone)
    except (ValueError, KeyError) as exc:
        raise ConfigError(str(exc)) from exc
    state = State.load(s.state_path)
    if dry_run:
        state.path = None
    try:
        return Watcher(
            build_sources(s),
            build_classifier(s),
            [StdoutSink()] if dry_run else build_sinks(s),
            state,
            quiet_hours=quiet,
            tz=tz,
            max_attempts=s.max_attempts,
            lookback=timedelta(hours=s.lookback_hours),
            first_run_lookback=timedelta(hours=s.first_run_lookback_hours),
        )
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
