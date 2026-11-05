"""Rarity (team vote + admin pin) and the control room's edit pages."""
from app import db as brtdb
from app import rarity

from .conftest import count


def test_decide_mode_ties_go_rarer_and_override_wins():
    assert rarity.decide([]) is None
    assert rarity.decide(["common", "rare", "rare"]).key == "rare"
    assert rarity.decide(["common", "epic"]).key == "epic"            # tie -> rarer
    assert rarity.decide(["common"], override="legendary").key == "legendary"
    assert rarity.decide(["nonsense"]) is None


def test_vote_and_change_vote(app, client, agent_token, biscuit_id):
    client.post(f"/b/{biscuit_id}/rarity", data={"tier": "rare"})
    client.post(f"/b/{biscuit_id}/rarity", data={"tier": "epic"})     # one vote per agent, changed
    assert count(app, "SELECT COUNT(*) FROM rarity_votes") == 1
    client.get("/")
    assert "Epic" in client.get("/").data.decode()
    assert client.post(f"/b/{biscuit_id}/rarity", data={"tier": "mythic"}).status_code == 400


def test_logger_pick_is_first_vote(app, client, agent_token):
    client.post("/add", data={"name": "Fig Roll", "tier": "uncommon"})
    assert count(app, "SELECT COUNT(*) FROM rarity_votes WHERE tier = 'uncommon'") == 1


def test_admin_edit_biscuit_and_pin_rarity(app, client, agent_token, biscuit_id):
    with app.app_context():
        brtdb.add_biscuit("Bourbon", "", None, None)
    client.post(f"/admin/biscuits/{biscuit_id}/edit", data={"name": "Hobnob Original", "brand": "McVitie's",
                                                            "rarity_override": "legendary"})
    with app.app_context():
        b = brtdb.get_biscuit(biscuit_id)
    assert b["name"] == "Hobnob Original" and b["rarity_override"] == "legendary"
    client.post(f"/admin/biscuits/{biscuit_id}/edit", data={"name": "Bourbon", "brand": ""})  # clash
    with app.app_context():
        assert brtdb.get_biscuit(biscuit_id)["name"] == "Hobnob Original"
    assert client.get(f"/admin/biscuits/{biscuit_id}/edit").status_code == 200


def test_admin_price_edit_and_retract(app, client, agent_token, biscuit_id):
    with app.app_context():
        shop = brtdb.add_shop({"name": "Corner", "lat": 51.5, "lng": -2.4}, None)
        brtdb.add_price(shop, biscuit_id, 150, "", 1)
        brtdb.add_price(shop, biscuit_id, 999, "", 1)                   # a fat-fingered newer report
    client.post("/admin/prices/2", data={"biscuit_id": biscuit_id, "action": "toggle"})  # retract it
    with app.app_context():
        assert [p["pence"] for p in brtdb.current_prices()] == [150]    # falls back to the older one
    client.post("/admin/prices/1", data={"biscuit_id": biscuit_id, "price": "£1.25", "pack": "300g"})
    with app.app_context():
        assert [(p["pence"], p["pack"]) for p in brtdb.current_prices()] == [(125, "300g")]


def test_admin_rename_shop_and_member(app, client, agent_token):
    with app.app_context():
        shop = brtdb.add_shop({"name": "MS-2", "lat": 51.5, "lng": -2.4}, None)
    client.post(f"/admin/shops/{shop}/rename", data={"name": "Mystery Shop"})
    client.post("/admin/members/1/edit", data={"name": "Testy", "avatar": "🦊"})
    with app.app_context():
        assert brtdb.get_shop(shop)["name"] == "Mystery Shop"
        assert tuple(brtdb.get_member(1))[1:3] == ("Testy", "🦊")
    lan = {"REMOTE_ADDR": "192.168.1.50"}
    assert client.post("/admin/members/1/edit", data={"name": "Hax"}, environ_base=lan).status_code == 403
