"""Agent-facing pages: join, specimens, rating, adding biscuits and photos, leaderboard."""
from __future__ import annotations

import functools
import json
import random
from dataclasses import asdict
from datetime import date
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template,
                   request, send_from_directory, url_for)

from . import awards, db, images, recommend, scoring, similarity, util
from . import drops as drops_mod

bp = Blueprint("views", __name__)

NAME_MAX = 60
COMMENT_MAX = 500
COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # a year: agents shouldn't need their link again


def agent_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.member is None:
            return render_template(
                "denied.html", stamp="Access denied", heading="You are not cleared for biscuits.",
                message="Ask the BRT administrator for your personal agent link.",
            ), 403
        return view(*args, **kwargs)
    return wrapped


def _presence():
    return current_app.extensions["brt_presence"]


def _describe(endpoint: str | None, args: dict) -> str | None:
    """Human label for a page, built server-side so admin never displays client-supplied text."""
    if endpoint == "views.biscuit":
        name = db.biscuit_name(args.get("biscuit_id", 0))
        return f"Looking at {name}" if name else None
    return {
        "views.index": "Browsing specimens",
        "views.add_biscuit": "Logging a new specimen",
        "views.leaderboard": "At awards night",
        "views.suggestions": "At the suggestion box",
        "views.dashboard": "Checking the dashboard",
        "views.edit_drop": "Logging a biscuit drop",
        "views.working_on_it": "Reading what's being built",
    }.get(endpoint)


# Blueprint-level, so it runs *after* the app-level load_agent() has set g.member.
@bp.before_request
def record_page_view() -> None:
    if request.method == "GET" and g.get("member") is not None:
        label = _describe(request.endpoint, request.view_args or {})
        if label:
            _presence().touch(g.member, label)


@bp.post("/api/ping")
@agent_required
def ping():
    """Heartbeat from brt.js every ~25 s while a tab is visible."""
    body = request.get_json(silent=True) or {}
    path = str(body.get("path", ""))[:200]
    try:
        endpoint, args = current_app.url_map.bind("").match(path, method="GET")
    except Exception:  # unknown path: still counts as live, just without a label
        endpoint, args = None, {}
    _presence().touch(g.member, _describe(endpoint, args) or "On BRT", editing=bool(body.get("editing")))
    return "", 204


def _active_biscuit_or_404(biscuit_id: int):
    b = db.get_biscuit(biscuit_id)
    if b is None or not b["active"]:
        abort(404)
    return b


@bp.get("/join/<token>")
def join(token: str):
    member = db.member_by_token(token)
    if member is None:
        abort(404)
    resp = redirect(url_for("views.index"))
    # The cookie *is* the identity (D4). httponly: page JS can't read it. Lax: not sent on
    # cross-site POSTs, which blunts CSRF from other sites.
    resp.set_cookie(util.AGENT_COOKIE, token, max_age=COOKIE_MAX_AGE, httponly=True, samesite="Lax")
    flash(f"Welcome to the programme, Agent {member['name']}. Clearance level: BISCUIT.", "celebrate")
    return resp


@bp.post("/leave")
def leave():
    resp = redirect(url_for("views.index"))
    resp.delete_cookie(util.AGENT_COOKIE)
    return resp


@bp.get("/")
@agent_required
def index():
    biscuits = db.list_biscuits(g.member["id"])
    todo = sum(1 for b in biscuits if not b["mine"])
    return render_template("index.html", biscuits=biscuits, todo=todo)


@bp.get("/b/<int:biscuit_id>")
@agent_required
def biscuit(biscuit_id: int):
    b = _active_biscuit_or_404(biscuit_id)
    mine = db.get_rating(g.member["id"], biscuit_id)
    # Blind rating: other people's results aren't even fetched until you've filed your own.
    return render_template(
        "biscuit.html", b=b, mine=mine,
        reports=db.ratings_for_biscuit(biscuit_id) if mine else [],
        cats=db.category_averages(biscuit_id) if mine else {},
    )


@bp.post("/b/<int:biscuit_id>/rate")
@agent_required
def rate(biscuit_id: int):
    _active_biscuit_or_404(biscuit_id)
    back = redirect(url_for("views.biscuit", biscuit_id=biscuit_id))

    purist = bool(request.form.get(scoring.PURIST_FIELD))
    skipped = scoring.SKIPPABLE_KEYS if purist else ()
    scores: dict[str, int] = {}
    for c in scoring.CATEGORIES:
        if c.key in skipped:
            continue  # stored as no score at all, so averages simply leave it out
        try:
            value = int(request.form.get(c.key, ""))
        except ValueError:
            value = 0
        if not 1 <= value <= 5:
            hint = f" (or tick “{scoring.PURIST_LABEL}”)" if c.skippable else ""
            flash(f"{c.label} needs a score from 1 to 5{hint}.", "error")
            return back
        scores[c.key] = value

    is_update = db.get_rating(g.member["id"], biscuit_id) is not None
    comment = request.form.get("comment", "").strip()[:COMMENT_MAX]
    db.upsert_rating(g.member["id"], biscuit_id, scores, comment, skipped)
    if purist:
        flash("Field report filed, bone dry. The tea remains untouched. 🏜️", "celebrate")
    else:
        flash("Field report amended. The record has been corrected." if is_update
              else "Field report filed. Crumbs logged as evidence.", "celebrate")
    # Post/Redirect/Get: a refresh after submitting won't resubmit the form.
    return back


