"""Biscuit tags and origin (suggestions #1 and #3, schema v11). Pure: no Flask, no SQL.

Rarity (app/rarity.py) stays the team's vote on *how rare*. Tags say *what kind*: any agent can
toggle them, like adding a missing photo. Tag keys are stored in `biscuit_tags.tag`, so treat
them as permanent; labels and icons can change freely.

"Foreign" isn't a tag anyone sets. It's shown whenever the origin is outside the UK, so the
flag and the label can never disagree.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tag:
    key: str
    icon: str
    label: str
    blurb: str


TAGS = (
    Tag("limited", "🎟️", "Limited edition", "Here for a short time only. Get it while you can."),
    Tag("seasonal", "🎄", "Seasonal", "Comes back at the same time every year."),
    Tag("own_brand", "🏷️", "Own brand", "A supermarket's own label."),
)
BY_KEY = {t.key: t for t in TAGS}
FOREIGN = Tag("foreign", "🌍", "Foreign", "From outside the UK.")
HOME = "GB"

# ISO 3166-1 alpha-2 -> name. Countries a biscuit is likely to come from; extend freely
# (codes are what's stored, so never change an existing code).
COUNTRIES = {
    "GB": "United Kingdom", "IE": "Ireland",
    "AR": "Argentina", "AU": "Australia", "AT": "Austria", "BE": "Belgium", "BR": "Brazil",
    "BG": "Bulgaria", "CA": "Canada", "CN": "China", "HR": "Croatia", "CZ": "Czechia",
    "DK": "Denmark", "EG": "Egypt", "EE": "Estonia", "FI": "Finland", "FR": "France",
    "DE": "Germany", "GR": "Greece", "HK": "Hong Kong", "HU": "Hungary", "IS": "Iceland",
    "IN": "India", "ID": "Indonesia", "IR": "Iran", "IL": "Israel", "IT": "Italy",
    "JM": "Jamaica", "JP": "Japan", "KE": "Kenya", "LV": "Latvia", "LB": "Lebanon",
    "LT": "Lithuania", "MY": "Malaysia", "MX": "Mexico", "MA": "Morocco", "NL": "Netherlands",
    "NZ": "New Zealand", "NG": "Nigeria", "NO": "Norway", "PK": "Pakistan", "PH": "Philippines",
    "PL": "Poland", "PT": "Portugal", "RO": "Romania", "SA": "Saudi Arabia", "RS": "Serbia",
    "SG": "Singapore", "ZA": "South Africa", "KR": "South Korea", "ES": "Spain", "LK": "Sri Lanka",
    "SE": "Sweden", "CH": "Switzerland", "TW": "Taiwan", "TH": "Thailand", "TR": "Turkey",
    "UA": "Ukraine", "AE": "United Arab Emirates", "US": "United States", "VN": "Vietnam",
}


def flag(code: str | None) -> str:
    """'FR' -> 🇫🇷: each letter becomes its regional-indicator symbol. '' for unknown codes."""
    if not code or code not in COUNTRIES:
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code)


def clean_origin(code: str | None) -> str | None:
    code = (code or "").strip().upper()
    return code if code in COUNTRIES else None


def clean_tags(keys) -> list[str]:
    """Known tag keys only, in catalogue order, no duplicates."""
    wanted = set(keys)
    return [t.key for t in TAGS if t.key in wanted]


def chips(origin: str | None, tag_keys) -> list[dict]:
    """What to show on a card or dossier: the flag first, then Foreign, then the set tags."""
    out = []
    if origin in COUNTRIES:
        out.append({"icon": flag(origin), "label": COUNTRIES[origin], "key": "origin"})
        if origin != HOME:
            out.append({"icon": FOREIGN.icon, "label": FOREIGN.label, "key": FOREIGN.key})
    out += [{"icon": BY_KEY[k].icon, "label": BY_KEY[k].label, "key": k} for k in clean_tags(tag_keys)]
    return out


def country_choices() -> list[tuple[str, str]]:
    """For the picker: the UK first, then A-Z by name."""
    rest = sorted(((c, n) for c, n in COUNTRIES.items() if c != HOME), key=lambda x: x[1])
    return [(HOME, COUNTRIES[HOME])] + rest
