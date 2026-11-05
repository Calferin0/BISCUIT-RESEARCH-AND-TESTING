"""'You might like': picks from what's on file, plus scouting for biscuits nobody has logged yet.

Blind rating (D10) holds: tasting picks are weighted by the viewer's *own* ratings and by how many
reports exist (popularity), never by other people's scores. Scouting uses team-level *brand*
preferences only. No individual biscuit's score can be inferred from it.
"""
from __future__ import annotations

import random
import re
import threading
import time
from collections import defaultdict
from statistics import mean
from urllib.parse import urlencode

from . import images, similarity

LIKED_AT = 3.5            # a biscuit you rated >= this makes its brand "one you like"
DEFAULT_BRANDS = ("McVitie's", "Fox's", "Tunnock's", "Lotus", "Maryland")  # well-known UK brands, for a cold start
UK_BISCUITS = 'categories_tags:"en:biscuits" AND countries_tags:"en:united-kingdom"'
CACHE_TTL_S = 6 * 3600     # be polite to Open Food Facts: one query per brand per 6 h

_cache: dict[str, tuple[float, list]] = {}
_cache_lock = threading.Lock()


def _norm_brand(brand: str) -> str:
    return similarity.normalise(brand or "")


def _weighted_sample(items: list, weights: list[float], k: int, rng: random.Random) -> list:
    """k picks without replacement, each draw proportional to weight."""
    items, weights, out = list(items), list(weights), []
    while items and len(out) < k:
        i = rng.choices(range(len(items)), weights=weights)[0]
        out.append(items.pop(i))
        weights.pop(i)
    return out


def next_tastings(biscuits, my_overalls: dict[int, float], rng: random.Random, k: int = 3) -> list[dict]:
    """Logged biscuits the viewer hasn't rated, nudged towards brands they've liked."""
    rated = {b["id"]: b for b in biscuits if b["id"] in my_overalls}
    liked = {_norm_brand(b["brand"]) for bid, b in rated.items()
             if b["brand"] and my_overalls[bid] >= LIKED_AT}
    candidates = [b for b in biscuits if b["id"] not in my_overalls]
    weights, reasons = [], {}
    for b in candidates:
        brand_hit = bool(b["brand"]) and _norm_brand(b["brand"]) in liked
        weights.append(1 + (3 if brand_hit else 0) + 0.4 * min(b["n"], 5))
        if brand_hit:
            reasons[b["id"]] = f"You've liked {b['brand']} before"
        elif b["n"] >= 3:
            reasons[b["id"]] = f"{b['n']} agents have already filed. Don't get left behind"
        elif b["n"] == 0:
            reasons[b["id"]] = "Untouched. Be the first to taste it"
        else:
            reasons[b["id"]] = "Wildcard pick"
    picks = _weighted_sample(candidates, weights, k, rng)
    return [{**dict(b), "reason": reasons[b["id"]]} for b in picks]


def team_brands(ranked, k: int = 3) -> list[str]:
    """Brands with the best average across the team's biscuits (brand-level only)."""
    by_brand: dict[str, list[float]] = defaultdict(list)
    display: dict[str, str] = {}
    for b in ranked:
        if b["brand"] and b["overall"] is not None:
            key = _norm_brand(b["brand"])
            by_brand[key].append(b["overall"])
            display.setdefault(key, b["brand"])
    best = sorted(by_brand, key=lambda key: mean(by_brand[key]), reverse=True)[:k]
    return [display[key] for key in best] or list(DEFAULT_BRANDS[:k])


def brand_tags(brand: str) -> list[str]:
    """Open Food Facts brand tags for a brand name: 'McVitie's' -> ['mcvitie-s', 'mcvities'].
    Output is [a-z0-9-] only, so it can't break out of the quoted query."""
    b = brand.lower().strip()
    squashed = re.sub(r"[^a-z0-9]+", "-", re.sub(r"[’']", "", b)).strip("-")
    hyphened = re.sub(r"[^a-z0-9]+", "-", b).strip("-")
    return sorted({squashed, hyphened} - {""})


def _off_search(query: str, page: int = 1) -> list[dict]:
    url = f"{images.OFF_SEARCH_URL}?" + urlencode({
        "q": query, "page_size": 24, "page": page,
        "fields": "product_name,brands,image_front_small_url,image_front_url",
    })
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(url)
        if hit and hit[0] > now:
            return hit[1]
    body = images.get_json(url)
    hits = [h for h in (body.get("hits") or []) if images.is_off_image_url(h.get("image_front_url") or "")
            and (h.get("product_name") or "").strip()]
    with _cache_lock:
        _cache[url] = (now + CACHE_TTL_S, hits)
    return hits


def scouting(brands: list[str], logged, rng: random.Random, k: int = 4) -> list[dict]:
    """UK biscuits from Open Food Facts that aren't on file yet. Raises images.PhotoError if offline."""
    pool: list[dict] = []
    for brand in brands:
        tags = brand_tags(brand)
        if not tags:
            continue
        either = " OR ".join(f'brands_tags:"{t}"' for t in tags)
        for h in _off_search(f"({either}) AND {UK_BISCUITS}"):
            pool.append({**h, "reason": f"The team rates {brand} highly"})
    # A dash of pure chance: a random page of all UK biscuits.
    for h in _off_search(UK_BISCUITS, page=rng.randint(1, 30)):
        pool.append({**h, "reason": "Pure scouting luck"})

    seen: set[str] = set()
    fresh: list[dict] = []
    for h in pool:
        name = h["product_name"].strip()
        brand = (h.get("brands") or [""])[0] if isinstance(h.get("brands"), list) else (h.get("brands") or "")
        key = similarity.normalise(name)
        if key in seen or similarity.find_matches(name, "", logged):
            continue  # already logged (or a near-duplicate of something that is)
        seen.add(key)
        fresh.append({"name": name, "brand": brand.split(",")[0].strip(), "image": h["image_front_url"],
                      "thumb": h.get("image_front_small_url") or h["image_front_url"], "reason": h["reason"]})
    rng.shuffle(fresh)
    return fresh[:k]


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
