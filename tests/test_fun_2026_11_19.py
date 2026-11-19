"""2026-11-19 fun batch: kinder tins (#10), new flair slots, the Agent catwalk,
the Ten Biscuit Commandments (#12) and Who Said That?"""
import random

import pytest

from app import db as brtdb
from app import loot, shop, whosaid

from .conftest import count, scores


def _agent(app, name, avatar="🦊"):
    with app.app_context():
        token = brtdb.add_member(name, avatar)
    c = app.test_client()
    c.get(f"/join/{token}")
    return c


def _make_public(app, biscuit_id):
    with app.app_context():
        conn = brtdb.get_db()
        conn.execute("UPDATE biscuits SET created_at = datetime('now', '-8 days') WHERE id = ?", (biscuit_id,))
        conn.commit()


# --- Mystery Tins ------------------------------------------------------------------------

def test_every_slot_has_tin_loot_in_every_tier():
    for tier in ("uncommon", "rare", "epic", "legendary"):
        assert {i.slot for i in shop.CATALOGUE if i.loot_tier == tier} >= {"title", "badge", "banner"}
    assert sum(1 for _, p in loot.ODDS if _ != "common") > 0
    assert dict(loot.ODDS)["common"] <= 30          # most tins hold a cosmetic


def test_new_items_before_duplicates():
    rng = random.Random(1)
    owned: set[str] = set()
    rare = [i.key for i in shop.CATALOGUE if i.loot_tier == "rare"]
    for _ in rare:   # one pull per rare item: every one is new
        monkey = loot.open_tin(owned, _Forced("rare", rng))
        assert not monkey.duplicate
        owned.add(monkey.item.key)
    assert set(rare) <= owned
    assert loot.open_tin(owned, _Forced("rare", rng)).duplicate   # only now


class _Forced(random.Random):
    def __init__(self, tier, base):
        super().__init__(base.random())
        self.tier = tier

    def choices(self, population, weights=None, k=1):
        return [self.tier] if self.tier in population else super().choices(population, weights=weights, k=k)


def test_pity_timer_guarantees_rare_or_better():
    rng = random.Random(0)
    assert not loot.pity_due(loot.PITY - 2)
    assert loot.pity_due(loot.PITY - 1)
    for _ in range(200):
        assert loot.open_tin(set(), rng, dry_streak=loot.PITY - 1).tier in loot.GOOD_TIERS


def test_dry_streak_counts_from_last_good_pull(app, client, agent_token, monkeypatch):
    with app.app_context():
        for n in range(30):
            brtdb.add_biscuit(f"Spec {n}", "", None, 1)     # 450 points to play with
    for tier in ("common", "uncommon", "rare", "common", "common"):
        monkeypatch.setattr(loot, "roll_tier", lambda rng, t=tier: t)
        client.post("/loot")
    with app.app_context():
        assert brtdb.tin_dry_streak(1, loot.GOOD_TIERS) == 2
    assert "Lucky meter" in client.get("/loot").data.decode()


# --- flair: effects, badges, banners -------------------------------------------------------

def test_new_slots_render_everywhere(app, client, agent_token):
    with app.app_context():
        for n in range(20):
            brtdb.add_biscuit(f"Spec {n}", "", None, 1)
    for key in ("fx-glow", "badge-crown", "banner-teatime"):
        client.post(f"/shop/buy/{key}")
    assert count(app, "SELECT COUNT(*) FROM equipped") == 3
    page = client.get("/agent/1").data.decode()
    assert "fx-glow" in page and "👑" in page and "banner-teatime" in page
    assert "fx-glow" in client.get("/agents").data.decode()
    assert "Profile banners" in client.get("/shop").data.decode()


# --- the Agent catwalk ---------------------------------------------------------------------

def test_catwalk_shows_every_agent_with_their_awards(app, client, agent_token, biscuit_id):
    _agent(app, "Other")
    client.post(f"/b/{biscuit_id}/rate", data={**scores(5), "comment": "Fine work"})
    page = client.get("/agents").data.decode()
    assert "Agent Tester" in page and "Agent Other" in page
    assert "Lead Investigator" in page                      # Tester's award, on their card
    assert "Agents</a>" in page                             # in the top bar


# --- the Ten Biscuit Commandments ----------------------------------------------------------

