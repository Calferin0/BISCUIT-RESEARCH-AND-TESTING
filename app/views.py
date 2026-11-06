"""Agent-facing pages: join, specimens, rating, adding biscuits and photos, leaderboard."""
from __future__ import annotations

import functools
import json
import random
from dataclasses import asdict
from datetime import date
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template,
                   request, send_from_directory, session, url_for)

from . import (awards, cases, db, duel, features, fun, images, loot, points, radar, rarity, recommend, scoring,
               shop, similarity, util)
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
        "views.points_page": "Counting their Biscuit Points",
        "views.shop_page": "Browsing the Biscuit Shop",
        "views.radar_page": "Scanning the Biscuit Radar",
        "views.arena": "Lurking in the Biscuit VS arena",
        "views.duel_page": "Mid-duel ⚔️",
        "views.loot_page": "Shaking a Mystery Tin",
        "views.dunk_page": "Timing a dunk ⏱️",
        "views.locker": "Admiring themselves in the Locker 🪞",
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
    today = date.today()
    rows = db.list_biscuits(g.member["id"])
    votes = db.rarity_votes()
    # Specimens with a current (not gone) drop get an "on shelves" badge.
    current = [d for d in db.list_drops() if not drops_mod.countdown(d, today).startswith("gone")]
    by_drop = {d["id"]: d for d in current}
    shelf = {bid: by_drop[did] for did, bid in drop_links(current, rows).items()}
    biscuits = [{**dict(b), "visible": cases.can_see(b, b["mine"], today), "closed": cases.is_closed(b),
                 "tier": rarity.decide(votes.get(b["id"], []), b["rarity_override"]),
                 "drop": shelf.get(b["id"])}
                for b in rows]
    todo = sum(1 for b in biscuits if not b["mine"] and not b["closed"])
    return render_template("index.html", biscuits=biscuits, todo=todo, kinds=drops_mod.KINDS)


@bp.post("/b/<int:biscuit_id>/rarity")
@agent_required
def vote_rarity(biscuit_id: int):
    _active_biscuit_or_404(biscuit_id)
    tier = request.form.get("tier", "")
    if tier not in rarity.BY_KEY:
        abort(400)
    db.vote_rarity(biscuit_id, g.member["id"], tier)
    t = rarity.BY_KEY[tier]
    flash(f"You voted {t.icon} {t.label}. {t.blurb}", "info")
    return redirect(url_for("views.biscuit", biscuit_id=biscuit_id) + "#rarity")


@bp.get("/b/<int:biscuit_id>")
@agent_required
def biscuit(biscuit_id: int):
    b = _active_biscuit_or_404(biscuit_id)
    mine = db.get_rating(g.member["id"], biscuit_id)
    # Blind rating: others' results aren't even fetched until you've filed, the case is a week
    # old, or it's closed (app/cases.py).
    visible = cases.can_see(b, mine is not None, date.today())
    return render_template(
        "biscuit.html", b=b, mine=mine, visible=visible,
        closed=cases.is_closed(b), unseals_on=cases.unseals_on(b),
        reports=db.ratings_for_biscuit(biscuit_id) if visible else [],
        cats=db.category_averages(biscuit_id) if visible else {},
        votes=db.report_votes(biscuit_id, g.member["id"]) if visible else {},
        reopen_pending=db.reopen_request_count(biscuit_id),
        cheapest=min((p for p in db.current_prices() if p["biscuit_id"] == biscuit_id),
                     key=lambda p: p["pence"], default=None),
        fmt_price=radar.fmt_price,
        tiers=rarity.TIERS,
        tier=rarity.decide(db.rarity_votes().get(biscuit_id, []), b["rarity_override"]),
        tier_counts={t: db.rarity_votes().get(biscuit_id, []).count(t) for t in rarity.BY_KEY},
        my_tier=db.my_rarity_vote(biscuit_id, g.member["id"]),
    )


@bp.post("/b/<int:biscuit_id>/rate")
@agent_required
def rate(biscuit_id: int):
    b = _active_biscuit_or_404(biscuit_id)
    back = redirect(url_for("views.biscuit", biscuit_id=biscuit_id))
    if cases.is_closed(b):
        flash("This case is closed: the biscuit's no longer in shops. Request a reopen if it's back.", "error")
        return back

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


