"""Plain-text tables for the demo and for --dry-run. No dependencies."""
from __future__ import annotations

from typing import Iterable, Sequence

from .pipeline import RETRY, RunReport


def shorten(text: object, width: int) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= width else flat[: width - 3].rstrip() + "..."


def table(headers: Sequence[str], rows: Iterable[Sequence[object]], widths: Sequence[int], indent: str = "  ") -> str:
    def line(cells: Sequence[object]) -> str:
        return (indent + "  ".join(shorten(cell, width).ljust(width) for cell, width in zip(cells, widths))).rstrip()

    return "\n".join([line(headers), line(["-" * width for width in widths]), *(line(row) for row in rows)])


def describe_run(report: RunReport) -> str:
    """One row per new mail: what the pre-filter said, what the classifier said, where it went."""
    rows = []
    for outcome in sorted(report.outcomes, key=lambda o: o.envelope.received):
        kind = outcome.classification.kind if outcome.classification else "-"
        if outcome.route is not None:
            routed = outcome.route.priority
        else:
            routed = "retry" if outcome.status == RETRY else "-"
        rows.append(
            [
                outcome.envelope.received.astimezone(report.now.tzinfo).strftime("%m-%d %H:%M"),
                outcome.envelope.sender_name,
                outcome.envelope.subject,
                outcome.reason,
                kind,
                routed,
            ]
        )
    if not rows:
        return "  no new mail"
    return table(["Received", "From", "Subject", "Pre-filter", "Kind", "Route"], rows, [11, 22, 34, 30, 12, 6])