@bp.post("/b/<int:biscuit_id>/photo")
@agent_required
def add_photo(biscuit_id: int):
    """Any agent can give a photo-less biscuit a photo. Replacing one is admin-only."""
    b = _active_biscuit_or_404(biscuit_id)
    back = redirect(url_for("views.biscuit", biscuit_id=biscuit_id))
    if b["image"]:
        flash("This specimen already has a photo. Only the control room can replace it.", "error")
        return back
    try:
        photo = images.attach_photo(request.form, request.files, exclude_biscuit=biscuit_id)
    except images.PhotoError as e:
        flash(str(e), "error")
        return back
    if photo is None:
        flash("Pick a photo first: upload one or search the web.", "error")
        return back
    db.set_biscuit_image(biscuit_id, *photo)
    flash("Evidence photo attached. Looking good.", "celebrate")
    return back


@bp.route("/add", methods=["GET", "POST"])
@agent_required
def add_biscuit():
    if request.method == "GET":
        # ?name=&brand= prefill, used by "Log it" links on the dashboard (drops and scouting picks).
        prefill = {"name": request.args.get("name", "")[:NAME_MAX], "brand": request.args.get("brand", "")[:NAME_MAX]}
        return render_template("add_biscuit.html", form=prefill, matches=[])

    form = {
        "name": request.form.get("name", "").strip()[:NAME_MAX],
        "brand": request.form.get("brand", "").strip()[:NAME_MAX],
        "web_image": request.form.get("web_image", "").strip(),
        "confirm_new": bool(request.form.get("confirm_new")),
    }

    def again(notice: str, matches=(), code: int = 200):
        # Re-render rather than redirect so typed values survive. The browser can't refill a
        # file input, so the template asks them to re-pick an uploaded photo.
        return render_template("add_biscuit.html", form=form, matches=matches, notice=notice), code

    if not form["name"]:
        return again("A specimen needs a name.", code=400)

    # Duplicate guard: exact matches are blocked; near-matches need an explicit "it's different".
    matches = db.similar_biscuits(form["name"], form["brand"])
    exact = next((m for m in matches if m.exact), None)
    if exact:
        return again(f"“{exact.name}” is already on file. Rate that one instead!", matches, 409)
    if matches and not form["confirm_new"]:
        return again("Possible duplicate! Check these first. If yours is different, tick the box.", matches)

    try:
        photo = images.attach_photo(request.form, request.files)
    except images.PhotoError as e:
        return again(str(e), matches, 400)
    filename, digest, source = photo or (None, None, None)

    biscuit_id = db.add_biscuit(form["name"], form["brand"], filename, g.member["id"],
                                image_hash=digest, image_source=source)
    flash("Specimen logged. Commence tasting.", "celebrate")
    return redirect(url_for("views.biscuit", biscuit_id=biscuit_id))


@bp.get("/api/similar")
@agent_required
def api_similar():
    name = request.args.get("name", "").strip()[:NAME_MAX]
    brand = request.args.get("brand", "").strip()[:NAME_MAX]
    if len(name) < 3:
        return {"matches": []}
    return {"matches": [{**asdict(m), "url": url_for("views.biscuit", biscuit_id=m.id)}
                        for m in db.similar_biscuits(name, brand)]}


@bp.get("/api/image-search")
@agent_required
def api_image_search():
    return images.search_json(request.args.get("q", ""))


@bp.get("/thumb")
def thumb():
    """Relay an Open Food Facts thumbnail through this PC, so phones need no internet of their own.
    Locked to the OFF image host so it can't be used as an open proxy. No agent check, because
    the admin photo page (127.0.0.1, no cookie) uses it too."""
    url = request.args.get("u", "")
    if not images.is_off_image_url(url):
        abort(404)
    try:
        data = images.fetch_image(url)
        ext, _ = images.inspect(data)
    except images.PhotoError:
        abort(404)
    mime = {"jpg": "image/jpeg"}.get(ext, f"image/{ext}")
    return current_app.response_class(data, mimetype=mime, headers={"Cache-Control": "public, max-age=86400"})


