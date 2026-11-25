"""Control-room awards (2026-11-25, the reply to suggestion #18): free cosmetics only admin can give."""
from app import loot, shop

from .conftest import count


def test_awards_are_never_sold_or_looted():
    assert shop.AWARDS
    for item in shop.AWARDS:
        assert item not in shop.FOR_SALE and item.loot_tier is None
    looted = {i.key for t in loot.ODDS for i in shop.CATALOGUE if i.loot_tier == t}
    assert not looted & {i.key for i in shop.AWARDS}


def test_agents_cant_buy_an_award(client, agent_token):
    assert client.post("/shop/buy/award-title-million").status_code == 404
    assert "Asked for a Million" not in client.get("/shop").data.decode()


def test_admin_awards_and_equips_once(app, client, agent_token):
    client.post("/admin/awards", data={"member_id": 1, "item_key": "award-title-million"})
    client.post("/admin/awards", data={"member_id": 1, "item_key": "award-title-million"})  # no double
    assert count(app, "SELECT COUNT(*) FROM purchases WHERE item_key = 'award-title-million' AND source = 'award'") == 1
    assert count(app, "SELECT COUNT(*) FROM equipped WHERE member_id = 1 AND item_key = 'award-title-million'") == 1
    assert count(app, "SELECT COUNT(*) FROM ledger WHERE member_id = 1") == 0          # free: no points move
    assert "Asked for 1,000,000 Points" in client.get("/locker").data.decode()


def test_admin_cant_award_a_shop_item_and_lan_is_refused(app, client, agent_token):
    client.post("/admin/awards", data={"member_id": 1, "item_key": "title-baron"})
    assert count(app, "SELECT COUNT(*) FROM purchases") == 0
    lan = {"REMOTE_ADDR": "192.168.1.50"}
    assert client.post("/admin/awards", data={"member_id": 1, "item_key": "award-badge-million"},
                       environ_base=lan).status_code == 403
