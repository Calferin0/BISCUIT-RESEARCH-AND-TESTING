"""Biscuit Points: earned from things already in the database, never stored as a running total.

Computing points from activity (rather than incrementing a balance) means there is no counter to
drift out of sync, and the rules below can be retuned at any time without a migration.
Spending (cosmetics) will add a ledger of *spends*. Balance = earned - spent.
"""
from __future__ import annotations

from dataclasses import dataclass

NOTE_MIN_CHARS = 20  # a "field note" worth a bonus, not just "nice"


@dataclass(frozen=True)
class Rule:
    key: str      # column name in db.points_activity()
    points: int
    icon: str
    label: str


RULES: tuple[Rule, ...] = (
    Rule("reports", 10, "📝", "Field report filed"),
    Rule("notes", 3, "✍️", f"Report with proper field notes ({NOTE_MIN_CHARS}+ characters)"),
    Rule("thumbs", 5, "👍", "Thumbs-up received on one of your reports"),
    Rule("specimens", 15, "🔬", "New specimen logged"),
    Rule("drops", 5, "📅", "Biscuit drop logged"),
    Rule("suggestions", 2, "📮", "Suggestion posted"),
    Rule("shipped", 10, "🚀", "Your suggestion got built"),
)

RANKS: tuple[tuple[int, str], ...] = (  # (minimum points, title), checked top-down
    (500, "🏛️ Biscuit Laureate"),
    (300, "🎖️ Senior Crumb Analyst"),
    (150, "🔍 Field Agent"),
    (50, "🍪 Junior Taster"),
    (0, "🥚 Recruit"),
)


def breakdown(activity) -> list[dict]:
    """Per-rule counts and points for one agent's activity row."""
    return [{"icon": r.icon, "label": r.label, "count": activity[r.key] or 0, "each": r.points,
             "points": (activity[r.key] or 0) * r.points} for r in RULES]


def total(activity) -> int:
    return sum(item["points"] for item in breakdown(activity))


def rank(points: int) -> str:
    for minimum, title in RANKS:
        if points >= minimum:
            return title
    return RANKS[-1][1]


def next_rank(points: int) -> tuple[str, int] | None:
    """(title, points still needed) for the next rank up, or None at the top."""
    above = [(m, t) for m, t in RANKS if m > points]
    if not above:
        return None
    minimum, title = min(above)
    return title, minimum - points
