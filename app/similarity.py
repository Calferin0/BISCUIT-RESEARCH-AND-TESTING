"""Fuzzy biscuit-name matching, so the team doesn't log "Hobnobs" three times.

Two tiers:
- exact: same name after normalising (case, punctuation, plurals, filler words) and a
  compatible brand. Blocked outright.
- similar: close enough to be suspicious. The agent must confirm "mine is different".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

STOPWORDS = {"the", "a", "an", "biscuit", "biscuits", "cookie", "cookies", "original", "classic"}
SIMILAR_AT = 0.75
SUBSET_SCORE = 0.85  # "Hobnob" vs "Chocolate Hobnob": worth asking about, not proof


def normalise(text: str) -> str:
    t = text.lower().replace("&", " and ").replace("'", "").replace("’", "")
    tokens = re.findall(r"[a-z0-9]+", t)
    out = []
    for tok in tokens:
        if tok in STOPWORDS:
            continue
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]  # crude plural strip: hobnobs -> hobnob, creams -> cream
        out.append(tok)
    return " ".join(out or tokens)


def score(a: str, b: str) -> float:
    """Similarity in [0, 1] between two *normalised* names."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = set(a.split()), set(b.split())
    subset = SUBSET_SCORE if (ta <= tb or tb <= ta) else 0.0
    jaccard = len(ta & tb) / len(ta | tb)
    typo = SequenceMatcher(None, a, b).ratio()  # catches "hobnob" vs "hobknob"
    return max(subset, jaccard, typo)


@dataclass(frozen=True)
class Match:
    id: int
    name: str
    brand: str
    score: float
    exact: bool


def find_matches(name: str, brand: str, candidates, limit: int = 5) -> list[Match]:
    """candidates: rows with id, name, brand. Returns likely duplicates, exact ones first."""
    n, b = normalise(name), normalise(brand) if brand else ""
    out = []
    for c in candidates:
        s = score(n, normalise(c["name"]))
        if s < SIMILAR_AT:
            continue
        cb = normalise(c["brand"]) if c["brand"] else ""
        # Same name but clearly different brands (McVitie's vs own-brand) is a different specimen.
        exact = s == 1.0 and (not b or not cb or b == cb)
        out.append(Match(c["id"], c["name"], c["brand"], round(s, 2), exact))
    out.sort(key=lambda m: (not m.exact, -m.score, m.name))
    return out[:limit]
