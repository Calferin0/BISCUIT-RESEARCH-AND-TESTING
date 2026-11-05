"""Mystery Tins (lootboxes). Points only, never money. The odds are shown on the page in full.

Roll a rarity tier by weight; common = a points refund, any other tier = a random lootbox-only
cosmetic of that tier. Already own it? It converts to points (no dead pulls).
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from . import shop

BOX_COST = 40
ODDS: tuple[tuple[str, float], ...] = (     # tier, percent; must sum to 100
    ("common", 50.0), ("uncommon", 27.0), ("rare", 15.0), ("epic", 6.5), ("legendary", 1.5),
)
COMMON_REFUND = (15, 35)                     # points back on a common roll (inclusive range)
DUPE_POINTS = {"uncommon": 25, "rare": 45, "epic": 80, "legendary": 150}

QUIPS = {
    "common": ("Just crumbs. And a few points.", "A single broken custard cream. Points instead.",
               "The tin was mostly cardboard.", "Someone ate it already. Have some points."),
    "uncommon": ("Ooh, not bad!", "A respectable find.", "Better than a Rich Tea."),
    "rare": ("RARE! The kitchen goes quiet.", "Now THAT'S a biscuit.", "Rare drop. Screenshot it."),
    "epic": ("EPIC!! Someone call HR, this is too good.", "The tin is glowing purple."),
    "legendary": ("🚨 LEGENDARY 🚨 Frame this moment.", "THE TIN SPEAKS. You are chosen."),
}


@dataclass(frozen=True)
class Pull:
    tier: str
    item: shop.Item | None     # None = points-only result
    points: int                # points credited back (refund or duplicate conversion)
    duplicate: bool
    quip: str


def roll_tier(rng: random.Random) -> str:
    tiers, weights = zip(*ODDS)
    return rng.choices(tiers, weights=weights)[0]


def open_tin(owned: set[str], rng: random.Random) -> Pull:
    tier = roll_tier(rng)
    quip = rng.choice(QUIPS[tier])
    if tier == "common":
        return Pull(tier, None, rng.randint(*COMMON_REFUND), False, quip)
    pool = [i for i in shop.CATALOGUE if i.loot_tier == tier]
    item = rng.choice(pool)
    if item.key in owned:
        return Pull(tier, item, DUPE_POINTS[tier], True, quip)
    return Pull(tier, item, 0, False, quip)


def expected_value() -> float:
    """Average points-equivalent back per tin, for the odds panel. Counts loot at its dupe value."""
    ev = 0.0
    for tier, pct in ODDS:
        value = sum(COMMON_REFUND) / 2 if tier == "common" else DUPE_POINTS[tier]
        ev += pct / 100 * value
    return ev
