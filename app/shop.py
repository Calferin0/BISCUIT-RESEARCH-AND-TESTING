"""The Biscuit Shop: cosmetic agent flair bought with Biscuit Points. Catalogue only, no I/O.

Three slots, one item equipped per slot:
  title  shown after your name      ("Agent Abi, Crumb Whisperer")
  color  your name's colour
  frame  a ring around your avatar

Prices are pitched against points.RULES: one report = 10, so a cheap colour costs about 3 reports
and the top items take a few weeks of enthusiastic tasting.
"""
from __future__ import annotations

from dataclasses import dataclass

SLOTS = {"title": "🏷️ Titles", "color": "🎨 Name colours", "frame": "🖼️ Avatar frames"}


@dataclass(frozen=True)
class Item:
    key: str     # stored in purchases/equipped: never rename, old purchases keep the old key
    slot: str
    name: str
    cost: int
    value: str   # title text, or CSS class suffix for colours/frames
    blurb: str


CATALOGUE: tuple[Item, ...] = (
    # titles
    Item("title-dunkinator", "title", "The Dunkinator", 40, "the Dunkinator", "Says it all, really."),
    Item("title-crumb-whisperer", "title", "Crumb Whisperer", 60, "Crumb Whisperer", "Can hear a crumb fall two desks away."),
    Item("title-ginger-ninja", "title", "Ginger Ninja", 50, "Ginger Ninja", "Silent. Deadly. Snappy."),
    Item("title-custodian", "title", "Custodian of the Tin", 90, "Custodian of the Tin", "Nobody touches the tin without your say-so."),
    Item("title-baron", "title", "Biscuit Baron", 150, "Biscuit Baron", "Landed gentry of the snack drawer."),
    # name colours
    Item("color-custard", "color", "Custard Cream", 30, "custard", "Smooth, yellow, reassuring."),
    Item("color-jaffa", "color", "Jaffa Orange", 40, "jaffa", "Tangy. Controversial. Is it even a biscuit?"),
    Item("color-bourbon", "color", "Bourbon Brown", 40, "bourbon", "Deep, dark, sophisticated."),
    Item("color-mint", "color", "After-Dinner Mint", 50, "mint", "Fancy-pants green."),
    Item("color-party", "color", "Party Ring", 120, "party", "Every colour at once. Subtle, it is not."),
    # avatar frames
    Item("frame-gold", "frame", "Gold Seal", 60, "gold", "A ring of pure (painted) gold."),
    Item("frame-stamp", "frame", "Classified Stamp", 80, "stamp", "Red ink. Top secret. Very official."),
    Item("frame-rainbow", "frame", "Rainbow Wafer", 100, "rainbow", "For agents who refuse to blend in."),
    Item("frame-sparkle", "frame", "Sugar Sparkle", 150, "sparkle", "Animated sparkles. Peak luxury."),
)

BY_KEY: dict[str, Item] = {i.key: i for i in CATALOGUE}


def flair_for(equipped_keys) -> dict:
    """Equipped item keys -> {'title': str|None, 'color': css|None, 'frame': css|None}."""
    out = {"title": None, "color": None, "frame": None}
    for key in equipped_keys:
        item = BY_KEY.get(key)
        if item:
            out[item.slot] = item.value
    return out
