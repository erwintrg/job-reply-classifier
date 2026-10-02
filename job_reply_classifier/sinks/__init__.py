"""Sinks: where routed replies go."""
from .base import BaseSink, Sink
from .jsonl import JsonlSink
from .stdout import StdoutSink
from .taskboard import CsvTaskBoard, TaskBoard, TaskBoardSink
from .webhook import WebhookSink

__all__ = ["BaseSink", "CsvTaskBoard", "JsonlSink", "Sink", "StdoutSink", "TaskBoard", "TaskBoardSink", "WebhookSink"]
