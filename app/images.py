"""Biscuit photos: validation, storage, duplicate detection and Open Food Facts search.

Every photo, whether uploaded, picked from Open Food Facts or pasted as a URL by the admin,
goes through attach_photo(): read bytes -> check magic bytes -> sha256 -> reject if another
biscuit already has that exact photo -> save under a random name. A local copy is stored, so
the app never hot-links and keeps working if the source disappears.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from flask import current_app

from . import db

USER_AGENT = "BRT-biscuit-rating/1.0 (internal office app)"  # Open Food Facts asks for a named UA
OFF_SEARCH_URL = "https://search.openfoodfacts.org/search"
OFF_LEGACY_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
OFF_IMAGE_HOST = "images.openfoodfacts.org"
OFF_SOURCE = "Open Food Facts"
MAX_DOWNLOAD = 8 * 1024 * 1024
TIMEOUT_S = 10
MAX_RESULTS = 12


class PhotoError(Exception):
    """A problem with a photo. The message is shown to the user as-is."""


def sniff(data: bytes) -> str | None:
    """Image type from magic bytes. Never trust the file extension: it's just part of a name."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def inspect(data: bytes) -> tuple[str, str]:
    ext = sniff(data)
    if ext is None:
        raise PhotoError("That file isn't a JPG, PNG, WEBP or GIF image.")
    return ext, hashlib.sha256(data).hexdigest()


def save(data: bytes, ext: str, upload_dir: Path) -> str:
    name = f"{uuid.uuid4().hex}.{ext}"
    (Path(upload_dir) / name).write_bytes(data)
    return name


def _http_get(url: str, timeout: float = TIMEOUT_S) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read(MAX_DOWNLOAD + 1)  # bounded read: never trust Content-Length
    except HTTPError as e:
        # Reached the site but it said no: 429/503 mean "busy" (OFF rate-limits search).
        if e.code in (429, 502, 503, 504):
            raise PhotoError("That site is busy right now. Try again in a moment.") from e
        raise PhotoError(f"That site refused the request (HTTP {e.code}).") from e
    except (URLError, TimeoutError, OSError, ValueError) as e:
        raise PhotoError("Couldn't fetch that from the web. Is this PC online?") from e
    if len(data) > MAX_DOWNLOAD:
        raise PhotoError("That image is over 8 MB.")
    return data


def get_json(url: str, timeout: float = TIMEOUT_S):
    """GET + JSON decode with the same UA and size limits as image fetches."""
    try:
        return json.loads(_http_get(url, timeout))
    except ValueError as e:
        raise PhotoError("That site sent back something unexpected.") from e


def fetch_image(url: str) -> bytes:
    if urlsplit(url).scheme not in ("http", "https"):
        raise PhotoError("Image links must start with http:// or https://")
    return _http_get(url)


def is_off_image_url(url: str) -> bool:
    p = urlsplit(url)
    return p.scheme == "https" and p.hostname == OFF_IMAGE_HOST


def _off_search_urls(query: str) -> list[str]:
    fields = "product_name,brands,image_front_small_url,image_front_url"
    return [
        # Primary: OFF's dedicated search service. Fast and stable when tested 2026-11-05 [BENCH].
        f"{OFF_SEARCH_URL}?" + urlencode({"q": query, "page_size": 30, "fields": fields}),
        # Fallback: the legacy endpoint. It works but intermittently returns 503 "temporarily
        # unavailable" (seen 2026-11-05 [BENCH]).
        f"{OFF_LEGACY_SEARCH_URL}?" + urlencode({
            "search_terms": query, "search_simple": 1, "action": "process", "json": 1,
            "page_size": 30, "fields": fields,
        }),
    ]


def _brand(raw) -> str:
    # The new API returns brands as a list; the legacy one as a comma-separated string.
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    return (raw or "").split(",")[0].strip()


def search_off(query: str) -> list[dict]:
    """Search Open Food Facts for pack shots. Runs on the server, so phones only load thumbnails."""
    products = None
    last_error: PhotoError | None = None
    for url in _off_search_urls(query):
        try:
            body = json.loads(_http_get(url))
            products = body.get("hits", body.get("products"))
        except PhotoError as e:
            last_error = e
            continue
        except (ValueError, AttributeError):
            continue
        if isinstance(products, list):
            break
    if not isinstance(products, list):
        raise last_error or PhotoError("Open Food Facts sent back something unexpected. Try again in a minute.")

    seen: set[str] = set()
    out: list[dict] = []
    for p in products:
        image = p.get("image_front_url") or ""
        if not is_off_image_url(image) or image in seen:
            continue
        seen.add(image)
        out.append({
            "name": (p.get("product_name") or "").strip(),
            "brand": _brand(p.get("brands")),
            "image": image,
            "thumb": p.get("image_front_small_url") or image,
        })
        if len(out) >= MAX_RESULTS:
            break
    return out


def search_json(query: str) -> tuple[dict, int]:
    """JSON body + status for the image-search API endpoints."""
    query = query.strip()[:80]
    if len(query) < 2:
        return {"results": []}, 200
    try:
        return {"results": search_off(query)}, 200
    except PhotoError as e:
        return {"error": str(e)}, 502


def _photo_bytes(form, files, allow_any_url: bool) -> tuple[bytes, str] | None:
    """Which photo did the form send? Priority: uploaded file > Open Food Facts pick > pasted URL."""
    upload = files.get("photo")
    if upload and upload.filename:
        return upload.read(), "upload"
    web = form.get("web_image", "").strip()
    if web:
        # Agents can only pick Open Food Facts images. Otherwise any phone on the LAN could make
        # this PC fetch arbitrary URLs (server-side request forgery, SSRF).
        if not is_off_image_url(web):
            raise PhotoError("Web photos must come from the Open Food Facts search.")
        return fetch_image(web), OFF_SOURCE
    pasted = form.get("image_url", "").strip()
    if pasted:
        if not allow_any_url:
            raise PhotoError("Only the control room can paste image links.")
        return fetch_image(pasted), pasted
    return None


def attach_photo(form, files, *, allow_any_url: bool = False,
                 exclude_biscuit: int | None = None) -> tuple[str, str, str] | None:
    """Validate, de-duplicate and store the photo in a request.

    Returns (filename, sha256, source), or None if the form had no photo. Raises PhotoError.
    """
    got = _photo_bytes(form, files, allow_any_url)
    if got is None:
        return None
    data, source = got
    ext, digest = inspect(data)
    clash = db.biscuit_with_image_hash(digest, exclude_biscuit)
    if clash is not None:
        raise PhotoError(f"That exact photo is already on file for “{clash['name']}”.")
    return save(data, ext, current_app.config["UPLOAD_DIR"]), digest, source
