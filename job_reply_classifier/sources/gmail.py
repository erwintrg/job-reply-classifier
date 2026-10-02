"""Gmail source: one instance per inbox, read-only scope, plain HTTPS calls (no Google SDK needed).

Auth is the OAuth refresh-token flow: one OAuth client plus one refresh token per inbox, issued
for the scope https://www.googleapis.com/auth/gmail.readonly. Access tokens are
refreshed when they expire and never logged.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Callable

from ..errors import ConfigError
from ..models import Envelope, ThreadItem
from .mail_parse import body_text, parse_message

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me/"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
# Inbound mail only, not from you, without the promotions, social and forums tabs.
BASE_QUERY = "in:inbox -from:me -category:promotions -category:social -category:forums"

UrlOpen = Callable[..., object]


class GmailError(Exception):
    """A transient Gmail problem (network, 5xx, quota). The cycle carries on and retries later."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class GmailSource:
    def __init__(
        self,
        inbox: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        *,
        page_size: int = 50,
        max_pages: int = 4,
        timeout: float = 30.0,
        urlopen: UrlOpen = urllib.request.urlopen,
    ) -> None:
        if not (inbox and client_id and client_secret and refresh_token):
            raise ConfigError(f"Gmail inbox {inbox or '?'} needs a client id, a client secret and a refresh token")
        self.inbox = inbox.lower()
        self.name = f"gmail:{self.inbox}"
        self._client = (client_id, client_secret, refresh_token)
        self.page_size = page_size
        self.max_pages = max_pages
        self.timeout = timeout
        self._urlopen = urlopen
        self._token = ""
        self._token_expires = 0.0

    # Source interface -------------------------------------------------------------------------

    def list_ids(self, since: datetime) -> list[str]:
        # `after:` takes a unix timestamp, so the window is exact to the second.
        params = {"q": f"{BASE_QUERY} after:{int(since.timestamp())}", "maxResults": self.page_size}
        ids: list[str] = []
        for _ in range(self.max_pages):
            data = self._get("messages", params)
            ids += [item["id"] for item in data.get("messages", [])]
            if not data.get("nextPageToken"):
                break
            params = {**params, "pageToken": data["nextPageToken"]}
        return ids

    def envelope(self, msg_id: str) -> Envelope:
        data = self._get(f"messages/{msg_id}", [("format", "metadata"), ("metadataHeaders", "From"), ("metadataHeaders", "Subject")])
        headers = _headers(data)
        return Envelope(
            id=msg_id,
            inbox=self.inbox,
            thread_id=data.get("threadId", msg_id),
            sender=headers.get("from", ""),
            subject=headers.get("subject", ""),
            received=datetime.fromtimestamp(int(data["internalDate"]) / 1000, tz=timezone.utc),
        )

    def thread(self, envelope: Envelope) -> list[ThreadItem]:
        data = self._get(
            f"threads/{envelope.thread_id}", [("format", "metadata"), ("metadataHeaders", "From"), ("metadataHeaders", "Subject")]
        )
        items = []
        for message in data.get("messages", []):
            headers = _headers(message)
            sender = headers.get("from", "")
            from_user = "SENT" in message.get("labelIds", []) or parseaddr(sender)[1].lower() == self.inbox
            items.append(ThreadItem(sender, headers.get("subject", ""), from_user))
        return items

    def body(self, envelope: Envelope) -> str:
        data = self._get(f"messages/{envelope.id}", {"format": "raw"})
        raw = data["raw"]
        return body_text(parse_message(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))))

    # HTTP -------------------------------------------------------------------------------------

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        client_id, client_secret, refresh_token = self._client
        form = urllib.parse.urlencode(
            {"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token, "grant_type": "refresh_token"}
        ).encode()
        try:
            payload = self._call(urllib.request.Request(TOKEN_URL, data=form))
        except GmailError as exc:
            if exc.status in (400, 401):
                raise ConfigError(f"Google rejected the OAuth client or refresh token for {self.inbox}") from None
            raise
        self._token = payload["access_token"]
        self._token_expires = time.time() + int(payload.get("expires_in", 3600))
        return self._token

    def _get(self, path: str, params) -> dict:
        url = API_ROOT + path + "?" + urllib.parse.urlencode(params, doseq=True)
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._access_token()}"})
        return self._call(request)

    def _call(self, request: urllib.request.Request) -> dict:
        endpoint = urllib.parse.urlsplit(request.full_url).path
        try:
            with self._urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise GmailError(f"HTTP {exc.code} from {endpoint}", status=exc.code) from None
        except urllib.error.URLError as exc:
            raise GmailError(f"network error calling {endpoint}: {exc.reason}") from None


def _headers(message: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
