"""Mystery Tins (lootboxes). Points only, never money. The odds are shown on the page in full.

Roll a rarity tier by weight; common = a points refund, any other tier = a lootbox-only
cosmetic of that tier, picked from the ones you *don't* own yet. Only once you own the whole
tier does a pull convert to points (no dead pulls).

2026-11-19 retune (#10, CF: "fun and rewarding most of the time"): pays back ~110% on average
(it was ~84%), 70% of tins hold a cosmetic, and a pity timer guarantees Rare or better at
least every PITY tins. Points minted here go through the ledger like everything else (D21).
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from . import shop

BOX_COST = 40
ODDS: tuple[tuple[str, float], ...] = (     # tier, percent; must sum to 100
    ("common", 30.0), ("uncommon", 36.0), ("rare", 22.0), ("epic", 9.0), ("legendary", 3.0),
)
COMMON_REFUND = (20, 40)                     # points back on a common roll (inclusive range)
DUPE_POINTS = {"uncommon": 30, "rare": 50, "epic": 85, "legendary": 160}
PITY = 8                                     # Rare or better at least once every PITY tins
GOOD_TIERS = ("rare", "epic", "legendary")

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


def roll_lucky(rng: random.Random) -> str:
    """The pity roll: only Rare or better, keeping their relative odds."""
    tiers, weights = zip(*[(t, w) for t, w in ODDS if t in GOOD_TIERS])
    return rng.choices(tiers, weights=weights)[0]


def pity_due(dry_streak: int) -> bool:
    """dry_streak = tins opened since the last Rare-or-better. The PITY-th tin is guaranteed."""
    return dry_streak >= PITY - 1


def open_tin(owned: set[str], rng: random.Random, dry_streak: int = 0) -> Pull:
    tier = roll_lucky(rng) if pity_due(dry_streak) else roll_tier(rng)
    quip = rng.choice(QUIPS[tier])
    if tier == "common":
        return Pull(tier, None, rng.randint(*COMMON_REFUND), False, quip)
    pool = [i for i in shop.CATALOGUE if i.loot_tier == tier]
    fresh = [i for i in pool if i.key not in owned]
    if fresh:                                # new stuff first: duplicates only once the tier is complete
        return Pull(tier, rng.choice(fresh), 0, False, quip)
    return Pull(tier, rng.choice(pool), DUPE_POINTS[tier], True, quip)


def expected_value() -> float:
    """Average points-equivalent back per tin, for the odds panel. Counts loot at its dupe value."""
    ev = 0.0
    for tier, pct in ODDS:
        value = sum(COMMON_REFUND) / 2 if tier == "common" else DUPE_POINTS[tier]
        ev += pct / 100 * value
    return ev


# --- the case-opening reel (2026-11-23) -------------------------------------------------------
# Pure theatre: the prize is decided by open_tin() before the page loads. The reel is a strip of
# random fillers rolled with the same ODDS, with the real prize placed at REEL_STOP, so the
# animation always lands on what you actually won.

REEL_LENGTH = 48
REEL_STOP = 40
SLOT_ICONS = {"title": "🏷️", "color": "🎨", "frame": "🖼️", "effect": "✨", "banner": "🎏"}


def reel_card(tier: str, item: shop.Item | None, points: int | None = None) -> dict:
    if item is None:
        return {"tier": tier, "icon": "🪙", "name": f"+{points} points" if points else "Points"}
    icon = item.value if item.slot == "badge" else SLOT_ICONS.get(item.slot, "🎁")
    return {"tier": tier, "icon": icon, "name": item.name}


def build_reel(tier: str, item: shop.Item | None, points: int, rng: random.Random) -> list[dict]:
    """REEL_LENGTH cards; the card at REEL_STOP is the real prize."""
    cards = []
    for i in range(REEL_LENGTH):
        if i == REEL_STOP:
            cards.append(reel_card(tier, item, points))
            continue
        t = roll_tier(rng)
        pool = [x for x in shop.CATALOGUE if x.loot_tier == t]
        cards.append(reel_card(t, rng.choice(pool) if pool else None))
    return cards