@bp.post("/b/<int:biscuit_id>/reopen")
@agent_required
def request_reopen(biscuit_id: int):
    b = _active_biscuit_or_404(biscuit_id)
    back = redirect(url_for("views.biscuit", biscuit_id=biscuit_id))
    if not cases.is_closed(b):
        flash("That case is already open.", "info")
    elif db.add_reopen_request(biscuit_id, g.member["id"], request.form.get("note", "").strip()[:200]):
        flash("Reopen request sent to the control room. Back on the shelves? Nice spot. 🕵️", "celebrate")
    else:
        flash("You've already asked. The control room will get to it.", "info")
    return back


@bp.post("/reports/<int:rating_id>/thumb")
@agent_required
def thumb_report(rating_id: int):
    """👍 another agent's field report. Not your own, and only once you can see it."""
    owner = db.rating_owner(rating_id)
    if owner is None:
        abort(404)
    b = _active_biscuit_or_404(owner["biscuit_id"])
    if owner["member_id"] == g.member["id"]:
        flash("Nice try. You can't thumbs-up your own report. 😏", "error")
    elif not cases.can_see(b, db.get_rating(g.member["id"], b["id"]) is not None, date.today()):
        abort(403)
    else:
        db.toggle_report_vote(rating_id, g.member["id"])
    return redirect(url_for("views.biscuit", biscuit_id=b["id"]) + f"#r{rating_id}")


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
    if request.form.get("tier") in rarity.BY_KEY:  # the logger's pick is the first rarity vote
        db.vote_rarity(biscuit_id, g.member["id"], request.form["tier"])
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


def drop_links(all_drops, logged) -> dict[int, int]:
    """{drop_id: biscuit_id} for drops that ARE a logged specimen: explicit link first, then an
    exact name match, then drops.auto_link's word-containment guess."""
    active_ids = {b["id"] for b in logged}
    links = {}
    for d in all_drops:
        if d["biscuit_id"] in active_ids:
            links[d["id"]] = d["biscuit_id"]
            continue
        exact = next((m for m in similarity.find_matches(d["name"], d["brand"], logged) if m.exact), None)
        guess = exact.id if exact else drops_mod.auto_link(d, logged)
        if guess:
            links[d["id"]] = guess
    return links


@bp.get("/dashboard")
@agent_required
def dashboard():
    today = date.today()
    logged = db.list_biscuits(g.member["id"])
    all_drops = db.list_drops()
    links = drop_links(all_drops, logged)
    by_id = {b["id"]: b for b in logged}
    # No duplicates: a drop that's already a specimen leaves the drop timeline and shows as a
    # compact "already on file" chip linking to its case file.
    timeline = drops_mod.timeline([d for d in all_drops if d["id"] not in links], today)
    on_file = [{**dict(d), "biscuit": by_id[links[d["id"]]], "countdown": drops_mod.countdown(d, today)}
               for d in all_drops if d["id"] in links
               and drops_mod.countdown(d, today).split()[0] != "gone"]
    picks = recommend.next_tastings(logged, db.member_ratings(g.member["id"]), random.Random())
    botd, botd_line = fun.biscuit_of_the_day([b for b in logged if b["active"]], today)
    return render_template("dashboard.html", timeline=timeline, picks=picks, kinds=drops_mod.KINDS,
                           on_file=on_file, todo=sum(1 for b in logged if not b["mine"]), today=today,
                           botd=botd, botd_line=botd_line, horoscope=fun.horoscope(g.member["id"], today))


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
    specimens = [b for b in db.list_biscuits(None) if b["active"]]
    if request.method == "GET":
        return render_template("drop_form.html", drop=existing or {}, kinds=drops_mod.KINDS, specimens=specimens)
    try:
        values = drops_mod.clean(request.form)
        if values["biscuit_id"] is not None and values["biscuit_id"] not in {b["id"] for b in specimens}:
            raise drops_mod.DropError("Pick a specimen from the list.")
    except drops_mod.DropError as e:
        flash(str(e), "error")
        return render_template("drop_form.html", drop={**(dict(existing) if existing else {}), **request.form},
                               kinds=drops_mod.KINDS, specimens=specimens), 400
    if existing:
        db.update_drop(drop_id, values, g.member["id"])
        flash("Drop updated. Thanks for keeping the intel fresh.", "info")
    else:
        db.add_drop(values, g.member["id"])
        flash("Drop logged. The team has been alerted (they'll see it on the dashboard). 📅", "celebrate")
    return redirect(url_for("views.dashboard") + "#drops")


def _earned(member_id: int) -> int:
    row = next(iter(db.points_activity(member_id)), None)
    return points.total(row) if row else 0


