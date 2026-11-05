"""Small helpers that don't belong to a route: networking, QR codes, product images, CSV safety."""
from __future__ import annotations

import random
import socket
from pathlib import Path

import segno
from flask import current_app, request, url_for

AGENT_COOKIE = "brt_agent"
IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "gif"}  # no SVG: it can carry script


def lan_ip() -> str:
    """Best guess at this PC's LAN address.

    A UDP connect() sends no packets. It only asks the OS which interface it would route
    through. On a VPN this may return the VPN adapter, so set BRT_PUBLIC_HOST to override.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def public_base_url() -> str:
    """URL teammates' phones should use. Not request.host: the admin page is viewed via
    127.0.0.1, which is useless in a QR code. The IP is looked up live because DHCP can move it."""
    host = current_app.config.get("PUBLIC_HOST") or lan_ip()
    port = request.environ.get("SERVER_PORT", "8080")
    return f"http://{host}:{port}"


def qr_data_uri(url: str) -> str:
    return segno.make(url, error="m").svg_data_uri(scale=4, border=2, dark="#1b1712", light="#fdf6e3")


def random_product_image() -> dict | None:
    """A random Motion Impossible product shot from static/img/products/ (supplied by CF)."""
    files = list_images(Path(current_app.static_folder) / "img" / "products")
    if not files:
        return None
    pick = random.choice(files)
    return {
        "url": url_for("static", filename=f"img/products/{pick.name}"),
        "caption": pick.stem.replace("_", " ").replace("-", " "),
    }


def list_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower().lstrip(".") in IMAGE_EXTS)


def work_screenshots() -> list[str]:
    """URLs of the fake 'work' screens for the E-STOP button, from static/img/work/ (CF's own)."""
    return [url_for("static", filename=f"img/work/{p.name}")
            for p in list_images(Path(current_app.static_folder) / "img" / "work")]


def csv_safe(value: object) -> object:
    """Neutralise CSV formula injection: Excel executes cells starting with = + - @."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value
