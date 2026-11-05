"""Dry Land Purists: non-dunkers skip the dunk pair, stored as no score, one agent one vote."""
import pytest

from app import awards
from app import db as brtdb
from app.scoring import CATEGORY_KEYS, PURIST_FIELD, SKIPPABLE_KEYS

from .conftest import count, scores


def dry(value: int) -> dict[str, str]:
    form = {k: v for k, v in scores(value).items() if k not in SKIPPABLE_KEYS}
    return {**form, PURIST_FIELD: "1"}


@pytest.fixture
def second(app):
    with app.app_context():
        token = brtdb.add_member("Dunker", "🫖")
    c = app.test_client()
    c.get(f"/join/{token}")
    return c


def test_dunk_pair_is_what_skips():
    assert SKIPPABLE_KEYS == ("dunk_better", "dunk_resist")


def test_purist_rating_stores_no_dunk_scores(app, client, agent_token, biscuit_id):
    client.post(f"/b/{biscuit_id}/rate", data=dry(4))
    assert count(app, "SELECT COUNT(*) FROM ratings") == 1
    assert count(app, "SELECT COUNT(*) FROM scores") == len(CATEGORY_KEYS) - 2
    assert count(app, "SELECT COUNT(*) FROM scores WHERE category LIKE 'dunk%'") == 0


def test_missing_dunk_without_tick_is_rejected(app, client, agent_token, biscuit_id):
    form = dry(4)
    del form[PURIST_FIELD]
    client.post(f"/b/{biscuit_id}/rate", data=form)
    assert count(app, "SELECT COUNT(*) FROM ratings") == 0


def test_switching_to_purist_clears_old_dunk_scores(app, client, agent_token, biscuit_id):
    client.post(f"/b/{biscuit_id}/rate", data=scores(5))
    client.post(f"/b/{biscuit_id}/rate", data=dry(5))
    assert count(app, "SELECT COUNT(*) FROM scores WHERE category LIKE 'dunk%'") == 0
    page = client.get(f"/b/{biscuit_id}").data.decode()
    assert "Dry Land Purist" in page and 'name="dry_purist" value="1" data-purist checked' in page


def test_tick_wins_even_if_dunk_scores_sent(app, client, agent_token, biscuit_id):
    client.post(f"/b/{biscuit_id}/rate", data={**scores(3), PURIST_FIELD: "1"})
    assert count(app, "SELECT COUNT(*) FROM scores WHERE category LIKE 'dunk%'") == 0


def test_overall_is_one_agent_one_vote(app, client, agent_token, biscuit_id, second):
    second.post(f"/b/{biscuit_id}/rate", data=scores(5))  # 10 scores, average 5
    client.post(f"/b/{biscuit_id}/rate", data=dry(1))     # 8 scores, average 1
    with app.app_context():
        b = brtdb.get_biscuit(biscuit_id)
        board = brtdb.leaderboard()
    # Per-rating mean: (5 + 1) / 2 = 3.0. Raw score-row mean would be (50 + 8) / 18 = 3.22.
    assert b["overall"] == pytest.approx(3.0)
    assert board[0]["overall"] == pytest.approx(3.0)


def test_purist_award_and_dunk_lord_ignores_purists():
    agents = [{"id": 1, "name": "Dry", "avatar": "🏜️", "n": 2, "given": 0, "added": 0},
              {"id": 2, "name": "Wet", "avatar": "🫖", "n": 2, "given": 0, "added": 0}]

    def rating(rid, member, biscuit, purist):
        s = {k: 3 for k in CATEGORY_KEYS if not (purist and k in SKIPPABLE_KEYS)}
        return {"id": rid, "member_id": member, "member": "", "avatar": "", "biscuit_id": biscuit,
                "biscuit": f"B{biscuit}", "comment_len": 0, "created_at": "2026-11-05", "scores": s}

    ratings = [rating(1, 1, 1, True), rating(2, 1, 2, True), rating(3, 2, 1, False), rating(4, 2, 2, False)]
    got = {a["title"]: a for a in awards.agent_awards(ratings, agents)}
    assert got["The Purist"]["winners"] == ["🏜️ Dry"]
    assert "Dunk Lord" not in got  # only one agent has dunk scores, and it needs two to compare