def balance(member_id: int) -> int:
    """Spendable points: lifetime earned - shop spend + ledger (tins, duels). One definition."""
    return _earned(member_id) - db.points_spent(member_id) + db.ledger_total(member_id)


@bp.get("/points")
@agent_required
def points_page():
    # Ranks use lifetime *earned* points, so shopping never demotes anyone.
    table = sorted(({**dict(a), "points": points.total(a)} for a in db.points_activity()),
                   key=lambda a: (-a["points"], a["name"].lower()))
    me_id = g.member["id"]
    mine = next((a for a in db.points_activity(me_id)), None)
    earned = points.total(mine) if mine else 0
    # The balance must use the same one definition as everywhere else (views.balance): earned -
    # shop spend + ledger. This page used to skip the ledger, so Mystery Tins didn't show here.
    return render_template("points.html", table=table, rules=points.RULES, rank=points.rank,
                           breakdown=points.breakdown(mine) if mine else [], earned=earned,
                           spent=db.points_spent(me_id), ledger=db.ledger_total(me_id), balance=balance(me_id),
                           movements=db.recent_ledger(me_id, 15), next_rank=points.next_rank(earned))


@bp.get("/shop")
@agent_required
@features.required("shop")
def shop_page():
    me_id = g.member["id"]
    equipped = shop.flair_for(db.equipped_items().get(me_id, []))
    return render_template("shop.html", slots=shop.SLOTS, catalogue=shop.CATALOGUE, balance=balance(me_id),
                           owned=db.owned_items(me_id), equipped_keys=set(db.equipped_items().get(me_id, [])),
                           preview=equipped)


@bp.post("/shop/buy/<item_key>")
@agent_required
@features.required("shop")
def shop_buy(item_key: str):
    item = shop.BY_KEY.get(item_key)
    if item is None or item.loot_tier is not None:  # loot-only items can't be bought
        abort(404)
    me_id = g.member["id"]
    error = db.buy(me_id, item.key, item.cost, balance(me_id))
    if error:
        flash(error, "error")
    else:
        db.equip(me_id, item.slot, item.key)  # buying it means you want to wear it
        flash(f"Purchased and equipped: {item.name}. Looking sharp, agent. 🛍️", "celebrate")
    return redirect(url_for("views.shop_page") + f"#{item.slot}")


@bp.route("/loot", methods=["GET", "POST"])
@agent_required
@features.required("loot")
def loot_page():
    me_id = g.member["id"]
    if request.method == "POST":
        if balance(me_id) < loot.BOX_COST:
            flash(f"A Mystery Tin costs {loot.BOX_COST} points. Go file some reports!", "error")
            return redirect(url_for("views.loot_page"))
        pull = loot.open_tin(db.owned_items(me_id), random.SystemRandom())
        db.grant_loot(me_id, None if (pull.item is None or pull.duplicate) else pull.item.key,
                      loot.BOX_COST, pull.points, "Mystery Tin")
        # Post/Redirect/Get, so a refresh can't open (and pay for) a second tin.
        session["loot_reveal"] = {"tier": pull.tier, "item": pull.item.key if pull.item else None,
                                  "points": pull.points, "duplicate": pull.duplicate, "quip": pull.quip}
        return redirect(url_for("views.loot_page") + "#reveal")
    reveal = session.pop("loot_reveal", None)
    if reveal and reveal["item"]:
        reveal["item_obj"] = shop.BY_KEY.get(reveal["item"])
    owned = db.owned_items(me_id)
    return render_template("loot.html", reveal=reveal, odds=loot.ODDS, cost=loot.BOX_COST,
                           balance=balance(me_id), tiers=rarity.BY_KEY, ev=loot.expected_value(),
                           refund=loot.COMMON_REFUND, dupe=loot.DUPE_POINTS,
                           collection=[i for i in shop.CATALOGUE if i.loot_tier],
                           owned=owned)


# --- Locker: your look + inventory -------------------------------------------------------
# Deliberately NOT behind the "shop" switch: what you own stays yours to wear.

@bp.get("/locker")
@agent_required
def locker():
    me_id = g.member["id"]
    owned = db.inventory(me_id)
    equipped = set(db.equipped_items().get(me_id, []))
    items = [{"item": shop.BY_KEY[o["item_key"]], "source": o["source"], "when": o["created_at"],
              "on": o["item_key"] in equipped} for o in owned if o["item_key"] in shop.BY_KEY]
    by_slot = {slot: [i for i in items if i["item"].slot == slot] for slot in shop.SLOTS}
    return render_template("locker.html", by_slot=by_slot, slots=shop.SLOTS, avatars=scoring.AVATARS,
                           total=len(items), loot_count=sum(1 for i in items if i["source"] == "loot"),
                           catalogue_size=len(shop.CATALOGUE))


