"""Deterministic keyword classifier for the offline demo and the tests.

It stands in for the LLM so the pipeline can run without a key or a network. It is not a
replacement for the real classifier: it does not understand context, it only matches German and
English phrases. It never reads instructions inside a mail, because it reads nothing at all, so
the prompt injection fixture says nothing about it; that fixture is for the real classifiers.
"""
from __future__ import annotations

import re

from ..models import Classification, Envelope

JOB_CONTEXT = re.compile(
    r"\b(application|applying|applied|bewerbung|bewerben|position|role|candidates?|kandidat\w*|stelle|"
    r"interview|vorstellungsgespräch\w*|kennenlern\w*|recruit\w*|hiring)\b",
    re.IGNORECASE,
)
NEGATIVE = re.compile(
    r"(unfortunately|regret to inform|not (?:to )?mov(?:e|ing) forward|move forward with other candidates|"
    r"position has been filled|leider|absage|nicht weiter berücksichtigen|für eine?n? andere)",
    re.IGNORECASE,
)
QUESTION_TOPICS = (
    ("salary expectations", re.compile(r"(salary expectations?|gehaltsvorstellung\w*|gehaltswunsch)", re.IGNORECASE)),
    ("earliest start date", re.compile(r"(start date|eintrittstermin|frühester? \w*\s?eintritt)", re.IGNORECASE)),
    ("documents", re.compile(r"(unterlagen nachreichen|zeugnisse|please send (?:us )?(?:your )?(?:cv|documents))", re.IGNORECASE)),
)
POSITIVE = re.compile(
    r"(invite you|invitation to|interview|like to (?:meet|talk|schedule)|schedule a call|your availability|"
    r"einladen|einladung|kennenlerngespräch|vorstellungsgespräch|job offer|offer letter)",
    re.IGNORECASE,
)
RECEIPT = re.compile(
    r"(received your application|thank you for applying|thanks for applying|eingegangen|eingangsbestätigung)",
    re.IGNORECASE,
)

_STOP = r"(?=\s+\(|\s+at\s|\s+bei\s|\s+role\b|\s+position\b|[.,;:!?]\s|[.,;:!?]?$|\n)"
ROLE_PATTERNS = (
    # "application for the position X", "Bewerbung als X", "applying for the X role"
    re.compile(
        r"(?:applying|application|bewerbung)\s+(?:for|als|as|für)\s+(?:the\s+|die\s+|den\s+)?"
        r"(?:position\s+|role\s+|stelle\s+)?(?:of\s+|als\s+)?(?P<role>[^\n(]+?)" + _STOP,
        re.IGNORECASE,
    ),
    # "Interview invitation: X at Company"
    re.compile(r"(?:application|bewerbung|invitation|einladung)\s*:\s*(?P<role>[^\n(]+?)" + _STOP, re.IGNORECASE),
    # "an der Position X (m/w/d)": keyword in any case, the role itself starts with a capital
    re.compile(r"(?i:position|role|stelle)\s+(?:(?i:as|als|of)\s+)?(?P<role>[A-ZÄÖÜ0-9][^\n(]{2,60}?)" + _STOP),
)
# "Initech Digital GmbH", "Hooli Labs Inc.": words joined by single spaces only, never across lines
LEGAL_ENTITY = re.compile(r"\b((?:[A-ZÄÖÜ][\w&-]* ){0,3}[A-ZÄÖÜ][\w&-]* (?:GmbH|AG|SE|KG|Inc\.|Ltd\.?|LLC))")
SENDER_SUFFIX = re.compile(
    r"\s+(?:(?:via|über)\s+\S+|careers|recruiting|recruitment|talent(?:\s+team|\s+acquisition)?|jobs|hr|team)$",
    re.IGNORECASE,
)

MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("january", "januar"), ("february", "februar"), ("march", "märz"), ("april",), ("may", "mai"),
            ("june", "juni"), ("july", "juli"), ("august",), ("september",), ("october", "oktober"),
            ("november",), ("december", "dezember"),
        ),
        start=1,
    )
    for name in names
}
_MONTH_NAMES = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_PATTERNS = (
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b"),
    re.compile(r"\b(?P<d>\d{1,2})\.\s?(?P<m>\d{1,2})\.\s?(?P<y>\d{4})\b"),
    re.compile(rf"\b(?P<d>\d{{1,2}})\.?\s+(?P<mon>{_MONTH_NAMES})\s+(?P<y>\d{{4}})\b", re.IGNORECASE),
    re.compile(rf"\b(?P<mon>{_MONTH_NAMES})\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>\d{{4}})\b", re.IGNORECASE),
)
TIME_AFTER_DATE = re.compile(r"^\D{0,12}?(?P<h>\d{1,2}):(?P<mi>\d{2})")


class MockClassifier:
    name = "mock"

    def classify(self, envelope: Envelope, body: str) -> Classification:
        text = f"{envelope.subject}\n{body}"
        if not JOB_CONTEXT.search(text):
            return Classification("not_job", summary="Not about a job application.")
        deadline = first_date(body)
        topics = [label for label, pattern in QUESTION_TOPICS if pattern.search(text)]
        if NEGATIVE.search(text):
            kind, summary = "negative", "Rejection: they will not move forward with this application."
        elif topics:
            kind = "question"
            summary = f"Asks for {' and '.join(topics)}" + (f", reply by {deadline}." if deadline else ".")
        elif POSITIVE.search(text):
            kind = "positive"
            summary = "Invites you to an interview or call" + (f" on {deadline}." if deadline else ".")
        elif RECEIPT.search(text):
            kind, summary = "receipt", "Automatic confirmation that the application arrived."
        else:
            return Classification("not_job", summary="Mentions a job but is not a reply to an application.")
        return Classification(
            kind=kind,
            company=guess_company(envelope, body),
            role=guess_role(envelope.subject, body),
            summary=summary,
            deadline=deadline if kind in ("positive", "question") else "",
        )


def guess_role(subject: str, body: str) -> str:
    for pattern in ROLE_PATTERNS:
        for text in (subject, body):
            match = pattern.search(text)
            if match:
                return match.group("role").strip(" \"'")
    return ""


def guess_company(envelope: Envelope, body: str) -> str:
    match = LEGAL_ENTITY.search(body)
    if match:
        return match.group(1)
    name = SENDER_SUFFIX.sub("", envelope.sender_name).strip()
    if name and "@" not in name:
        return name
    domain = envelope.sender_address.rsplit("@", 1)[-1].split(".")[0]
    return domain.replace("-", " ").title()


def first_date(text: str) -> str:
    """The earliest date written in the text, with a time if one follows it closely."""
    found = []
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(text):
            parts = match.groupdict()
            month = MONTHS[parts["mon"].lower()] if parts.get("mon") else int(parts["m"])
            day, year = int(parts["d"]), int(parts["y"])
            if not (1 <= month <= 12 and 1 <= day <= 31):
                continue
            stamp = f"{year:04d}-{month:02d}-{day:02d}"
            clock = TIME_AFTER_DATE.match(text[match.end() : match.end() + 20])
            if clock and int(clock["h"]) < 24:
                stamp += f" {int(clock['h']):02d}:{clock['mi']}"
            found.append(stamp)
    return min(found) if found else ""
