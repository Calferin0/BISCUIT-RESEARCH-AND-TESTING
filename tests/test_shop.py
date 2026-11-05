"""Biscuit Shop: buying with earned points, spend ledger, equipping, flair rendering."""
import pytest

from app import db as brtdb
from app import shop

from .conftest import count, scores


@pytest.fixture
def rich(app, client, agent_token):
    """Give Tester 60 points: 4 biscuits logged (15 each)."""
    with app.app_context():
        for name in ("Alpha", "Bravo", "Charlie", "Delta"):
            brtdb.add_biscuit(name, "", None, 1)
    return client


def test_catalogue_is_consistent():
    assert len(shop.BY_KEY) == len(shop.CATALOGUE)
    assert all(i.slot in shop.SLOTS and i.cost > 0 for i in shop.CATALOGUE)


def test_buy_equip_and_balance(app, rich):
    rich.post("/shop/buy/color-custard")                       # 30
    assert count(app, "SELECT COUNT(*) FROM purchases") == 1
    assert count(app, "SELECT COUNT(*) FROM equipped WHERE item_key = 'color-custard'") == 1
    assert "🪙 30" in rich.get("/shop").data.decode()          # 60 earned - 30 spent

    rich.post("/shop/buy/color-custard")                       # double-buy refused
    assert count(app, "SELECT COUNT(*) FROM purchases") == 1
    rich.post("/shop/buy/title-baron")                         # 150 > 30 balance
    assert count(app, "SELECT COUNT(*) FROM purchases") == 1
    assert rich.post("/shop/buy/nonsense").status_code == 404


def test_rank_uses_earned_not_balance(app, rich):
    rich.post("/shop/buy/color-jaffa")                         # spend 40 of 60
    page = rich.get("/points").data.decode()
    assert "Junior Taster" in page and "earned 60 · spent 40" in page


def test_equip_rules(app, rich):
    assert rich.post("/shop/equip/color", data={"item_key": "color-custard"}).status_code == 400  # not owned
    rich.post("/shop/buy/color-custard")
    rich.post("/shop/equip/color", data={"item_key": ""})      # take it off
    assert count(app, "SELECT COUNT(*) FROM equipped") == 0
    assert rich.post("/shop/equip/frame", data={"item_key": "color-custard"}).status_code == 400  # wrong slot
    assert rich.post("/shop/equip/hat", data={"item_key": ""}).status_code == 404


def test_flair_shows_on_reports(app, rich, biscuit_id):
    rich.post("/shop/buy/title-dunkinator")                    # 40
    rich.post(f"/b/{biscuit_id}/rate", data=scores(4))
    page = rich.get(f"/b/{biscuit_id}").data.decode()
    assert "the Dunkinator" in page
