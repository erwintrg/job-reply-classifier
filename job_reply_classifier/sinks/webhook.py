from __future__ import annotations

import json
import urllib.request
from typing import Callable, Iterable

from ..models import ReplyEvent
from ..routing import LOUD
from .base import BaseSink

Poster = Callable[[str, dict], None]


class WebhookSink(BaseSink):
    """POSTs events as JSON: a Slack incoming webhook, an n8n or Make webhook, or your own endpoint.

    fmt="json" sends the whole event. fmt="slack" sends {"text": ...} for Slack incoming webhooks;
    text taken from the mail is escaped, so a sender cannot sneak an @channel mention into it.
    By default only loud events are sent, which keeps receipts out of your notifications.
    """

    name = "webhook"

    def __init__(
        self,
        url: str,
        fmt: str = "json",
        priorities: Iterable[str] = (LOUD,),
        timeout: float = 10.0,
        post: Poster | None = None,
    ) -> None:
        super().__init__(priorities)
        if fmt not in ("json", "slack"):
            raise ValueError("webhook format must be 'json' or 'slack'")
        self.url = url
        self.fmt = fmt
        self.timeout = timeout
        self._post = post or self._http_post

    def payload(self, event: ReplyEvent) -> dict:
        if self.fmt == "json":
            return {"type": "job_reply", "title": event.title, **event.to_dict()}
        lines = [f"*{_slack(event.title)}*"]
        if event.summary:
            lines.append(_slack(event.summary))
        if event.deadline:
            lines.append(f"Deadline: {_slack(event.deadline)}")
        lines.append(f"Received {event.received[:16].replace('T', ' ')} in {_slack(event.inbox)}")
        return {"text": "\n".join(lines)}

    def deliver(self, event: ReplyEvent) -> None:
        self._post(self.url, self.payload(event))

    def _http_post(self, url: str, payload: dict) -> None:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            if response.status >= 300:
                raise RuntimeError(f"webhook answered HTTP {response.status}")


def _slack(text: str) -> str:
    """Escape the three characters Slack treats as markup for links and mentions."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
