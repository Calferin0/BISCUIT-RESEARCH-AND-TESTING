"""Biscuit VS: rules, escrowed stakes, secret moves, single settlement, biscuit IOUs."""
import pytest

from app import db as brtdb
from app import duel

from .conftest import count


# --- pure rules --------------------------------------------------------------------------

def test_triangle():
    assert duel.beats("dunk", "snap") and duel.beats("snap", "crumble") and duel.beats("crumble", "dunk")
    assert not duel.beats("snap", "dunk")


def test_first_to_two_with_replayed_draws():
    moves = [(1, 1, "dunk"), (1, 2, "dunk"),          # drawn
             (2, 1, "dunk"), (2, 2, "snap"),          # 1 wins
             (3, 1, "crumble"), (3, 2, "snap"),       # 2 wins
             (4, 1, "snap"), (4, 2, "crumble")]       # 1 wins -> 2-1
    st = duel.build_state(1, 2, moves)
    assert st.finished and st.winner == 1 and st.score == {1: 2, 2: 1}
    assert [r.winner for r in st.rounds] == [None, 1, 2, 1]


def test_waiting_on_and_secrecy_of_current_round():
    st = duel.build_state(1, 2, [(1, 1, "dunk")])
    assert st.current == 1 and st.waiting_on == {2} and not st.rounds   # P1's move isn't exposed as a round


def test_max_rounds_draw():
    moves = [(r, p, "dunk") for r in range(1, duel.MAX_ROUNDS + 1) for p in (1, 2)]
    st = duel.build_state(1, 2, moves)
    assert st.finished and st.winner is None


# --- flow ---------------------------------------------------------------------------------

@pytest.fixture
def two(app, client, agent_token):
    """Tester (id 1, 60 pts from 4 logged biscuits) vs Rival (id 2, 30 pts)."""
    with app.app_context():
        for n in "ABCD":
            brtdb.add_biscuit(f"T{n}", "", None, 1)
        rival = brtdb.add_member("Rival", "🦊")
        for n in "AB":
            brtdb.add_biscuit(f"R{n}", "", None, 2)
    c2 = app.test_client()
    c2.get(f"/join/{rival}")
    return client, c2


def play(c, duel_id, move):
    return c.post(f"/duel/{duel_id}/move", data={"move": move})


def test_full_duel_pays_pot_once_and_iou(app, two):
    c1, c2 = two
    c1.post("/arena/challenge", data={"opponent_id": 2, "wager": 20, "biscuit_iou": "1"})
    assert count(app, "SELECT SUM(delta) FROM ledger WHERE member_id = 1") == -20       # stake held
    c2.post("/duel/1/accept")
    assert count(app, "SELECT SUM(delta) FROM ledger WHERE member_id = 2") == -20
    for _ in range(2):                                   # P1 dunk beats P2 snap, twice
        play(c1, 1, "dunk")
        play(c2, 1, "snap")
    with app.app_context():
        d = brtdb.get_duel(1)
    assert d["status"] == "done" and d["winner_id"] == 1
    assert count(app, "SELECT SUM(delta) FROM ledger WHERE member_id = 1") == 20        # -20 + 40
    assert count(app, "SELECT SUM(delta) FROM ledger WHERE member_id = 2") == -20
    assert "owes" in c1.get("/arena").data.decode()
    c1.post("/duel/1/paid")
    assert count(app, "SELECT iou_paid FROM duels") == 1
    assert play(c1, 1, "dunk").status_code == 400                                      # finished: no more moves
    with app.app_context():
        assert brtdb.finish_duel(1, 1) is False                                          # can't settle twice


def test_opponent_cannot_see_pending_move(app, two):
    c1, c2 = two
    c1.post("/arena/challenge", data={"opponent_id": 2, "wager": 0})
    c2.post("/duel/1/accept")
    play(c1, 1, "crumble")
    page = c2.get("/duel/1").data.decode()
    assert "Round by round" not in page and "choose your weapon" in page


def test_decline_and_cancel_refund(app, two):
    c1, c2 = two
    c1.post("/arena/challenge", data={"opponent_id": 2, "wager": 15})
    c2.post("/duel/1/decline")
    c1.post("/arena/challenge", data={"opponent_id": 2, "wager": 15})
    c1.post("/duel/2/cancel")
    assert count(app, "SELECT SUM(delta) FROM ledger WHERE member_id = 1") == 0


def test_guards(app, two):
    c1, c2 = two
    c1.post("/arena/challenge", data={"opponent_id": 1, "wager": 0})                    # self
    c1.post("/arena/challenge", data={"opponent_id": 2, "wager": 999})                  # over cap
    c1.post("/arena/challenge", data={"opponent_id": 2, "wager": 100})                  # can't afford
    assert count(app, "SELECT COUNT(*) FROM duels") == 0
    c1.post("/arena/challenge", data={"opponent_id": 2, "wager": 50})
    c2.post("/duel/1/accept")                                                            # rival has 30 < 50
    assert count(app, "SELECT status FROM duels") == "pending"
    assert c1.post("/duel/1/accept").status_code == 403                                  # not the opponent
