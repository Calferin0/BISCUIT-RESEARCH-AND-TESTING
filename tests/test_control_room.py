"""Control-room powers (feature switches, grants, removals, duel voids), the Locker, and the
points-page balance regression (it ignored the ledger, so Mystery Tins didn't show)."""
import pytest

from app import db as brtdb
from app import loot

from .conftest import count


@pytest.fixture
def rich(app, client, agent_token):
    """Tester with 60 earned points (4 logged biscuits)."""
    with app.app_context():
        for n in "ABCD":
            brtdb.add_biscuit(f"Specimen {n}", "", None, 1)
    return client


def test_points_page_balance_includes_tins(app, rich, monkeypatch):
    monkeypatch.setattr(loot, "roll_tier", lambda rng: "epic")       # epic = item, no refund
    rich.post("/loot")
    page = rich.get("/points").data.decode()
    assert f'class="points-big">{60 - loot.BOX_COST}<' in page        # was 60 before the fix
    assert "Mystery Tin" in page                                     # listed in ins and outs


def test_feature_switch_hides_and_closes(app, client, agent_token):
    client.post("/admin/features", data={"on": ["radar", "vs", "loot", "shop", "horoscope", "estop"]})  # dunk off
    assert client.get("/dunk").status_code == 404
    assert "Dunk-O-Meter" not in client.get("/dashboard").data.decode()
    client.post("/admin/features", data={"on": ["radar", "vs", "loot", "shop", "horoscope", "estop", "dunk"]})
    assert client.get("/dunk").status_code == 200
    client.post("/admin/features", data={"on": []})                  # everything off
    page = client.get("/").data.decode()
    assert "data-estop" not in page and ">VS<" not in page and ">Radar<" not in page
    assert client.get("/arena").status_code == 404 and client.get("/locker").status_code == 200


def test_grant_points_shows_for_agent(app, client, agent_token):
    client.post("/admin/points", data={"member_id": 1, "amount": 50, "reason": "Brought shortbread"})
    client.post("/admin/points", data={"member_id": 1, "amount": 5000, "reason": "too much"})   # over the cap
    client.post("/admin/points", data={"member_id": 1, "amount": 0})
    assert count(app, "SELECT SUM(delta) FROM ledger") == 50
    assert "Brought shortbread" in client.get("/points").data.decode()
    assert "🪙 50" in client.get("/").data.decode()
    lan = {"REMOTE_ADDR": "192.168.1.50"}
    assert client.post("/admin/points", data={"member_id": 1, "amount": 50}, environ_base=lan).status_code == 403


def test_remove_dunk(app, client, agent_token, biscuit_id):
    client.post("/dunk", data={"biscuit_id": biscuit_id, "seconds": "42", "drink": "tea"})
    client.post("/admin/dunks/1/toggle")
    client.get("/dunk")
    assert "42.0s" not in client.get("/dunk").data.decode()
    assert count(app, "SELECT COUNT(*) FROM dunks") == 1                 # soft: still there


def test_void_active_duel_refunds_both(app, rich):
    with app.app_context():
        rival = brtdb.add_member("Rival", "🦊")
        for n in "XY":
            brtdb.add_biscuit(f"R{n}", "", None, 2)
    c2 = rich.application.test_client()
    c2.get(f"/join/{rival}")
    rich.post("/arena/challenge", data={"opponent_id": 2, "wager": 20, "biscuit_iou": "1"})
    c2.post("/duel/1/accept")
    rich.post("/admin/duels/1/void")
    assert count(app, "SELECT SUM(delta) FROM ledger WHERE member_id = 1") == 0
    assert count(app, "SELECT SUM(delta) FROM ledger WHERE member_id = 2") == 0
    assert count(app, "SELECT status FROM duels") == "cancelled"


def test_admin_price_list_retract(app, client, agent_token, biscuit_id):
    with app.app_context():
        shop_id = brtdb.add_shop({"name": "Corner", "lat": 51.5, "lng": -2.4}, None)
        brtdb.add_price(shop_id, biscuit_id, 150, "", 1)
    assert "Corner" in client.get("/admin/").data.decode()
    client.post("/admin/prices/1", data={"action": "toggle", "back": "list", "biscuit_id": biscuit_id})
    with app.app_context():
        assert brtdb.current_prices() == []


def test_rarity_reset(app, client, agent_token, biscuit_id):
    client.post(f"/b/{biscuit_id}/rarity", data={"tier": "legendary"})
    client.post(f"/admin/biscuits/{biscuit_id}/rarity-reset")
    assert count(app, "SELECT COUNT(*) FROM rarity_votes") == 0


def test_locker_shows_inventory_equips_and_avatar(app, rich, monkeypatch):
    rich.post("/shop/buy/color-custard")
    monkeypatch.setattr(loot, "roll_tier", lambda rng: "legendary")
    rich.post("/loot")                                                # 30 left after buying: tin costs 40
    page = rich.get("/locker").data.decode()
    assert "Custard Cream" in page and "bought for 30 pts" in page
    rich.post("/locker/equip/color", data={"item_key": ""})
    assert count(app, "SELECT COUNT(*) FROM equipped WHERE slot = 'color'") == 0
    rich.post("/locker/equip/color", data={"item_key": "color-custard"})
    assert count(app, "SELECT COUNT(*) FROM equipped WHERE slot = 'color'") == 1
    assert rich.post("/locker/equip/color", data={"item_key": "color-party"}).status_code == 400   # not owned
    rich.post("/locker/avatar", data={"avatar": "🦉"})
    with app.app_context():
        assert brtdb.get_member(1)["avatar"] == "🦉"
    assert rich.post("/locker/avatar", data={"avatar": "💩"}).status_code == 400
