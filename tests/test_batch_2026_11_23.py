"""2026-11-23 batch: Who Said That? stops repeating (#14, #15), coffee corner in the shop (#13)."""
import random

from app import shop, whosaid


def _quotes(n):
    return [{"id": i, "member_id": 100 + i} for i in range(1, n + 1)]


def test_every_quote_before_any_repeat():
    rng, quotes, seen, shown = random.Random(7), _quotes(12), {}, []
    for round_id in range(1, 13):
        q = whosaid.choose_quote(quotes, seen, rng)
        shown.append(q["id"])
        seen[q["id"]] = round_id
    assert sorted(shown) == list(range(1, 13))           # 12 rounds, 12 different quotes


def test_repeats_come_from_the_stalest_half():
    rng, quotes = random.Random(3), _quotes(10)
    seen = {q["id"]: q["id"] for q in quotes}             # quote 1 seen longest ago, 10 most recently
    for _ in range(200):
        assert whosaid.choose_quote(quotes, seen, rng)["id"] <= 5


def test_never_the_same_quote_twice_in_a_row():
    rng, quotes, seen, last = random.Random(1), _quotes(3), {}, None
    for round_id in range(1, 60):
        q = whosaid.choose_quote(quotes, seen, rng)
        assert q["id"] != last
        seen[q["id"]], last = round_id, q["id"]


def test_coffee_corner_is_stocked():
    coffee = [i for i in shop.FOR_SALE if i.key in {
        "title-barista", "color-espresso", "frame-coffee-ring", "fx-steam", "badge-beans", "banner-coffeeshop"}]
    assert len(coffee) == 6
    assert {i.slot for i in coffee} == set(shop.SLOTS)    # something coffee in every slot


# --- case-opening reel and the Tony easter egg ------------------------------------------------

def test_reel_always_lands_on_the_real_prize():
    from app import loot
    rng = random.Random(5)
    for tier in ("uncommon", "rare", "epic", "legendary"):
        item = next(i for i in shop.CATALOGUE if i.loot_tier == tier)
        reel = loot.build_reel(tier, item, 0, rng)
        assert len(reel) == loot.REEL_LENGTH
        assert reel[loot.REEL_STOP] == loot.reel_card(tier, item)
    common = loot.build_reel("common", None, 33, rng)
    assert common[loot.REEL_STOP]["name"] == "+33 points"


def test_tin_page_renders_the_reel_once(app, client, agent_token, monkeypatch):
    from app import db as brtdb
    from app import loot
    with app.app_context():
        for n in range(6):
            brtdb.add_biscuit(f"Spec {n}", "", None, 1)
    monkeypatch.setattr(loot, "roll_tier", lambda rng: "rare")
    client.post("/loot")
    page = client.get("/loot").data.decode()
    assert page.count('class="case-card') == loot.REEL_LENGTH and 'data-stop="40"' in page
    assert "data-reel" not in client.get("/loot").data.decode()     # refresh: no replay


def test_tony_easter_egg_is_wired_up():
    from pathlib import Path
    js = Path("app/static/js/brt.js").read_text(encoding="utf-8")
    assert "Math.random() < 0.01" in js and "tony=1" in js and "tony-run" in js
