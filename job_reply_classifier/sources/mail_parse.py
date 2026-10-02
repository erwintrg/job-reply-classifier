"""Raw RFC 822 mail to plain text. Shared by the fixture source and the Gmail source.

Gmail is asked for `format=raw`, the same bytes an .eml file holds, so the offline demo runs
exactly the parsing code that real mode runs.
"""
from __future__ import annotations

import re
from email import message_from_bytes, policy
from email.message import EmailMessage
from html.parser import HTMLParser


def parse_message(raw: bytes) -> EmailMessage:
    return message_from_bytes(raw, policy=policy.default)  # type: ignore[return-value]


def header(msg: EmailMessage, name: str) -> str:
    value = msg.get(name)
    return " ".join(str(value).split()) if value is not None else ""


def thread_root(msg: EmailMessage) -> str:
    """The first Message-ID of the conversation: References lists ancestors oldest first."""
    references = header(msg, "References").split()
    if references:
        return references[0]
    in_reply_to = header(msg, "In-Reply-To").split()
    if in_reply_to:
        return in_reply_to[0]
    return header(msg, "Message-ID")


def body_text(msg: EmailMessage) -> str:
    """Plain text of the mail: prefers text/plain, falls back to text/html, drops quoted history."""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeDecodeError):  # unknown or lying charset
        content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
    if part.get_content_type() == "text/html":
        content = html_to_text(content)
    return tidy(strip_quoted(content))


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "blockquote"}
    SKIP = {"script", "style", "head", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(re.sub(r"\s+", " ", data))


def html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    return "".join(parser.parts)


_QUOTE_START = re.compile(
    r"^(On .{5,200} wrote:|Am .{5,200} schrieb .{1,200}:|-{2,} ?Original Message ?-{2,}|-{2,} ?Ursprüngliche Nachricht ?-{2,})\s*$",
    re.IGNORECASE,
)


def strip_quoted(text: str) -> str:
    """Cut the quoted history of a reply: it repeats your own mail and adds nothing to classify."""
    kept = []
    for line in text.splitlines():
        if _QUOTE_START.match(line.strip()):
            break
        if line.lstrip().startswith(">"):
            continue
        kept.append(line)
    return "\n".join(kept)


def tidy(text: str) -> str:
    """Trim every line and collapse runs of blank lines."""
    lines = [" ".join(line.split()) for line in text.splitlines()]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()
