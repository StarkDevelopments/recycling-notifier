"""Pure report-building logic.

Turn a list of collections and a "today" date into a human-readable
notification (or None when there is nothing to say). No I/O and no env access
here, so the logic is unit-tested in isolation; `app.py` does the fetching and
sending around it.

Problems are reported on their own: when a collection looks missed or a state
needs attention, the report talks about that only — it doesn't pad it out with
the (obvious) "no collections tomorrow" line. A collection whose state is
``In Progress`` is treated as normal (the crew is actively collecting), so it
never triggers a warning.

Works for household UPRNs (Refuse/Food/Recycling) and trade UPRNs (Trade
Refuse/Trade Food/Trade Recycling) alike: trade records may have a null
schedule description, and ``Closed Completed with Exception`` counts as a
normal completion, not a problem.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from scraper import Collection

HEALTHY_STATE = "Closed Completed"
IN_PROGRESS_STATE = "In Progress"
DEFAULT_USUAL_DAY = "Monday"
_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass
class Report:
    title: str
    body: str


def build_report(collections: list[Collection], today: date, usual_day: int = 0) -> Report | None:
    """Build a human-readable report relative to `today` (compared in UK time).

    `usual_day` is the user's normal collection weekday (0=Monday). When
    tomorrow is that weekday but nothing is scheduled, the report is a "no
    collections on usual date" dead-man's check rather than a generic "none".
    Problems (a collection due today that isn't confirmed collected, or a state
    that needs attention) override any "collections tomorrow" text: the report
    is about the problem and only the problem.

    Returns None when there is nothing to say: no collections tomorrow, tomorrow
    is not the user's usual day, and nothing needs attention. A quiet run like
    that is expected and shouldn't ping.
    """
    tomorrow = today + timedelta(days=1)
    upcoming = _due_on(collections, tomorrow)
    pending, state_only = _problems(collections, today)
    usual_tomorrow = tomorrow.weekday() == usual_day

    if not upcoming and not pending and not state_only and not usual_tomorrow:
        return None

    if pending or state_only:
        lines = []
        if pending:
            lines.append("Collections due today haven't been confirmed as collected:")
            lines.extend(f"- {c.service}: {detail}" for c, detail in pending)
        if state_only:
            if lines:
                lines.append("")
            lines.append("Collection states need attention:")
            lines.extend(f"- {c.service}: {detail}" for c, detail in state_only)
        title = "Recycling: action needed" if pending else "Recycling: check status"
        return Report(title=title, body="\n".join(lines))

    lines = []
    if upcoming:
        lines.append(f"Collections tomorrow ({_fmt(tomorrow)}):")
        lines.extend(
            f"- {c.service} ({c.schedule_description})" if c.schedule_description else f"- {c.service}"
            for c in upcoming
        )
        title = "Recycling collections tomorrow"
    elif usual_tomorrow:
        lines.append(
            f"No collections tomorrow ({_fmt_ordinal(tomorrow)}), which is the "
            f"usual collection day ({_day_name(usual_day)})."
        )
        title = "No collections on usual date"
    else:
        lines.append(f"No collections tomorrow ({_fmt(tomorrow)}).")
        title = "No recycling collections tomorrow"
    return Report(title=title, body="\n".join(lines))


def parse_weekday(value: str) -> int:
    """Map a weekday name (case-insensitive) to 0=Monday .. 6=Sunday."""
    normalized = value.strip().lower()
    for i, name in enumerate(_DAY_NAMES):
        if name.lower() == normalized:
            return i
    raise ValueError(f"Unknown weekday {value!r}; use one of: {', '.join(_DAY_NAMES)}")


def _problems(collections: list[Collection], today: date) -> tuple[list[tuple[Collection, str]], list[tuple[Collection, str]]]:
    """Split collections that need attention into two buckets.

    - `pending`: scheduled today but not confirmed collected. A state of
      ``In Progress`` means the crew is actively collecting and is normal, so
      it never counts as pending.
    - `state_only`: an unexpected state (anything not completed or in progress)
      on a collection not due today. States beginning ``Closed Completed``
      (e.g. ``Closed Completed with Exception``, common on trade rounds) count
      as completed and stay quiet; only genuinely unresolved states like
      ``Closed Not Completed`` are flagged.
    """
    pending: list[tuple[Collection, str]] = []
    state_only: list[tuple[Collection, str]] = []
    for c in collections:
        if _was_due(c, today) and not _completed_ok(c) and c.state_name != IN_PROGRESS_STATE:
            detail = "no completion recorded" if (not c.state_name or _is_completed_state(c.state_name)) else c.state_name
            pending.append((c, detail))
        elif c.state_name and c.state_name != IN_PROGRESS_STATE and not _is_completed_state(c.state_name):
            state_only.append((c, c.state_name))
    return pending, state_only


def _due_on(collections: list[Collection], day: date) -> list[Collection]:
    return sorted(
        (c for c in collections if _is_due(c, day)),
        key=lambda c: c.service or "",
    )


def _is_due(c: Collection, day: date) -> bool:
    return c.next_collection is not None and c.next_collection.date() == day


def _was_due(c: Collection, day: date) -> bool:
    return c.last_collection is not None and c.last_collection.date() == day


def _completed_ok(c: Collection) -> bool:
    return c.last_collection_completed is not None and _is_completed_state(c.state_name)


def _is_completed_state(state_name: str | None) -> bool:
    """True for completed states, including trade's ``Closed Completed with Exception``."""
    return bool(state_name) and state_name.startswith(HEALTHY_STATE)


def _fmt(day: date) -> str:
    return day.strftime("%A %d %b")


def _fmt_ordinal(day: date) -> str:
    suffix = "th" if 11 <= day.day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day.day % 10, "th")
    return f"{day:%A} {day.day}{suffix} {day:%b}"


def _day_name(weekday: int) -> str:
    return _DAY_NAMES[weekday]
