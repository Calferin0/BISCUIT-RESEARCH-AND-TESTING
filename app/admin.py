"""Control room: manage agents and biscuits, export data. Loopback-only (D5)."""
from __future__ import annotations

import csv
import io
import random
from datetime import date

from flask import (Blueprint, Response, abort, current_app, flash, redirect, render_template,
                   request, url_for)

from . import db, features, images, radar, rarity, scoring, util

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
        reopen=db.pending_reopen_requests(),
        site=radar.load_site(current_app.config["DATA_DIR"]),
        shops=db.list_shops(include_hidden=True),
        features=features.FEATURES, feature_state=features.enabled_map(),
        grants=db.admin_grants(), grant_limit=GRANT_LIMIT,
        all_prices=db.all_prices(), fmt_price=radar.fmt_price, dunks=db.all_dunks(),
        open_duels=[d for d in db.list_duels(None, 200) if d["status"] in ("pending", "active")],
        ious=[d for d in db.list_duels(None, 200) if d["status"] == "done" and d["biscuit_iou"]
              and d["winner_id"] and not d["iou_paid"]],
    )


@bp.route("/biscuits/<int:biscuit_id>/edit", methods=["GET", "POST"])
def edit_biscuit(biscuit_id: int):
    """Full specimen edit: name, brand, pinned rarity, and every price report for it."""
    b = db.get_biscuit(biscuit_id)
    if b is None:
        abort(404)
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:60]
        brand = request.form.get("brand", "").strip()[:60]
        tier = request.form.get("rarity_override") or None
        if not name:
            flash("A specimen needs a name.", "error")
        elif tier is not None and tier not in rarity.BY_KEY:
            abort(400)
        elif any(m.exact and m.id != biscuit_id for m in db.similar_biscuits(name, brand)):
            flash(f"Another specimen is already called “{name}”.", "error")
        else:
            db.update_biscuit(biscuit_id, name, brand, tier)
            flash(f"Saved: {name}.", "celebrate")
            return redirect(url_for("admin.edit_biscuit", biscuit_id=biscuit_id))
    votes = db.rarity_votes().get(biscuit_id, [])
    return render_template("admin_biscuit.html", b=b, tiers=rarity.TIERS, prices=db.prices_for_biscuit(biscuit_id),
                           fmt=radar.fmt_price, team_tier=rarity.decide(votes),
                           counts={t: votes.count(t) for t in rarity.BY_KEY})


@bp.post("/prices/<int:price_id>")
def edit_price(price_id: int):
    biscuit_id = request.form.get("biscuit_id", type=int)
    if request.form.get("action") == "toggle":
        db.toggle_price(price_id)
    else:
        try:
            db.update_price(price_id, radar.parse_price(request.form.get("price", "")),
                            request.form.get("pack", "").strip()[:40])
        except radar.RadarError as e:
            flash(str(e), "error")
    if request.form.get("back") == "list":
        return redirect(url_for("admin.index") + "#prices")
    return redirect(url_for("admin.edit_biscuit", biscuit_id=biscuit_id) + "#prices")


# --- control-room powers --------------------------------------------------------------

GRANT_LIMIT = 1000


@bp.post("/features")
def set_features():
    """Feature switches: every box posted = on, unticked = off."""
    on = set(request.form.getlist("on"))
    for key in features.FEATURES:
        db.set_setting(f"feature.{key}", "1" if key in on else "0")
    flash("Feature switches saved.", "info")
    return redirect(url_for("admin.index") + "#features")


@bp.post("/points")
def grant_points():
    """Hand out (or dock) points. Goes through the ledger, so the agent sees it on their points page."""
    m = db.get_member(request.form.get("member_id", type=int) or 0)
    amount = request.form.get("amount", type=int)
    reason = request.form.get("reason", "").strip()[:80] or "Control room bonus"
    if m is None or amount is None or amount == 0 or abs(amount) > GRANT_LIMIT:
        flash(f"Pick an agent and an amount between -{GRANT_LIMIT} and {GRANT_LIMIT} (not 0).", "error")
    else:
        db.ledger_add(m["id"], amount, f"🎖️ {reason}", "admin")
        flash(f"{'+' if amount > 0 else ''}{amount} points to {m['name']}: {reason}", "celebrate")
    return redirect(url_for("admin.index") + "#points")


