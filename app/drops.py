"""Biscuit drops: validation and timeline bucketing. Pure functions with no Flask or SQL.

A drop's place on the timeline comes only from its dates relative to `today`:
  gone     ends_on < today
  soon     starts_on > today                 (sorted soonest first)
  tbc      no dates at all                   ("rumoured")
  now      everything else (on shelves); `last_chance` if it ends within LAST_CHANCE_DAYS
"""
from __future__ import annotations

from datetime import date
from urllib.parse import urlsplit

KINDS = {
    "limited": "⏳ Limited edition",
    "seasonal": "🎄 Seasonal",
    "new": "✨ New release",
    "returning": "🔁 Back again",
}
LAST_CHANCE_DAYS = 14
NAME_MAX, TEXT_MAX, NOTES_MAX = 80, 120, 300


class DropError(ValueError):
    """Validation problem; the message is shown to the user."""


def _date(raw: str, label: str) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as e:
        raise DropError(f"{label} isn't a valid date.") from e


def clean(form) -> dict:
    """Form -> values for db.add_drop/update_drop. Raises DropError."""
    name = (form.get("name") or "").strip()[:NAME_MAX]
    if not name:
        raise DropError("A drop needs a biscuit name.")
    kind = form.get("kind") or "limited"
    if kind not in KINDS:
        kind = "limited"
    starts = _date(form.get("starts_on"), "Start date")
    ends = _date(form.get("ends_on"), "End date")
    if starts and ends and ends < starts:
        raise DropError("The end date is before the start date.")
    url = (form.get("source_url") or "").strip()[:500]
    # Rendered as a link, so only http(s): a "javascript:" URL would run script when clicked.
    if url and urlsplit(url).scheme not in ("http", "https"):
        raise DropError("The source link must start with http:// or https://")
    raw_link = str(form.get("biscuit_id") or "").strip()
    return {
        "name": name,
        "brand": (form.get("brand") or "").strip()[:TEXT_MAX],
        "kind": kind,
        "starts_on": starts,
        "ends_on": ends,
        "shops": (form.get("shops") or "").strip()[:TEXT_MAX],
        "source_url": url,
        "notes": (form.get("notes") or "").strip()[:NOTES_MAX],
        # Explicit "this drop IS that specimen" link. The view checks the id exists.
        "biscuit_id": int(raw_link) if raw_link.isdigit() else None,
    }


def auto_link(drop, logged) -> int | None:
    """Best-guess specimen for a drop with no explicit link, so the same biscuit isn't shown twice.

    Matches when every word of a specimen's name appears in the drop's name (after normalising),
    and the specimen name has 2+ words: "Gingerbread Digestive" matches "Gingerbread Flavour Milk
    Chocolate Digestives", but a bare "Digestive" won't swallow every digestive drop.
    """
    from .similarity import normalise
    drop_words = set(normalise(drop["name"]).split())
    best = None
    for b in logged:
        words = set(normalise(b["name"]).split())
        if len(words) >= 2 and words <= drop_words:
            if best is None or len(words) > best[0]:
                best = (len(words), b["id"])
    return best[1] if best else None


def _days(iso: str | None, today: date) -> int | None:
    return None if iso is None else (date.fromisoformat(iso) - today).days


def countdown(drop, today: date) -> str:
    start, end = _days(drop["starts_on"], today), _days(drop["ends_on"], today)
    if end is not None and end < 0:
        return f"gone {-end} day{'s' if end != -1 else ''} ago"
    if start is not None and start > 0:
        return "lands tomorrow" if start == 1 else f"lands in {start} days"
    if end is not None:
        return "last day today!" if end == 0 else f"{end} day{'s' if end != 1 else ''} left"
    if start is not None:
        return "out now" if start == 0 else f"out for {-start} day{'s' if start != -1 else ''}"
    return "date TBC"


def timeline(drops, today: date) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"last_chance": [], "now": [], "soon": [], "tbc": [], "gone": []}
    for d in drops:
        item = {**dict(d), "countdown": countdown(d, today)}
        start, end = _days(d["starts_on"], today), _days(d["ends_on"], today)
        if end is not None and end < 0:
            out["gone"].append(item)
        elif start is not None and start > 0:
            out["soon"].append(item)
        elif start is None and end is None:
            out["tbc"].append(item)
        elif end is not None and end <= LAST_CHANCE_DAYS:
            out["last_chance"].append(item)
        else:
            out["now"].append(item)
    out["soon"].sort(key=lambda d: d["starts_on"])
    out["last_chance"].sort(key=lambda d: d["ends_on"])
    out["gone"].sort(key=lambda d: d["ends_on"], reverse=True)
    return out