@bp.post("/locker/equip/<slot>")
@agent_required
def locker_equip(slot: str):
    if slot not in shop.SLOTS:
        abort(404)
    key = request.form.get("item_key", "")
    if key:
        item = shop.BY_KEY.get(key)
        if item is None or item.slot != slot or key not in db.owned_items(g.member["id"]):
            abort(400)
    db.equip(g.member["id"], slot, key or None)
    return redirect(url_for("views.locker") + f"#{slot}")


@bp.post("/locker/avatar")
@agent_required
def locker_avatar():
    avatar = request.form.get("avatar", "")
    if avatar not in scoring.AVATARS:
        abort(400)
    db.update_member(g.member["id"], g.member["name"], avatar)
    flash(f"New look: {avatar}. Very distinguished.", "celebrate")
    return redirect(url_for("views.locker"))


# --- Dunk-O-Meter ----------------------------------------------------------------------

DRINKS = {"tea": "🫖 Tea", "coffee": "☕ Coffee", "hot-choc": "🍫 Hot chocolate", "milk": "🥛 Milk"}


@bp.route("/dunk", methods=["GET", "POST"])
@agent_required
@features.required("dunk")
def dunk_page():
    if request.method == "POST":
        b = db.get_biscuit(request.form.get("biscuit_id", type=int) or 0)
        try:  # the JS timer and the no-JS fallback share a name; take whichever was filled in
            seconds = float(next((v for v in request.form.getlist("seconds") if v.strip()), ""))
        except ValueError:
            seconds = -1
        drink = request.form.get("drink", "tea")
        # 0.3 s floor: a human can't tap faster; 900 s cap: anything longer means they wandered off.
        if b is None or not b["active"] or not 0.3 <= seconds <= 900 or drink not in DRINKS:
            flash("That dunk didn't register. Try again (and keep it under 15 minutes).", "error")
        else:
            db.add_dunk(g.member["id"], b["id"], seconds, drink)
            verdict = ("Instant collapse. Tragic." if seconds < 3 else "Respectable." if seconds < 10
                       else "Heroic structural integrity!" if seconds < 30 else "Is it even a biscuit?! 🛟")
            flash(f"💦 {b['name']} lasted {seconds:.1f}s in {DRINKS[drink].split(' ', 1)[1].lower()}. {verdict}", "celebrate")
        return redirect(url_for("views.dunk_page"))
    return render_template("dunk.html", biscuits=[b for b in db.list_biscuits(None) if b["active"]],
                           drinks=DRINKS, fame=db.dunk_hall_of_fame(), by_biscuit=db.dunk_by_biscuit())


# --- Biscuit VS ------------------------------------------------------------------------

def _duel_or_404(duel_id: int):
    d = db.get_duel(duel_id)
    if d is None:
        abort(404)
    return d


@bp.get("/arena")
@agent_required
@features.required("vs")
def arena():
    me_id = g.member["id"]
    mine = db.list_duels(me_id)
    states = {}
    for d in mine:
        if d["status"] == "active":
            states[d["id"]] = duel.build_state(d["challenger_id"], d["opponent_id"], db.duel_moves(d["id"]))
    opponents = [m for m in db.list_members() if m["active"] and m["id"] != me_id]
    ious = [d for d in db.list_duels(None, 200) if d["status"] == "done" and d["biscuit_iou"]
            and d["winner_id"] and not d["iou_paid"]]
    return render_template("arena.html", duels=mine, states=states, opponents=opponents, ious=ious,
                           balance=balance(me_id), max_wager=duel.MAX_WAGER, records=db.duel_records(),
                           recent=[d for d in db.list_duels(None, 12) if d["status"] == "done"], moves=duel.MOVES)


