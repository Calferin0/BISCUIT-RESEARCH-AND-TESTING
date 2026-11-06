"""Control-room feature switches. Stored in the `settings` table as 'feature.<key>' = '1' / '0'.

Off means: gone from the nav and dashboard, and its pages answer with a friendly "switched off"
page. Data is untouched, so switching back on restores everything exactly as it was.
"""
from __future__ import annotations

import functools

from flask import g, render_template

from . import db

FEATURES = {
    "radar": ("🛰️", "Biscuit Radar", "Shops, prices, cheapest finds"),
    "vs": ("⚔️", "Biscuit VS", "Duels and wagers"),
    "loot": ("🎁", "Mystery Tins", "Lootboxes"),
    "shop": ("🛍️", "Biscuit Shop", "Buying cosmetics with points"),
    "dunk": ("⏱️", "Dunk-O-Meter", "Dunk timing and Hall of Fame"),
    "horoscope": ("🔮", "Daily horoscope", "Biscuit of the Day + horoscope on the dashboard"),
    "estop": ("🛑", "E-STOP button", "The work-mode panic button"),
}


def enabled_map() -> dict[str, bool]:
    """All switches for this request (cached on g). Missing = on."""
    if "features" not in g:
        settings = db.get_settings()
        g.features = {k: settings.get(f"feature.{k}", "1") == "1" for k in FEATURES}
    return g.features


def enabled(key: str) -> bool:
    return enabled_map().get(key, True)


def required(key: str):
    """Route decorator: 404-style friendly page when the control room has switched it off."""
    def deco(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if not enabled(key):
                icon, label, _ = FEATURES[key]
                return render_template("denied.html", stamp="Switched off",
                                       heading=f"{icon} {label} is closed for now.",
                                       message="The control room has switched this off. Try again later."), 404
            return view(*args, **kwargs)
        return wrapped
    return deco