@bp.get("/dashboard")
@agent_required
def dashboard():
    today = date.today()
    timeline = drops_mod.timeline(db.list_drops(), today)
    # Link drops to case files by exact (normalised) name, so "on file" needs no extra column.
    logged = db.list_biscuits(g.member["id"])
    for bucket in timeline.values():
        for d in bucket:
            match = next((m for m in similarity.find_matches(d["name"], d["brand"], logged) if m.exact), None)
            d["biscuit_id"] = match.id if match else None
    picks = recommend.next_tastings(logged, db.member_ratings(g.member["id"]), random.Random())
    return render_template("dashboard.html", timeline=timeline, picks=picks, kinds=drops_mod.KINDS,
                           todo=sum(1 for b in logged if not b["mine"]), today=today)


@bp.get("/api/scouting")
@agent_required
def api_scouting():
    try:
        brands = recommend.team_brands(db.leaderboard())
        items = recommend.scouting(brands, db.list_biscuits(None), random.Random())
    except images.PhotoError as e:
        return {"items": [], "error": str(e)}, 502
    for it in items:
        it["thumb_url"] = url_for("views.thumb", u=it["thumb"])
        it["log_url"] = url_for("views.add_biscuit", name=it["name"], brand=it["brand"])
    return {"items": items}


@bp.route("/drops/new", methods=["GET", "POST"])
@bp.route("/drops/<int:drop_id>/edit", methods=["GET", "POST"])
@agent_required
def edit_drop(drop_id: int | None = None):
    existing = db.get_drop(drop_id) if drop_id else None
    if drop_id and (existing is None or not existing["active"]):
        abort(404)
    if request.method == "GET":
        return render_template("drop_form.html", drop=existing or {}, kinds=drops_mod.KINDS)
    try:
        values = drops_mod.clean(request.form)
    except drops_mod.DropError as e:
        flash(str(e), "error")
        return render_template("drop_form.html", drop={**(dict(existing) if existing else {}), **request.form},
                               kinds=drops_mod.KINDS), 400
    if existing:
        db.update_drop(drop_id, values, g.member["id"])
        flash("Drop updated. Thanks for keeping the intel fresh.", "info")
    else:
        db.add_drop(values, g.member["id"])
        flash("Drop logged. The team has been alerted (they'll see it on the dashboard). 📅", "celebrate")
    return redirect(url_for("views.dashboard") + "#drops")


SUGGESTION_MAX = 1000
ROADMAP_FILE = Path(__file__).with_name("roadmap.json")
ROADMAP_STATUSES = {"now": "🚧 Working on it now", "next": "⏭️ Up next", "later": "🗓️ On the list",
                    "done": "✅ Done"}


@bp.route("/suggestions", methods=["GET", "POST"])
@agent_required
def suggestions():
    if request.method == "POST":
        kind = request.form.get("kind", "idea")
        body = request.form.get("body", "").strip()[:SUGGESTION_MAX]
        if kind not in db.SUGGESTION_KINDS:
            kind = "other"
        if len(body) < 5:
            flash("Give us a bit more than that. What's the idea?", "error")
        else:
            db.add_suggestion(g.member["id"], kind, body)
            flash("Suggestion filed. The control room reviews the box every week. 📮", "celebrate")
        return redirect(url_for("views.suggestions"))
    return render_template("suggestions.html", items=db.list_suggestions(g.member["id"]),
                           kinds=db.SUGGESTION_KINDS, statuses=db.SUGGESTION_STATUSES)


@bp.post("/suggestions/<int:suggestion_id>/vote")
@agent_required
def vote(suggestion_id: int):
    if not db.suggestion_exists(suggestion_id):
        abort(404)
    db.toggle_vote(suggestion_id, g.member["id"])
    return redirect(url_for("views.suggestions") + f"#s{suggestion_id}")


@bp.get("/working-on-it")
@agent_required
def working_on_it():
    try:
        roadmap = json.loads(ROADMAP_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current_app.logger.exception("roadmap.json unreadable")
        roadmap = {"updates": [], "roadmap": []}
    return render_template("working_on_it.html", roadmap=roadmap, road_statuses=ROADMAP_STATUSES,
                           statuses=db.SUGGESTION_STATUSES,
                           in_flight=db.list_suggestions(g.member["id"], ("building", "planned")),
                           shipped=db.list_suggestions(g.member["id"], ("shipped",))[:10])


@bp.get("/leaderboard")
@agent_required
def leaderboard():
    return render_template("leaderboard.html", ranked=db.leaderboard(), agents=db.agent_stats(),
                           awards=awards.compute(db.awards_data()),
                           rated=db.rated_biscuit_ids(g.member["id"]))


@bp.get("/uploads/<path:filename>")
def upload(filename: str):
    # send_from_directory rejects ../ traversal. Photos aren't secret, so no agent check:
    # the admin page (no agent cookie on 127.0.0.1) needs them too.
    return send_from_directory(current_app.config["UPLOAD_DIR"], filename, max_age=86400)