def test_commandments_propose_vote_and_become_law(app, client, agent_token):
    other = _agent(app, "Other")
    client.post("/commandments", data={"body": "Thou shalt not double-dip"})
    client.post("/commandments", data={"body": "x"})                         # too short
    assert count(app, "SELECT COUNT(*) FROM commandments") == 1
    client.post("/commandments/1/vote")                                       # own: refused
    assert count(app, "SELECT COUNT(*) FROM commandment_votes") == 0
    page = client.get("/commandments").data.decode()
    assert page.count("awaiting a worthy commandment") == 10                  # empty tablet: ten vacancies
    other.post("/commandments/1/vote")
    page = client.get("/commandments").data.decode()
    tablet = page.split('class="tablet"')[1].split("</section>")[0]
    assert "Thou shalt not double-dip" in tablet                               # now law
    other.post("/commandments/1/vote")                                         # un-vote
    assert count(app, "SELECT COUNT(*) FROM commandment_votes") == 0


def test_only_ten_are_law_and_withdraw_and_strike(app, client, agent_token):
    other = _agent(app, "Other")
    for n in range(12):
        other.post("/commandments", data={"body": f"Commandment number {n:02d}"})
        client.post(f"/commandments/{n + 1}/vote")
    page = client.get("/commandments").data.decode()
    tablet = page.split('class="tablet"')[1].split("</section>")[0]
    assert tablet.count("law-body") == 10
    other.post("/commandments", data={"body": "Withdraw me please"})
    other.post("/commandments/13/withdraw")
    assert count(app, "SELECT COUNT(*) FROM commandments") == 12
    assert client.post("/commandments/1/strike", environ_base={"REMOTE_ADDR": "192.168.1.50"}).status_code == 403
    client.post("/commandments/1/strike")                                       # test client = 127.0.0.1
    assert count(app, "SELECT COUNT(*) FROM commandments WHERE active = 0") == 1


# --- Who Said That? ------------------------------------------------------------------------

def _quote_setup(app, client, biscuit_id, public=True):
    other = _agent(app, "Other")
    _agent(app, "Decoy", "🐻")
    other.post(f"/b/{biscuit_id}/rate", data={**scores(3), "comment": "Tastes like a damp Tuesday afternoon"})
    if public:
        _make_public(app, biscuit_id)
    return other


def test_whosaid_respects_blind_rating(app, client, agent_token, biscuit_id):
    _quote_setup(app, client, biscuit_id, public=False)
    page = client.get("/whosaid").data.decode()
    assert "damp Tuesday" not in page and "Nothing to quote yet" in page        # sealed case (D10)


def test_whosaid_never_quotes_you(app, client, agent_token, biscuit_id):
    client.post(f"/b/{biscuit_id}/rate", data={**scores(3), "comment": "My own very long field note here"})
    _agent(app, "Other")
    _make_public(app, biscuit_id)
    assert "My own very long field note" not in client.get("/whosaid").data.decode()


def test_whosaid_round_pays_once_and_answer_not_in_page(app, client, agent_token, biscuit_id):
    _quote_setup(app, client, biscuit_id)
    page = client.get("/whosaid").data.decode()
    assert "damp Tuesday" in page
    with app.app_context():
        rnd = brtdb.open_whosaid(1)
        author = rnd["author_id"]
    assert "correct" not in page.split("guess-grid")[1].split("</form>")[0]     # no tell in the buttons
    client.post("/whosaid", data={"round": rnd["id"], "guess": author})
    client.post("/whosaid", data={"round": rnd["id"], "guess": author})       # double tap
    assert count(app, "SELECT COALESCE(SUM(delta), 0) FROM ledger WHERE reason = 'Who Said That?'") == whosaid.REWARD
    assert count(app, "SELECT COUNT(*) FROM whosaid_rounds WHERE guess_id IS NOT NULL") == 1


def test_whosaid_rejects_a_guess_not_on_the_card(app, client, agent_token, biscuit_id):
    _quote_setup(app, client, biscuit_id)
    client.get("/whosaid")
    with app.app_context():
        rnd = brtdb.open_whosaid(1)
    assert client.post("/whosaid", data={"round": rnd["id"], "guess": 999}).status_code == 400


def test_whosaid_reward_cap_and_streaks():
    assert whosaid.reward_for(True, 0) == whosaid.REWARD
    assert whosaid.reward_for(True, whosaid.DAILY_CAP) == 0
    assert whosaid.reward_for(False, 0) == 0
    hist = [{"correct": c} for c in (1, 1, 0, 1, 1, 1, 0)]   # newest first
    assert whosaid.streaks(hist) == (2, 3)


@pytest.mark.parametrize("path", ["/commandments", "/whosaid", "/agents"])
def test_new_pages_need_an_agent(client, path):
    assert client.get(path).status_code == 403