@bp.post("/dunks/<int:dunk_id>/toggle")
def toggle_dunk(dunk_id: int):
    db.toggle_dunk(dunk_id)
    return redirect(url_for("admin.index") + "#dunks")


@bp.post("/duels/<int:duel_id>/void")
def void_duel(duel_id: int):
    flash("Duel voided, stakes refunded." if db.void_duel(duel_id) else "That duel is already over.", "info")
    return redirect(url_for("admin.index") + "#duels")


@bp.post("/duels/<int:duel_id>/iou")
def settle_iou(duel_id: int):
    db.set_iou(duel_id, 1 if request.form.get("action") == "paid" else 2)
    return redirect(url_for("admin.index") + "#duels")


@bp.post("/biscuits/<int:biscuit_id>/rarity-reset")
def reset_rarity(biscuit_id: int):
    db.clear_rarity_votes(biscuit_id)
    flash("Rarity votes cleared.", "info")
    return redirect(url_for("admin.edit_biscuit", biscuit_id=biscuit_id))


@bp.post("/shops/<int:shop_id>/rename")
def rename_shop(shop_id: int):
    name = request.form.get("name", "").strip()[:80]
    if name and db.get_shop(shop_id):
        db.update_shop(shop_id, name)
    return redirect(url_for("admin.index") + "#radar")


@bp.post("/members/<int:member_id>/edit")
def edit_member(member_id: int):
    m = db.get_member(member_id)
    name = request.form.get("name", "").strip()[:MEMBER_NAME_MAX]
    avatar = request.form.get("avatar", "")
    if m is None:
        abort(404)
    if not name:
        flash("An agent needs a name.", "error")
    elif name.lower() != m["name"].lower() and db.member_name_taken(name):
        flash(f"There's already an agent called {name}.", "error")
    else:
        db.update_member(member_id, name, avatar if avatar in scoring.AVATARS else m["avatar"])
        flash(f"Agent {name} updated.", "info")
    return redirect(url_for("admin.index"))


@bp.post("/biscuits/<int:biscuit_id>/case")
def set_case(biscuit_id: int):
    """Close a case (biscuit gone from shops: results go public, reports stop) or reopen it."""
    b = db.get_biscuit(biscuit_id)
    if b is None:
        abort(404)
    closing = request.form.get("action") == "close"
    db.set_case_status(biscuit_id, closed=closing)
    flash(f"Case {'closed' if closing else 'reopened'}: {b['name']}.", "info")
    return redirect(url_for("admin.index") + "#biscuits")


@bp.post("/reopen-requests/<int:request_id>/decline")
def decline_reopen(request_id: int):
    db.decline_reopen_request(request_id)
    return redirect(url_for("admin.index") + "#reopen")


@bp.post("/radar/centre")
def radar_centre():
    """Set the radar centre by postcode. Stored in the data dir, never in the (public) repo."""
    try:
        postcode = radar.normalise_postcode(request.form.get("postcode", ""))
        lat, lng = radar.postcode_lookup(postcode)
    except radar.RadarError as e:
        flash(str(e), "error")
        return redirect(url_for("admin.index") + "#radar")
    label = request.form.get("label", "").strip()[:60] or "HQ"
    radar.save_site(current_app.config["DATA_DIR"], label, lat, lng, postcode)
    flash(f"Radar centred on {label} ({postcode}).", "info")
    return redirect(url_for("admin.index") + "#radar")


@bp.post("/radar/import")
def radar_import():
    site = radar.load_site(current_app.config["DATA_DIR"])
    if site is None:
        flash("Set the radar centre first.", "error")
        return redirect(url_for("admin.index") + "#radar")
    try:
        found = radar.overpass_shops(site["lat"], site["lng"])
    except radar.RadarError as e:
        flash(str(e), "error")
        return redirect(url_for("admin.index") + "#radar")
    added = sum(1 for s in found if db.add_shop(s, None) is not None)
    flash(f"OpenStreetMap: {len(found)} shops found within {radar.IMPORT_RADIUS_M // 1000} km, {added} new.", "info")
    return redirect(url_for("admin.index") + "#radar")


@bp.post("/shops/<int:shop_id>/toggle")
def toggle_shop(shop_id: int):
    if db.get_shop(shop_id) is None:
        abort(404)
    db.toggle_shop(shop_id)
    return redirect(url_for("admin.index") + "#radar")


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
