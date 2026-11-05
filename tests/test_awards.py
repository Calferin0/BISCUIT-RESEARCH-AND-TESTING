"""Awards night: pure-function tests over hand-built data."""
from app import awards
from app.scoring import CATEGORY_KEYS


def rating(rid, member_id, biscuit_id, value=None, created="2026-11-05 10:00:00", comment_len=0, **overrides):
    scores = {k: value for k in CATEGORY_KEYS} if value is not None else {}
    scores.update(overrides)
    return {"id": rid, "member_id": member_id, "member": f"M{member_id}", "avatar": "🍪",
            "biscuit_id": biscuit_id, "biscuit": f"B{biscuit_id}", "comment_len": comment_len,
            "created_at": created, "scores": scores}


AGENTS = [
    {"id": 1, "name": "Ada", "avatar": "🦉", "n": 3, "given": 0, "added": 2},
    {"id": 2, "name": "Brunel", "avatar": "🎬", "n": 3, "given": 0, "added": 0},
]


def by_title(cards):
    return {c["title"]: c for c in cards}


def test_agent_awards_happy_vs_critic():
    ratings = [
        rating(1, 1, 1, 5, created="2026-11-05 09:00:00", comment_len=40),
        rating(2, 1, 2, 5, created="2026-11-05 09:00:00"),
        rating(3, 1, 3, 4, created="2026-11-05 09:00:00"),
        rating(4, 2, 1, 1, created="2026-11-05 10:00:00"),
        rating(5, 2, 2, 2, created="2026-11-05 10:00:00"),
        rating(6, 2, 3, 1, created="2026-11-05 10:00:00"),
    ]
    got = by_title(awards.agent_awards(ratings, AGENTS))
    assert got["Easily Pleased"]["winners"] == ["🦉 Ada"]
    assert got["Golden Retriever"]["winners"] == ["🦉 Ada"]
    assert got["The Food Critic"]["winners"] == ["🎬 Brunel"]
    assert got["Early Bird"]["winners"] == ["🦉 Ada"]
    assert got["The Wordsmith"]["winners"] == ["🦉 Ada"]
    assert got["Specimen Hunter"]["winners"] == ["🦉 Ada"]
    assert set(got["Lead Investigator"]["winners"]) == {"🦉 Ada", "🎬 Brunel"}  # tie is shared


def test_taste_awards_need_enough_reports():
    got = by_title(awards.agent_awards([rating(1, 1, 1, 5)], AGENTS))
    assert "Golden Retriever" not in got and "The Food Critic" not in got
    assert "Lead Investigator" in got


def test_biscuit_awards():
    ratings = [
        rating(1, 1, 1, 5), rating(2, 2, 1, 1),                      # B1: divisive
        rating(3, 1, 2, 2, excitement=5, taste=1),                   # B2: overhyped, last
        rating(4, 1, 3, 3, excitement=1, taste=5, snap=5),           # B3: dark horse, loud
    ]
    specials, champions = awards.biscuit_awards(ratings)
    s = by_title(specials)
    assert s["Most Divisive"]["winners"] == ["B1"]
    assert s["Most Overhyped"]["winners"] == ["B2"]
    assert s["Dark Horse"]["winners"] == ["B3"]
    assert s["The Wooden Spoon"]["winners"] == ["B2"]
    c = by_title(champions)
    assert len(champions) == len(CATEGORY_KEYS)
    assert "B3" in c["Loudest Snap"]["winners"]


def test_empty_data_gives_no_awards():
    assert awards.compute({"ratings": [], "agents": []}) == {
        "biscuit_specials": [], "champions": [], "agents": [], "favourites": {}}


def test_soulmate_and_nemesis():
    ratings = [rating(1, 1, 1, 5), rating(2, 1, 2, 2), rating(3, 1, 3, 5),   # agent 1: tie at top
               rating(4, 2, 1, 3)]                                           # agent 2: one report
    fav = awards.agent_favourites(ratings)
    assert fav[1]["soulmate"] == [(1, "B1"), (3, "B3")] and fav[1]["soulmate_score"] == 5
    assert fav[1]["nemesis"] == [(2, "B2")] and fav[1]["nemesis_score"] == 2
    assert fav[2]["soulmate"] == [(1, "B1")] and fav[2]["nemesis"] == []  # nothing to compare
