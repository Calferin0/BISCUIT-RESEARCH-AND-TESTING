"""R&D birthday tracker. Pure: no Flask, no SQL.

Birthdays are stored as 'MM-DD' on `members.birthday`: day and month only, never a year, so
nobody's age is on file. They live in the DB only, never in the repo (it's public).
29 Feb birthdays are celebrated on 28 Feb in non-leap years.
"""
from __future__ import annotations

import calendar
import re
from datetime import date

GIFT = 50          # points, once a year, on the day (via the ledger, D21)
SOON_DAYS = 7      # "coming up" window for the banner/strip


def parse(text: str) -> str | None:
    """'19/11', '1/02', '09-03' (UK day first) -> 'MM-DD', or None if it isn't a real date."""
    m = re.fullmatch(r"\s*(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*", text or "")
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12 or not 1 <= day <= (29 if month == 2 else calendar.monthrange(2001, month)[1]):
        return None
    return f"{month:02d}-{day:02d}"


def _on(mmdd: str, year: int) -> date:
    month, day = int(mmdd[:2]), int(mmdd[3:])
    if month == 2 and day == 29 and not calendar.isleap(year):
        day = 28
    return date(year, month, day)


def next_date(mmdd: str, today: date) -> date:
    """The next time this birthday happens, counting today."""
    this_year = _on(mmdd, today.year)
    return this_year if this_year >= today else _on(mmdd, today.year + 1)


def days_until(mmdd: str, today: date) -> int:
    return (next_date(mmdd, today) - today).days


def is_today(mmdd: str | None, today: date) -> bool:
    return bool(mmdd) and _on(mmdd, today.year) == today


def label(mmdd: str) -> str:
    """'11-19' -> '19 Nov'."""
    return f"{int(mmdd[3:])} {calendar.month_abbr[int(mmdd[:2])]}"


def form_value(mmdd: str | None) -> str:
    """'11-19' -> '19/11', for pre-filling a dd/mm input."""
    return f"{mmdd[3:]}/{mmdd[:2]}" if mmdd else ""


def upcoming(rows: list, today: date) -> list[dict]:
    """rows with `birthday`: soonest first, each with `days` and `label` added. No birthday = skipped."""
    out = [{**dict(r), "days": days_until(r["birthday"], today), "label": label(r["birthday"])}
           for r in rows if r["birthday"]]
    return sorted(out, key=lambda r: (r["days"], r["name"].lower()))
