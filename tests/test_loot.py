"""Mystery Tins: odds, duplicate conversion, ledger accounting, loot-only items."""
import random

import pytest

from app import db as brtdb
from app import loot, shop

from .conftest import count


class FixedRng(random.Random):
    """Forces the tier roll; everything else stays deterministic."""
    def __init__(self, tier):
        super().__init__(0)
        self.tier = tier

    def choices(self, population, weights=None, k=1):
        return [self.tier] if self.tier in population else super().choices(population, weights=weights, k=k)


@pytest.fixture
def rich(app, client, agent_token):
    """Tester with 90 points: 6 logged biscuits."""
    with app.app_context():
        for n in "ABCDEF":
            brtdb.add_biscuit(f"Specimen {n}", "", None, 1)
    return client


def test_odds_sum_to_100_and_every_tier_has_items():
    assert sum(p for _, p in loot.ODDS) == pytest.approx(100)
    for tier, _ in loot.ODDS:
        if tier != "common":
            assert any(i.loot_tier == tier for i in shop.CATALOGUE)
    assert 0 < loot.expected_value() < loot.BOX_COST          # the tin always wins


def test_common_is_points_and_dupes_convert():
    p = loot.open_tin(set(), FixedRng("common"))
    assert p.item is None and loot.COMMON_REFUND[0] <= p.points <= loot.COMMON_REFUND[1]
    rare_keys = {i.key for i in shop.CATALOGUE if i.loot_tier == "rare"}
    dup = loot.open_tin(rare_keys, FixedRng("rare"))
    assert dup.duplicate and dup.points == loot.DUPE_POINTS["rare"]


def test_open_tin_charges_and_grants(app, rich, monkeypatch):
    monkeypatch.setattr(loot, "roll_tier", lambda rng: "epic")
    rich.post("/loot")
    assert count(app, "SELECT COUNT(*) FROM purchases WHERE source = 'loot'") == 1
    assert count(app, "SELECT SUM(delta) FROM ledger") == -loot.BOX_COST
    assert 'id="reveal"' in rich.get("/loot").data.decode()        # the reveal shows once...
    assert 'id="reveal"' not in rich.get("/loot").data.decode()    # ...and a refresh doesn't replay it
    assert f"🪙 {90 - loot.BOX_COST}" in rich.get("/shop").data.decode()


def test_cannot_afford_and_cannot_buy_loot(app, client, agent_token):
    client.post("/loot")
    assert count(app, "SELECT COUNT(*) FROM ledger") == 0       # 0 points: refused
    assert client.post("/shop/buy/loot-title-oracle").status_code == 404


def test_loot_items_can_be_worn(app, rich, monkeypatch):
    monkeypatch.setattr(loot, "roll_tier", lambda rng: "legendary")
    rich.post("/loot")
    with app.app_context():
        key = next(iter(brtdb.owned_items(1)))
    item = shop.BY_KEY[key]
    rich.post(f"/shop/equip/{item.slot}", data={"item_key": key})
    assert count(app, f"SELECT COUNT(*) FROM equipped WHERE item_key = '{key}'") == 1
