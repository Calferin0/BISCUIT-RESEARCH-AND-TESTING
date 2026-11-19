"""The Biscuit Shop: cosmetic agent flair bought with Biscuit Points. Catalogue only, no I/O.

Six slots, one item equipped per slot:
  title   shown after your name      ("Agent Abi, Crumb Whisperer")
  color   your name's colour
  frame   a ring around your avatar
  effect  an animation on your name (glow, wobble, crumbs)
  badge   an emoji pinned after your name (value is the emoji itself)
  banner  the backdrop of your profile and your spot on the Agents catwalk

Prices are pitched against points.RULES: one report = 10, so a cheap colour costs about 3 reports
and the top items take a few weeks of enthusiastic tasting.
"""
from __future__ import annotations

from dataclasses import dataclass

SLOTS = {"title": "🏷️ Titles", "color": "🎨 Name colours", "frame": "🖼️ Avatar frames",
         "effect": "✨ Name effects", "badge": "📛 Badges", "banner": "🎏 Profile banners"}


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
    # ---- 2026-11-19: more of everything, plus three new slots ----
    Item("title-crumb-inspector", "title", "Crumb Inspector", 45, "Crumb Inspector", "Clipboard. Magnifying glass. No mercy."),
    Item("title-tea-sommelier", "title", "Tea Sommelier", 70, "Tea Sommelier", "Notes of malt, with a biscuity finish."),
    Item("title-cdo", "title", "Chief Dunking Officer", 120, "Chief Dunking Officer", "C-suite. Of the kitchen."),
    Item("color-ginger", "color", "Ginger Snap", 45, "ginger", "Warm, spicy, breaks clean."),
    Item("color-lemon", "color", "Lemon Puff", 45, "lemon", "Sharp and sunny."),
    Item("color-fig", "color", "Fig Roll Purple", 55, "fig", "Misunderstood. Magnificent."),
    Item("frame-crumbring", "frame", "Crumb Ring", 70, "crumbring", "A dotted halo of crumbs."),
    Item("frame-neon", "frame", "Neon Tin Sign", 110, "neon", "Buzzes faintly. Open all hours."),
    Item("fx-glow", "effect", "Warm Glow", 70, "glow", "Your name, fresh from the oven."),
    Item("fx-wobble", "effect", "Jelly Wobble", 80, "wobble", "Like a Jaffa Cake's middle bit."),
    Item("fx-bounce", "effect", "Dunk Bob", 90, "bounce", "Your name bobs like a biscuit in tea."),
    Item("fx-crumbs", "effect", "Falling Crumbs", 140, "crumbs", "Leaves a little trail of crumbs everywhere."),
    Item("badge-cookie", "badge", "Cookie Badge", 20, "🍪", "The classic."),
    Item("badge-tea", "badge", "Cuppa Badge", 20, "☕", "Never without one."),
    Item("badge-teapot", "badge", "Teapot Badge", 30, "🫖", "For agents who brew for the whole floor."),
    Item("badge-magnifier", "badge", "Investigator Badge", 40, "🔍", "On the case."),
    Item("badge-fire", "badge", "Hot Streak Badge", 80, "🔥", "Can't stop reviewing."),
    Item("badge-crown", "badge", "Crown Badge", 150, "👑", "Heavy is the head that holds the tin."),
    Item("banner-dossier", "banner", "Classified Dossier", 60, "dossier", "Manila folder, red stamp, very hush-hush."),
    Item("banner-teatime", "banner", "Tea Time", 60, "teatime", "Steam, saucers, a plate of possibilities."),
    Item("banner-factory", "banner", "Biscuit Factory", 90, "factory", "Conveyor belts as far as the eye can see."),
    Item("banner-nightshift", "banner", "Night Shift", 120, "nightshift", "Starry skies over the snack drawer."),
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
    # 2026-11-19 tin restock
    Item("loot-title-tin-rattler", "title", "Tin Rattler", 0, "Tin Rattler", "Heard from three rooms away.", "uncommon"),
    Item("loot-color-malted", "color", "Malted Milk", 0, "malted", "Cows on a biscuit. Calm energy.", "uncommon"),
    Item("loot-badge-milk", "badge", "Milk Dunker Badge", 0, "🥛", "Rebels against tea.", "uncommon"),
    Item("loot-banner-barrel", "banner", "Biscuit Barrel", 0, "barrel", "Grandma's barrel. Always half full.", "uncommon"),
    Item("loot-fx-pulse", "effect", "Heartbeat", 0, "pulse", "Your name gently throbs with biscuit love.", "uncommon"),
    Item("loot-frame-sprinkles", "frame", "Hundreds and Thousands", 0, "sprinkles", "A party-ring rim.", "uncommon"),
    Item("loot-title-agent-crumbs", "title", "Agent of Crumbs", 0, "Agent of Crumbs", "Licensed to nibble.", "rare"),
    Item("loot-color-chocorange", "color", "Chocolate Orange", 0, "chocorange", "Tap it and unwrap it.", "rare"),
    Item("loot-badge-unicorn", "badge", "Unicorn Badge", 0, "🦄", "As rare as a full packet on Friday.", "rare"),
    Item("loot-banner-picnic", "banner", "Picnic Blanket", 0, "picnic", "Gingham, sunshine, wasps.", "rare"),
    Item("loot-fx-shimmer", "effect", "Sugar Shimmer", 0, "shimmer", "A glint runs across your name.", "rare"),
    Item("loot-frame-swirl", "frame", "Custard Swirl", 0, "swirl", "Hypnotic. Creamy.", "rare"),
    Item("loot-title-duke", "title", "Duke of Dunk", 0, "Duke of Dunk", "Owns several mugs. Ceremonial ones.", "epic"),
    Item("loot-badge-ufo", "badge", "UFO Badge", 0, "🛸", "They came for the biscuits.", "epic"),
    Item("loot-banner-midnight", "banner", "Midnight Raid", 0, "midnight", "Torchlight on the cupboard. Shhh.", "epic"),
    Item("loot-fx-rainbow", "effect", "Rainbow Wave", 0, "rainbow", "Every colour, rolling through your name.", "epic"),
    Item("loot-frame-halo", "frame", "Crumb Halo", 0, "halo", "Saintly. Slightly sticky.", "epic"),
    Item("loot-title-last-custard", "title", "The Last Custard Cream", 0, "the Last Custard Cream",
         "Survivor of every team meeting.", "legendary"),
    Item("loot-badge-trophy", "badge", "Golden Tin Badge", 0, "🏆", "Champion of the cupboard.", "legendary"),
    Item("loot-banner-golden", "banner", "Golden Ticket", 0, "golden", "A shimmering gold banner. Wonka who?", "legendary"),
    Item("loot-fx-fire", "effect", "On Fire", 0, "fire", "Your name, actually on fire. Hot from the oven.", "legendary"),
)

BY_KEY: dict[str, Item] = {i.key: i for i in CATALOGUE}
FOR_SALE = tuple(i for i in CATALOGUE if i.loot_tier is None)


def flair_for(equipped_keys) -> dict:
    """Equipped item keys -> {slot: value or None} for every slot in SLOTS."""
    out: dict = {slot: None for slot in SLOTS}
    for key in equipped_keys:
        item = BY_KEY.get(key)
        if item:
            out[item.slot] = item.value
    return out
