"""Case lifecycle: when a biscuit's results become public, and whether it can still be rated.

Blind rating (D10) is relaxed in two ways, both requested by CF (2026-11-05):
  * a case goes **public** PUBLIC_AFTER_DAYS after the biscuit was logged, so results don't stay
    hidden forever from people who never try it;
  * a **closed** case (biscuit no longer in shops) is public straight away and takes no new reports.
Before that, the leaderboard shows a biscuit's *name and place* to everyone but hides its *score*.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

PUBLIC_AFTER_DAYS = 7


def logged_on(b) -> date:
    return datetime.fromisoformat(b["created_at"]).date()


def unseals_on(b) -> date:
    return logged_on(b) + timedelta(days=PUBLIC_AFTER_DAYS)


def is_closed(b) -> bool:
    return (b["case_status"] or "open") == "closed"


def is_public(b, today: date) -> bool:
    return is_closed(b) or today >= unseals_on(b)


def can_see(b, rated_by_viewer: bool, today: date) -> bool:
    """May this viewer see this biscuit's scores?"""
    return bool(rated_by_viewer) or is_public(b, today)