@bp.post("/arena/challenge")
@agent_required
@features.required("vs")
def challenge():
    me_id = g.member["id"]
    back = redirect(url_for("views.arena"))
    opp = db.get_member(request.form.get("opponent_id", type=int) or 0)
    wager = request.form.get("wager", type=int) or 0
    if opp is None or not opp["active"] or opp["id"] == me_id:
        flash("Pick a worthy opponent (not yourself, tempting as it is).", "error")
        return back
    if not 0 <= wager <= duel.MAX_WAGER:
        flash(f"Wagers go from 0 to {duel.MAX_WAGER} points.", "error")
        return back
    if wager > balance(me_id):
        flash("You can't bet points you don't have. Nice try.", "error")
        return back
    duel_id = db.create_duel(me_id, opp["id"], wager, bool(request.form.get("biscuit_iou")))
    flash(f"⚔️ Gauntlet thrown at {opp['name']}! {f'{wager} points on the line.' if wager else 'For honour alone.'}", "celebrate")
    return redirect(url_for("views.duel_page", duel_id=duel_id))


@bp.get("/duel/<int:duel_id>")
@agent_required
@features.required("vs")
def duel_page(duel_id: int):
    d = _duel_or_404(duel_id)
    st = duel.build_state(d["challenger_id"], d["opponent_id"], db.duel_moves(duel_id))
    me_id = g.member["id"]
    return render_template("duel.html", d=d, st=st, moves=duel.MOVES, me_in=me_id in (d["challenger_id"], d["opponent_id"]),
                           my_turn=d["status"] == "active" and me_id in st.waiting_on,
                           can_afford=balance(me_id) >= d["wager"])


@bp.post("/duel/<int:duel_id>/<action>")
@agent_required
@features.required("vs")
def duel_action(duel_id: int, action: str):
    d = _duel_or_404(duel_id)
    me_id = g.member["id"]
    back = redirect(url_for("views.duel_page", duel_id=duel_id))
    if action == "accept" and me_id == d["opponent_id"]:
        if balance(me_id) < d["wager"]:
            flash(f"You need {d['wager']} points to match the stake.", "error")
        elif db.accept_duel(duel_id, me_id, d["wager"]):
            flash("Challenge accepted. Choose your weapon. 🫖💥🍪", "celebrate")
    elif action in ("decline", "cancel") and me_id == (d["opponent_id"] if action == "decline" else d["challenger_id"]):
        if db.close_pending_duel(duel_id, "declined" if action == "decline" else "cancelled"):
            flash("Duel called off. Stakes returned.", "info")
        return redirect(url_for("views.arena"))
    elif action == "paid" and me_id == d["winner_id"]:
        db.mark_iou_paid(duel_id, me_id)
        flash("Biscuit debt settled. Honour restored. 🍪🤝", "celebrate")
    elif action == "move":
        move = request.form.get("move", "")
        st = duel.build_state(d["challenger_id"], d["opponent_id"], db.duel_moves(duel_id))
        if d["status"] != "active" or me_id not in st.waiting_on or move not in duel.MOVES:
            abort(400)
        db.add_move(duel_id, st.current, me_id, move)
        st = duel.build_state(d["challenger_id"], d["opponent_id"], db.duel_moves(duel_id))
        if st.finished and db.finish_duel(duel_id, st.winner):
            if st.winner == me_id:
                flash(f"🏆 VICTORY! {'+' + str(2 * d['wager']) + ' points. ' if d['wager'] else ''}"
                      f"{'And they owe you a packet of biscuits. ' if d['biscuit_iou'] else ''}", "celebrate")
            elif st.winner is None:
                flash("A draw! Stakes returned. The tin remains undecided.", "info")
            else:
                flash("Defeat. The crumbs settle. 😔" + (" Better go buy those biscuits." if d["biscuit_iou"] else ""), "info")
        elif not st.finished and me_id in st.waiting_on:
            flash(st.rounds[-1].line if st.rounds else "Move locked in.", "info")  # round resolved, go again
        else:
            flash("Move locked in. Waiting for your opponent… 🤫", "info")
    else:
        abort(403)
    return back


@bp.post("/shop/equip/<slot>")
@agent_required
@features.required("shop")
def shop_equip(slot: str):
    if slot not in shop.SLOTS:
        abort(404)
    item_key = request.form.get("item_key", "")
    if item_key:
        item = shop.BY_KEY.get(item_key)
        if item is None or item.slot != slot or item_key not in db.owned_items(g.member["id"]):
            abort(400)
    db.equip(g.member["id"], slot, item_key or None)
    return redirect(url_for("views.shop_page") + f"#{slot}")


