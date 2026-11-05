"""Rarity tiers, shared by specimens (team-voted) and lootbox drops. Pure, no I/O."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    key: str
    label: str
    icon: str
    blurb: str      # tongue-in-cheek description shown on vote buttons


TIERS: tuple[Tier, ...] = (
    Tier("common", "Common", "⚪", "In every tin in the land."),
    Tier("uncommon", "Uncommon", "🟢", "You'd have to visit a second shop."),
    Tier("rare", "Rare", "🔵", "Spotted in the wild maybe twice a year."),
    Tier("epic", "Epic", "🟣", "People whisper about it in the kitchen."),
    Tier("legendary", "Legendary", "🟠", "Some say it was never real."),
)
BY_KEY = {t.key: t for t in TIERS}
ORDER = {t.key: i for i, t in enumerate(TIERS)}


def decide(votes: list[str], override: str | None = None) -> Tier | None:
    """Displayed tier: admin override, else the most-voted tier (ties go to the RARER tier,
    because 'is it legendary?' arguments are more fun than 'is it common?'). None = no votes."""
    if override in BY_KEY:
        return BY_KEY[override]
    counts = Counter(v for v in votes if v in BY_KEY)
    if not counts:
        return None
    best = max(counts.values())
    return BY_KEY[max((k for k, n in counts.items() if n == best), key=ORDER.get)]
