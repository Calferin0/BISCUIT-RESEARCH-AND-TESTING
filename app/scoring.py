"""Rating categories and verdicts: the silly bits, kept in one place.

Scores live in a long `scores` table (rating_id, category, value), so adding, removing or
renaming a category here needs no schema migration. Old scores under a removed key are kept in
the DB but ignored. Older ratings simply lack a newly added key until the agent amends them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    key: str     # stored in scores.category: never rename casually, old rows keep the old key
    label: str
    short: str   # chip label on field reports
    hint: str
    # Biscuit award for the top scorer in this category (leaderboard).
    award_icon: str
    award_title: str
    award_tag: str
    # Skippable categories (the dunk pair) can be left blank by a "Dry Land Purist". A skip is
    # stored as *no score row*, so every average naturally ignores it.
    skippable: bool = False


# The opt-out for non-dunkers. One tickbox skips every skippable category.
PURIST_FIELD = "dry_purist"
PURIST_LABEL = "🏜️ Dry Land Purist"
PURIST_PITCH = "I don't dunk. Tea is for drinking, biscuits are for eating. Skip both dunk ratings."

CATEGORIES: tuple[Category, ...] = (
    Category("mouthfeel", "Mouthfeel", "Mouthfeel", "Velvet on the tongue, or a mouthful of sawdust?",
             "🧈", "Smoothest Operator", "Glides in like it owns the place."),
    Category("moreish", "Moreishness", "Moreish", "Can you stop at one? Be honest.",
             "🔁", "Just One More", "The packet empties itself, apparently."),
    Category("taste", "Taste", "Taste", "Does it actually taste good?",
             "😋", "Flavour Bomb", "Taste buds filed a thank-you note."),
    Category("presentation", "Presentation", "Looks", "Would it look good on the boardroom plate?",
             "🎩", "Best Dressed", "Red-carpet ready. Crumb-free cuffs."),
    Category("snap", "Snap", "Snap", "A clean, satisfying break?",
             "💥", "Loudest Snap", "Heard from the next desk. Twice."),
    Category("excitement", "Excitement / Anticipation", "Hype", "How excited were you when you spotted it in the tin?",
             "🤩", "Most Hyped", "The office gasped when the lid came off."),
    Category("dunk_better", "Dunkability 1: Better with dunk?", "Dunk+", "5 = transformed by tea",
             "🫖", "Tea's Best Friend", "Was born to be dunked.", skippable=True),
    Category("dunk_resist", "Dunkability 2: Dunk time / resistance", "Dunk time", "5 = survives a long dunk without collapsing",
             "🛟", "Unsinkable", "Went in. Came out. Tells the tale.", skippable=True),
    Category("afford", "Affordability", "£", "5 = cheap as chips",
             "💷", "Budget Hero", "Finance department approves."),
    Category("sniff", "Sniff test", "Sniff", "Open the packet. Inhale. Judge.",
             "👃", "Best Bouquet", "Notes of butter, with a finish of 'more please'."),
)

CATEGORY_KEYS: tuple[str, ...] = tuple(c.key for c in CATEGORIES)
SKIPPABLE_KEYS: tuple[str, ...] = tuple(c.key for c in CATEGORIES if c.skippable)


def is_purist(scores: dict) -> bool:
    """A rating that skipped every skippable (dunk) category."""
    return bool(SKIPPABLE_KEYS) and not any(k in scores for k in SKIPPABLE_KEYS)

# Keys get inlined into SQL as literals (db.CATS_IN), so they must stay boring identifiers.
# This is a real check, not an assert: asserts vanish under `python -O`.
if len(set(CATEGORY_KEYS)) != len(CATEGORY_KEYS) or not all(re.fullmatch(r"[a-z_]+", k) for k in CATEGORY_KEYS):
    raise ValueError("Category keys must be unique and match [a-z_]+")

AVATARS: tuple[str, ...] = (
    "🍪", "🥨", "🧁", "🫖", "☕", "🍩", "🥐", "🧇", "🎬",
    "🎥", "📹", "🕵️", "🦊", "🐙", "🦉", "🚀", "🛰️", "🎯",
)


@dataclass(frozen=True)
class Verdict:
    stamp: str
    tone: str  # good | meh | bad -> CSS class
    line: str


# (minimum overall score, verdict), checked top-down.
_VERDICTS: tuple[tuple[float, Verdict], ...] = (
    (4.5, Verdict("Approved", "good", "Locked off. Buttery smooth. Print it.")),
    (3.5, Verdict("Approved", "good", "Solid take. Minor wobble, nobody will notice.")),
    (2.5, Verdict("Under review", "meh", "We'll fix it in post.")),
    (1.5, Verdict("Rejected", "bad", "Needs a reshoot.")),
    (0.0, Verdict("Rejected", "bad", "Lost in the edit. Burn the negatives.")),
)


def verdict(overall: float | None) -> Verdict | None:
    if overall is None:
        return None
    for threshold, v in _VERDICTS:
        if overall >= threshold:
            return v
    return _VERDICTS[-1][1]
