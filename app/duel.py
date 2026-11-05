"""Biscuit VS: Dunk / Snap / Crumble. A best-of-3 rock-paper-scissors duel, played async on phones.

  Dunk    beats Snap     (a good dunk softens any snap into submission)
  Snap    beats Crumble  (a clean snap leaves no crumbs)
  Crumble beats Dunk     (crumbs in the tea: the dunk is ruined)

First to WIN_ROUNDS round wins takes the pot. Drawn rounds don't count and are replayed, up to
MAX_ROUNDS in total; after that the higher score wins, or it's a draw and stakes are refunded.
Pure functions: state is rebuilt from the stored moves every time, so there's nothing to drift.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

MOVES = {"dunk": "🫖 Dunk", "snap": "💥 Snap", "crumble": "🍪 Crumble"}
BEATS = {"dunk": "snap", "snap": "crumble", "crumble": "dunk"}
WIN_ROUNDS = 2
MAX_ROUNDS = 9
MAX_WAGER = 200

COMMENTARY = {
    ("dunk", "snap"): ("The dunk softened the snap into submission.", "Snap? More like *sag*."),
    ("snap", "crumble"): ("A clean snap. The crumble never stood a chance.", "Crisp, decisive, devastating."),
    ("crumble", "dunk"): ("Crumbs in the tea. The dunker weeps.", "A floating crumb raft of shame."),
}
MIRROR = ("Mirror match! Both went {move}. Go again.", "Identical tactics. The tin demands a replay.",
          "Great minds dunk alike. Again!")


@dataclass
class Round:
    number: int
    moves: dict[int, str]              # member_id -> move (only for completed rounds)
    winner: int | None                 # None = drawn round
    line: str


@dataclass
class State:
    rounds: list[Round] = field(default_factory=list)
    score: dict[int, int] = field(default_factory=dict)
    current: int = 1                   # the round awaiting moves
    waiting_on: set[int] = field(default_factory=set)
    finished: bool = False
    winner: int | None = None          # None + finished = draw


def beats(a: str, b: str) -> bool:
    return BEATS[a] == b


def build_state(challenger: int, opponent: int, moves: list[tuple[int, int, str]],
                rng: random.Random | None = None) -> State:
    """moves: (round, member_id, move) rows. Rebuilds rounds, score and whose turn it is."""
    rng = rng or random.Random(0)      # commentary choice only; seeded so a page reload is stable
    players = (challenger, opponent)
    by_round: dict[int, dict[int, str]] = {}
    for rnd, member, move in moves:
        by_round.setdefault(rnd, {})[member] = move
    st = State(score={challenger: 0, opponent: 0})
    rnd = 1
    while rnd <= MAX_ROUNDS:
        played = by_round.get(rnd, {})
        if set(played) != set(players):
            st.current, st.waiting_on = rnd, {p for p in players if p not in played}
            break
        a, b = played[challenger], played[opponent]
        if a == b:
            st.rounds.append(Round(rnd, played, None, rng.choice(MIRROR).format(move=MOVES[a])))
        else:
            win = challenger if beats(a, b) else opponent
            key = (a, b) if win == challenger else (b, a)
            st.score[win] += 1
            st.rounds.append(Round(rnd, played, win, rng.choice(COMMENTARY[key])))
        if max(st.score.values()) >= WIN_ROUNDS:
            st.finished = True
            st.winner = max(st.score, key=st.score.get)
            break
        rnd += 1
    else:
        st.finished = True
        a, b = st.score[challenger], st.score[opponent]
        st.winner = None if a == b else (challenger if a > b else opponent)
    if st.finished:
        st.waiting_on = set()
    return st
