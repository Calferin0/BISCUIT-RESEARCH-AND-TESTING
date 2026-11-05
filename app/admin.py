"""Control room: manage agents and biscuits, export data. Loopback-only (D5)."""
from __future__ import annotations

import csv
import io
import random
from datetime import date

from flask import (Blueprint, Response, abort, current_app, flash, redirect, render_template,
                   request, url_for)

from . import db, images, scoring, util

bp = Blueprint("admin", __name__, url_prefix="/admin")

LOOPBACK = {"127.0.0.1", "::1"}
MEMBER_NAME_MAX = 40


@bp.before_request
def loopback_only():
    # Authorisation by network origin: only a browser on the host PC itself gets in.
    # remote_addr is the TCP peer. X-Forwarded-For is deliberately ignored: there's no
    # proxy here, and trusting that header would let any phone claim to be 127.0.0.1.
    if request.remote_addr not in LOOPBACK:
        abort(403)


@bp.get("/")
def index():
    base = util.public_base_url()
    members = []
    for m in db.list_members():
        url = f"{base}/join/{m['token']}"
        members.append({**dict(m), "url": url, "qr": util.qr_data_uri(url) if m["active"] else None})
    return render_template(
        "admin.html", base=base, members=members, avatars=scoring.AVATARS,
        biscuits=db.list_biscuits(None, include_inactive=True),
        live=current_app.extensions["brt_presence"].live(),
        new_suggestions=len(db.list_suggestions(None, ("new",))),
        drops=db.list_drops(include_hidden=True),
    )


@bp.post("/drops/<int:drop_id>/toggle")
def toggle_drop(drop_id: int):
    if db.get_drop(drop_id) is None:
        abort(404)
    db.toggle_drop(drop_id)
    return redirect(url_for("admin.index") + "#drops")


@bp.get("/suggestions")
def suggestions():
    return render_template("admin_suggestions.html", items=db.list_suggestions(None),
                           kinds=db.SUGGESTION_KINDS, statuses=db.SUGGESTION_STATUSES)


@bp.post("/suggestions/<int:suggestion_id>")
def update_suggestion(suggestion_id: int):
    status = request.form.get("status", "")
    if status not in db.SUGGESTION_STATUSES or not db.suggestion_exists(suggestion_id):
        abort(400)
    db.set_suggestion_status(suggestion_id, status, request.form.get("response", "").strip()[:500])
    flash(f"Suggestion #{suggestion_id} updated.", "info")
    return redirect(url_for("admin.suggestions") + f"#s{suggestion_id}")


@bp.get("/api/live")
def api_live():
    """Who's on BRT now. Polled by the admin page's 'Live now' panel."""
    agents = current_app.extensions["brt_presence"].live()
    return {"count": len(agents), "editing": sum(a["editing"] for a in agents), "agents": agents}


@bp.get("/live-count")
def live_count():
    """Plain-text number of live agents, for stop-brt.bat (batch files can't parse JSON)."""
    return str(len(current_app.extensions["brt_presence"].live())), 200, {"Content-Type": "text/plain"}


@bp.post("/members")
def add_member():
    name = request.form.get("name", "").strip()[:MEMBER_NAME_MAX]
    avatar = request.form.get("avatar", "")
    if avatar not in scoring.AVATARS:
        avatar = random.choice(scoring.AVATARS)
    if not name:
        flash("An agent needs a name.", "error")
    elif db.member_name_taken(name):
        flash(f"There's already an agent called {name}.", "error")
    else:
        db.add_member(name, avatar)
        flash(f"Agent {name} recruited. Send them their link.", "celebrate")
    return redirect(url_for("admin.index"))


@bp.post("/members/<int:member_id>/toggle")
def toggle_member(member_id: int):
    db.toggle_member(member_id)
    return redirect(url_for("admin.index"))


@bp.post("/members/<int:member_id>/rotate")
def rotate_token(member_id: int):
    db.rotate_token(member_id)
    flash("New link issued. The old one no longer works.", "info")
    return redirect(url_for("admin.index"))


@bp.post("/biscuits/<int:biscuit_id>/toggle")
def toggle_biscuit(biscuit_id: int):
    db.toggle_biscuit(biscuit_id)
    return redirect(url_for("admin.index") + "#biscuits")


@bp.route("/biscuits/<int:biscuit_id>/photo", methods=["GET", "POST"])
def biscuit_photo(biscuit_id: int):
    """Add or replace a biscuit's photo: upload, Open Food Facts pick, or any pasted URL."""
    b = db.get_biscuit(biscuit_id)
    if b is None:
        abort(404)
    if request.method == "POST":
        try:
            photo = images.attach_photo(request.form, request.files, allow_any_url=True,
                                        exclude_biscuit=biscuit_id)
        except images.PhotoError as e:
            flash(str(e), "error")
            return redirect(url_for("admin.biscuit_photo", biscuit_id=biscuit_id))
        if photo is None:
            flash("Pick a photo first.", "error")
            return redirect(url_for("admin.biscuit_photo", biscuit_id=biscuit_id))
        db.set_biscuit_image(biscuit_id, *photo)
        flash(f"Photo saved for {b['name']}.", "celebrate")
        return redirect(url_for("admin.index") + "#biscuits")
    return render_template("admin_photo.html", b=b)


@bp.get("/api/image-search")
def api_image_search():
    # Separate from the agent endpoint: admin on 127.0.0.1 usually has no agent cookie.
    return images.search_json(request.args.get("q", ""))


@bp.get("/export.csv")
def export_csv():
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["agent", "biscuit", "brand", *scoring.CATEGORY_KEYS, "overall",
                     "comment", "created_utc", "updated_utc"])
    for r in db.export_ratings():
        vals = [r["scores"].get(k, "") for k in scoring.CATEGORY_KEYS]
        present = [v for v in vals if v != ""]
        overall = round(sum(present) / len(present), 2) if present else ""
        row = [r["agent"], r["biscuit"], r["brand"], *vals, overall,
               r["comment"], r["created_at"], r["updated_at"]]
        writer.writerow([util.csv_safe(v) for v in row])
    # utf-8-sig adds a BOM so Excel shows emoji and accents instead of mojibake.
    body = buf.getvalue().encode("utf-8-sig")
    filename = f"brt-ratings-{date.today():%Y%m%d}.csv"
    return Response(body, mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
