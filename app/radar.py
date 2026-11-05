"""Biscuit Radar: shops around the office, plotted by distance and bearing, with team prices.

Data sources (both free, no API key):
  * postcodes.io: UK postcode -> lat/lng (radar centre, and shops added by postcode)
  * OpenStreetMap Overpass API: supermarkets and convenience stores within IMPORT_RADIUS_M.
    © OpenStreetMap contributors (ODbL), credited on the page.
Prices are team-entered: there is no public UK biscuit-price feed.

The centre lives in DATA_DIR/site.json, NOT in the repo: the repo is public and the centre is
where everyone using the app works.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from urllib.parse import quote, urlencode

from . import images

RINGS_KM = (1, 2, 3, 5)
RADAR_KM = RINGS_KM[-1]
IMPORT_RADIUS_M = 5000
OVERPASS_TIMEOUT_S = 45
OVERPASS_ENDPOINTS = (  # public instances, tried in order
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",   # main one again: "at capacity" is often momentary
)
WALK_MIN_PER_KM = 12
POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$")


class RadarError(ValueError):
    """Shown to the user as-is."""


# --- site config (radar centre) -------------------------------------------------------

def _site_file(data_dir: Path) -> Path:
    return Path(data_dir) / "site.json"


def load_site(data_dir: Path) -> dict | None:
    try:
        site = json.loads(_site_file(data_dir).read_text(encoding="utf-8"))
        return site if {"lat", "lng"} <= site.keys() else None
    except (OSError, ValueError):
        return None


def save_site(data_dir: Path, label: str, lat: float, lng: float, postcode: str) -> None:
    _site_file(data_dir).write_text(json.dumps(
        {"label": label, "lat": lat, "lng": lng, "postcode": postcode}, indent=2), encoding="utf-8")


# --- lookups -----------------------------------------------------------------------------

def normalise_postcode(raw: str) -> str:
    pc = re.sub(r"\s+", "", (raw or "").upper())
    if not POSTCODE_RE.match(pc):
        raise RadarError("That doesn't look like a UK postcode.")
    return f"{pc[:-3]} {pc[-3:]}"


def postcode_lookup(postcode: str) -> tuple[float, float]:
    pc = normalise_postcode(postcode)
    try:
        body = images.get_json("https://api.postcodes.io/postcodes/" + quote(pc.replace(" ", "")))
    except images.PhotoError as e:
        raise RadarError("Couldn't look that postcode up. Check it, or try again in a minute.") from e
    result = (body or {}).get("result") or {}
    if "latitude" not in result:
        raise RadarError("Postcode not found.")
    return float(result["latitude"]), float(result["longitude"])


def overpass_shops(lat: float, lng: float, radius_m: int = IMPORT_RADIUS_M) -> list[dict]:
    """Supermarkets and convenience stores near (lat, lng) from OpenStreetMap."""
    query = (f'[out:json][timeout:25];('
             f'node["shop"~"^(supermarket|convenience)$"](around:{int(radius_m)},{lat},{lng});'
             f'way["shop"~"^(supermarket|convenience)$"](around:{int(radius_m)},{lat},{lng}););'
             f'out center tags;')
    # Overpass routinely takes 10-30 s and the main public server is often "at capacity" (502),
    # both seen 2026-11-05 [MEASURED]. So: a long timeout, and fall through to public mirrors.
    # This is an occasional admin action, so waiting is fine.
    body, last_error = None, None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            body = images.get_json(f"{endpoint}?" + urlencode({"data": query}), timeout=OVERPASS_TIMEOUT_S)
            break
        except images.PhotoError as e:
            last_error = e
    if body is None:
        raise RadarError("OpenStreetMap's servers are busy. Try the import again in a few minutes.") from last_error
    out = []
    for el in (body or {}).get("elements", []):
        tags = el.get("tags") or {}
        point = el if el.get("type") == "node" else el.get("center") or {}
        if not tags.get("name") or "lat" not in point:
            continue
        out.append({"osm_ref": f"{el['type']}/{el['id']}", "name": tags["name"][:80],
                    "brand": (tags.get("brand") or "")[:80], "kind": tags.get("shop", ""),
                    "lat": float(point["lat"]), "lng": float(point["lon"]),
                    "postcode": (tags.get("addr:postcode") or "")[:10]})
    return out


# --- geometry ----------------------------------------------------------------------------

def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle (haversine) distance. Plenty accurate at biscuit-run scale."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Initial bearing from point 1 to point 2, 0 = north, clockwise."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def radar_xy(km: float, bearing: float, radius_px: float = 140.0) -> tuple[float, float]:
    """Polar -> SVG coords with the centre at (0, 0), north up, clamped to the outer ring."""
    r = min(km, RADAR_KM) / RADAR_KM * radius_px
    t = math.radians(bearing)
    return round(r * math.sin(t), 1), round(-r * math.cos(t), 1)


def maps_url(lat: float, lng: float) -> str:
    return "https://www.google.com/maps/search/?api=1&" + urlencode({"query": f"{lat:.6f},{lng:.6f}"})


# --- prices ------------------------------------------------------------------------------

def parse_price(raw: str) -> int:
    """'£1.20', '1.2', '120p', '1' -> pence. Raises RadarError."""
    s = (raw or "").strip().lower().replace("£", "").replace(",", ".").replace(" ", "")
    try:
        pence = int(s[:-1]) if s.endswith("p") else round(float(s) * 100)
    except ValueError as e:
        raise RadarError("Price should look like £1.20 or 120p.") from e
    if not 1 <= pence <= 10_000:
        raise RadarError("That price looks wrong (between 1p and £100, please).")
    return pence


def fmt_price(pence: int) -> str:
    return f"{pence}p" if pence < 100 else f"£{pence / 100:.2f}"
