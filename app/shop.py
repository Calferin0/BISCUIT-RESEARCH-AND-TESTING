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
    loot_tier: str | None = None  # set = lootbox-only (can't be bought); value is its rarity tier


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
    # ---- lootbox exclusives (cost 0: you can only get them from a Mystery Tin) ----
    Item("loot-title-crumb-collector", "title", "Crumb Collector", 0, "Crumb Collector",
         "Hoovers up the bits nobody else wants.", "uncommon"),
    Item("loot-color-oat", "color", "Hobnob Oat", 0, "oat", "Rustic. Wholesome. Slightly crunchy.", "uncommon"),
    Item("loot-frame-tea-ring", "frame", "Tea Ring", 0, "teering", "The mug stain of honour.", "uncommon"),
    Item("loot-title-dunk-whisperer", "title", "Dunk Whisperer", 0, "Dunk Whisperer",
         "Knows the exact second before collapse.", "rare"),
    Item("loot-color-wafer", "color", "Pink Wafer", 0, "wafer", "Nobody's favourite. Everybody's nostalgia.", "rare"),
    Item("loot-frame-doily", "frame", "Grandma's Doily", 0, "doily", "Lace. Respectability. Crumbs.", "rare"),
    Item("loot-title-last-biscuit", "title", "Keeper of the Last Biscuit", 0, "Keeper of the Last Biscuit",
         "Has never once taken it. Probably.", "epic"),
    Item("loot-color-galaxy", "color", "Galaxy Chocolate", 0, "galaxy", "A whole universe of smooth.", "epic"),
    Item("loot-frame-foil", "frame", "Gold Foil Wrapper", 0, "foil", "Crinkly, shiny, and very hard to open.", "epic"),
    Item("loot-title-oracle", "title", "The Biscuit Oracle", 0, "the Biscuit Oracle",
         "Foresaw the Jaffa Cake debate before it began.", "legendary"),
    Item("loot-color-caramel", "color", "Molten Caramel", 0, "caramel", "Animated. Gooey. Legendary.", "legendary"),
    Item("loot-frame-holo-tin", "frame", "Holographic Tin", 0, "holotin", "The tin at the back of the cupboard. It glows.", "legendary"),
)

BY_KEY: dict[str, Item] = {i.key: i for i in CATALOGUE}
FOR_SALE = tuple(i for i in CATALOGUE if i.loot_tier is None)


def flair_for(equipped_keys) -> dict:
    """Equipped item keys -> {'title': str|None, 'color': css|None, 'frame': css|None}."""
    out = {"title": None, "color": None, "frame": None}
    for key in equipped_keys:
        item = BY_KEY.get(key)
        if item:
            out[item.slot] = item.value
    return out
