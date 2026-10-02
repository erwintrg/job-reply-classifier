"""Command line entry point: python -m job_reply_classifier [--loop] [--dry-run] ..."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Iterator

from .config import Settings, build_watcher, load_env_file
from .errors import ConfigError
from .report import describe_run


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m job_reply_classifier",
        description="Watch inboxes for replies to job applications, classify them and route the result.",
    )
    parser.add_argument("--loop", action="store_true", help="keep running, one cycle every POLL_SECONDS (default 120)")
    parser.add_argument("--dry-run", action="store_true", help="print what would be routed; no sinks, no state written")
    parser.add_argument("--source", choices=["gmail", "fixtures"], help="override SOURCE")
    parser.add_argument("--classifier", choices=["anthropic", "claude-cli", "mock"], help="override CLASSIFIER")
    parser.add_argument("--sinks", help="override SINKS, e.g. stdout,jsonl,taskboard,webhook")
    parser.add_argument("--env-file", default=".env", help="settings file to read first (default .env)")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser.parse_args(argv)


@contextmanager
def run_lock(state_path: Path, enabled: bool = True) -> Iterator[bool]:
    """One run at a time per state file, so a slow cycle and the next cron tick cannot overlap."""
    try:
        import fcntl
    except ImportError:  # Windows: no flock, rely on the scheduler instead
        enabled = False
    if not enabled:
        yield True
        return
    lock_path = state_path.with_name(state_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_env_file(Path(args.env_file))
    try:
        settings = Settings.from_env()
        overrides = {"source": args.source, "classifier": args.classifier}
        settings = replace(settings, **{k: v for k, v in overrides.items() if v})
        if args.sinks:
            settings.sinks = [part.strip().lower() for part in args.sinks.split(",") if part.strip()]
        watcher = build_watcher(settings, dry_run=args.dry_run)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    with run_lock(settings.state_path, enabled=not args.dry_run) as acquired:  # a dry run writes nothing
        if not acquired:
            print("another run holds the lock, exiting")
            return 0
        try:
            while True:
                try:
                    report = watcher.run_once()
                except ConfigError as exc:
                    print(f"config error: {exc}", file=sys.stderr)
                    return 2
                print(report.summary_line(), flush=True)
                if args.dry_run:
                    print(describe_run(report))
                if not args.loop:
                    return 0
                time.sleep(settings.poll_seconds)
        except KeyboardInterrupt:
            return 0