def _radar_shops(site: dict) -> list[dict]:
    """Active shops with distance, bearing, radar position and their current prices, nearest first."""
    prices: dict[int, list] = {}
    for p in db.current_prices():
        prices.setdefault(p["shop_id"], []).append(p)
    out = []
    for s in db.list_shops():
        km = radar.distance_km(site["lat"], site["lng"], s["lat"], s["lng"])
        x, y = radar.radar_xy(km, radar.bearing_deg(site["lat"], site["lng"], s["lat"], s["lng"]))
        out.append({**dict(s), "km": km, "walk_min": round(km * radar.WALK_MIN_PER_KM), "x": x, "y": y,
                    "outside": km > radar.RADAR_KM, "prices": prices.get(s["id"], []),
                    "maps": radar.maps_url(s["lat"], s["lng"])})
    return sorted(out, key=lambda s: s["km"])


@bp.get("/radar")
@agent_required
@features.required("radar")
def radar_page():
    site = radar.load_site(current_app.config["DATA_DIR"])
    shops = _radar_shops(site) if site else []
    cheapest: dict[str, dict] = {}
    for s in shops:
        for p in s["prices"]:
            if p["biscuit"] not in cheapest or p["pence"] < cheapest[p["biscuit"]]["pence"]:
                cheapest[p["biscuit"]] = {"pence": p["pence"], "shop": s["name"], "km": s["km"], "shop_id": s["id"]}
    return render_template("radar.html", site=site, shops=shops, rings=radar.RINGS_KM, radar_km=radar.RADAR_KM,
                           cheapest=sorted(cheapest.items()), fmt=radar.fmt_price,
                           biscuits=[b for b in db.list_biscuits(None) if b["active"]])


@bp.post("/radar/price")
@agent_required
@features.required("radar")
def radar_price():
    back = redirect(url_for("views.radar_page") + "#prices")
    try:
        shop_id, biscuit_id = int(request.form.get("shop_id", 0)), int(request.form.get("biscuit_id", 0))
        pence = radar.parse_price(request.form.get("price", ""))
    except ValueError as e:  # RadarError is a ValueError; so is a non-numeric id
        flash(str(e) if isinstance(e, radar.RadarError) else "Pick a shop and a biscuit.", "error")
        return back
    shop_row, b = db.get_shop(shop_id), db.get_biscuit(biscuit_id)
    if shop_row is None or not shop_row["active"] or b is None or not b["active"]:
        flash("Pick a shop and a biscuit from the lists.", "error")
        return back
    db.add_price(shop_id, biscuit_id, pence, request.form.get("pack", "").strip()[:40], g.member["id"])
    flash(f"Logged: {b['name']} at {shop_row['name']} for {radar.fmt_price(pence)}. Intel received. 💷", "celebrate")
    return redirect(url_for("views.radar_page") + f"#shop-{shop_id}")


@bp.post("/radar/shop")
@agent_required
@features.required("radar")
def radar_add_shop():
    back = redirect(url_for("views.radar_page") + "#add-shop")
    name = request.form.get("name", "").strip()[:80]
    if not name:
        flash("A shop needs a name.", "error")
        return back
    try:
        postcode = radar.normalise_postcode(request.form.get("postcode", ""))
        lat, lng = radar.postcode_lookup(postcode)
    except radar.RadarError as e:
        flash(str(e), "error")
        return back
    shop_id = db.add_shop({"name": name, "lat": lat, "lng": lng, "postcode": postcode, "kind": "added"},
                          g.member["id"])
    flash(f"{name} is on the radar. 🛰️", "celebrate")
    return redirect(url_for("views.radar_page") + f"#shop-{shop_id}")


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
    today = date.today()
    # `scored`: biscuits whose *scores* this viewer may see. Names and places show for everyone.
    scored = {b["id"] for b in db.list_biscuits(g.member["id"]) if cases.can_see(b, b["mine"], today)}
    data = db.awards_data()
    # An agent's "avg given" over *all* their reports leaks sealed scores (1 report + a public
    # Soulmate name = that biscuit's score). So average only over biscuits this viewer can see.
    visible_vals: dict[int, list[int]] = {}
    for r in data["ratings"]:
        if r["biscuit_id"] in scored:
            visible_vals.setdefault(r["member_id"], []).extend(r["scores"].values())
    given = {m: sum(v) / len(v) for m, v in visible_vals.items() if v}
    return render_template("leaderboard.html", ranked=db.leaderboard(), agents=db.agent_stats(),
                           awards=awards.compute(data), scored=scored, given=given)


@bp.get("/uploads/<path:filename>")
def upload(filename: str):
    # send_from_directory rejects ../ traversal. Photos aren't secret, so no agent check:
    # the admin page (no agent cookie on 127.0.0.1) needs them too.
    return send_from_directory(current_app.config["UPLOAD_DIR"], filename, max_age=86400)
