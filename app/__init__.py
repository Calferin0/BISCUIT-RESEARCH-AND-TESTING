"""BRT: Biscuit Research & Testing. Flask application factory."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from flask import Flask, g, render_template, request

from . import db, scoring, util
from .presence import Presence


def resolve_data_dir(override: str | os.PathLike | None = None) -> Path:
    """Where the DB, uploads, secret key and logs live (D2: never inside OneDrive)."""
    raw = override or os.environ.get("BRT_DATA_DIR")
    if not raw:
        raw = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "BRT"
    return Path(raw).resolve()


def _load_secret_key(data_dir: Path) -> str:
    """Signs the session cookie that carries flash messages. Persisted so restarts don't drop them."""
    path = data_dir / "secret_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    path.write_text(key, encoding="utf-8")
    return key


def create_app(test_config: dict | None = None) -> Flask:
    cfg = dict(test_config or {})
    data_dir = resolve_data_dir(cfg.pop("DATA_DIR", None))

    # D2: OneDrive syncing a live SQLite file can corrupt it or spawn "conflicted copy" files.
    if "onedrive" in str(data_dir).lower():
        raise RuntimeError(f"Refusing to keep BRT data inside OneDrive ({data_dir}). Set BRT_DATA_DIR elsewhere.")

    (data_dir / "uploads").mkdir(parents=True, exist_ok=True)

    app = Flask(__name__)
    app.config.update(
        DATA_DIR=data_dir,
        DATABASE=data_dir / "brt.sqlite3",
        UPLOAD_DIR=data_dir / "uploads",
        MAX_CONTENT_LENGTH=12 * 1024 * 1024,  # phone photos are typically 3-8 MB
        PUBLIC_HOST=os.environ.get("BRT_PUBLIC_HOST"),
        SECRET_KEY=_load_secret_key(data_dir),
    )
    app.config.update(cfg)

    db.init_app(app)
    app.extensions["brt_presence"] = Presence()  # one per app, so each test gets a fresh one

    from .admin import bp as admin_bp
    from .views import bp as views_bp
    app.register_blueprint(views_bp)
    app.register_blueprint(admin_bp)

    @app.before_request
    def load_agent() -> None:
        g.member = None
        if request.endpoint == "static":
            return
        token = request.cookies.get(util.AGENT_COOKIE)
        if token:
            g.member = db.member_by_token(token)

    @app.context_processor
    def inject_globals() -> dict:
        return {
            "me": g.get("member"),
            "CATEGORIES": scoring.CATEGORIES,
            "PURIST_FIELD": scoring.PURIST_FIELD,
            "PURIST_LABEL": scoring.PURIST_LABEL,
            "PURIST_PITCH": scoring.PURIST_PITCH,
            "is_purist": scoring.is_purist,
            "verdict": scoring.verdict,
            "product": util.random_product_image(),
            "work_shots": util.work_screenshots(),
        }

    def denied(code: int, stamp: str, heading: str, message: str):
        return render_template("denied.html", stamp=stamp, heading=heading, message=message), code

    @app.errorhandler(403)
    def forbidden(_e):
        return denied(403, "Access denied", "Clearance insufficient.",
                      "This area is restricted to the BRT control room.")

    @app.errorhandler(404)
    def not_found(_e):
        return denied(404, "Redacted", "Nothing on file.",
                      "That page, biscuit or agent link doesn't exist (or has been retired).")

    @app.errorhandler(413)
    def too_large(_e):
        return denied(413, "Too heavy", "Evidence photo too large.",
                      "Keep photos under 12 MB. Try a lower camera resolution.")

    return app
