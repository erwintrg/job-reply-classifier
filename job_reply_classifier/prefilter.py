"""Cheap, regex-only checks that decide which mails are worth an LLM call.

Order matters:

1. your own mail is never a reply to you;
2. noise (job alerts, newsletters) is dropped first, because job alerts are full of
   application words ("Neue Stelle für Sie", "12 new positions") and would pass every later check;
3. an applicant tracking system (ATS) as sender, application words in the subject, or a thread
   you started with an application make a mail a candidate;
4. everything else is skipped without an LLM call.

The rules are tuned for recall, not precision. A client mail about "next steps" gets through and
the classifier drops it later. Missing a real reply costs more than one extra Haiku call.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from .models import Envelope, ThreadItem

ATS_SENDER = re.compile(
    r"(workday|myworkday|greenhouse|lever\.co|personio|join\.com|smartrecruiters|recruitee|softgarden|"
    r"successfactors|teamtailor|workable|ashbyhq|bamboohr|dvinci|d\.vinci|rexx|onlyfy|prescreen|jobvite|"
    r"icims|taleo|zohorecruit|heyrecruit|coveto|umantis|haufe|talention|concludis|milch-zucker|b-ite|"
    r"recruiting|recruitment|karriere|career|jobs@|bewerbung|talent|hr@|personal@|people@)",
    re.IGNORECASE,
)

APPLICATION_WORDS = re.compile(
    r"(bewerbung|application|applying|candidacy|kandidatur|interview|vorstellungsgespr|kennenlern|absage|"
    r"rückmeldung|next steps|nächste schritte|position|stelle\b|role\b|talent acquisition|recruit)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NoiseRule:
    label: str
    field: str  # "sender" or "subject"
    pattern: re.Pattern


NOISE_RULES: Sequence[NoiseRule] = (
    NoiseRule(
        "job alert",
        "sender",
        re.compile(
            r"(jobalerts?-noreply@linkedin\.com|jobs-noreply@linkedin\.com|@match\.indeed\.com|alert@indeed\.com|"
            r"jobagent|jobalert|job-alert|noreply@glassdoor\.com)",
            re.IGNORECASE,
        ),
    ),
    NoiseRule("job alert", "subject", re.compile(r"(job ?alert|jobalarm|jobagent|new jobs for you|neue jobs für sie)", re.IGNORECASE)),
    NoiseRule(
        "newsletter",
        "sender",
        re.compile(r"(newsletter|substack\.com|beehiiv\.com|list-manage\.com|mailchimp|convertkit)", re.IGNORECASE),
    ),
    NoiseRule("newsletter", "subject", re.compile(r"\bnewsletter\b", re.IGNORECASE)),
)


@dataclass(frozen=True)
class Decision:
    candidate: bool
    reason: str


ThreadLookup = Callable[[], Iterable[ThreadItem]]


class PreFilter:
    def __init__(
        self,
        ats: re.Pattern = ATS_SENDER,
        words: re.Pattern = APPLICATION_WORDS,
        noise: Sequence[NoiseRule] = NOISE_RULES,
    ) -> None:
        self.ats = ats
        self.words = words
        self.noise = noise

    def check(self, envelope: Envelope, thread: ThreadLookup | None = None) -> Decision:
        """Decide whether a mail goes to the classifier.

        `thread` is called lazily, only when the cheaper header checks found nothing,
        because it costs an extra API call per mail.
        """
        if envelope.sender_address and envelope.sender_address == envelope.inbox.lower():
            return Decision(False, "your own mail")
        for rule in self.noise:
            value = envelope.sender if rule.field == "sender" else envelope.subject
            if rule.pattern.search(value):
                return Decision(False, rule.label)
        # The address says more than the display name ("myworkday" beats "Careers"), so try it first.
        match = self.ats.search(envelope.sender_address) or self.ats.search(envelope.sender)
        if match:
            return Decision(True, f'ATS sender "{match.group(0).lower()}"')
        match = self.words.search(envelope.subject)
        if match:
            return Decision(True, f'subject: "{match.group(0).lower()}"')
        if thread is not None and self.started_with_application(thread()):
            return Decision(True, "your application thread")
        return Decision(False, "no job signal")

    def started_with_application(self, items: Iterable[ThreadItem]) -> bool:
        """True when you wrote into this thread with an application-like subject."""
        return any(item.from_user and self.words.search(item.subject) for item in items)
