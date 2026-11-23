"""Who Said That? A field report quote; guess which agent wrote it. Pure: no Flask, no SQL.

Only quotes the player may already read (D10, checked by the caller with cases.can_see) and
never their own. The answer is stored server-side in `whosaid_rounds`, never sent to the page.
Correct guesses pay a few points through the ledger (D21), capped per day so it stays a game.
"""
from __future__ import annotations

import random

MIN_QUOTE = 15        # characters: shorter notes ("ok", "nice") aren't guessable
OPTIONS = 4           # the author plus up to three decoys
REWARD = 3            # points per correct guess...
DAILY_CAP = 15        # ...up to this many per day


def choose_quote(quotes: list, seen: dict[int, int], rng: random.Random):
    """Fresh quotes first (#14/#15: they repeated a lot). Once you've seen every quote, pick from
    the half you saw longest ago, so a repeat is always the stalest one, never the last round.
    seen: {rating id: id of the latest round that used it} for this player."""
    fresh = [q for q in quotes if q["id"] not in seen]
    if fresh:
        return rng.choice(fresh)
    stalest = sorted(quotes, key=lambda q: seen[q["id"]])
    return rng.choice(stalest[:max(1, len(stalest) // 2)])


def pick_round(quotes: list, agent_ids: list[int], player_id: int,
               rng: random.Random, seen: dict[int, int] | None = None) -> tuple[object, list[int]] | None:
    """quotes: rows with `id` and `member_id` (already filtered for visibility). Returns
    (quote, options) or None when there's nothing to play: no quotes, or nobody to use as a decoy."""
    if not quotes:
        return None
    quote = choose_quote(quotes, seen or {}, rng)
    decoys = [a for a in agent_ids if a not in (quote["member_id"], player_id)]
    if not decoys:
        return None
    options = rng.sample(decoys, min(OPTIONS - 1, len(decoys))) + [quote["member_id"]]
    rng.shuffle(options)
    return quote, options


def reward_for(correct: bool, rewarded_today: int) -> int:
    if not correct:
        return 0
    return max(0, min(REWARD, DAILY_CAP - rewarded_today))


def streaks(history: list) -> tuple[int, int]:
    """history: settled rounds newest first, each with `correct`. Returns (current, best)."""
    current = 0
    for r in history:
        if not r["correct"]:
            break
        current += 1
    best = run = 0
    for r in reversed(history):
        run = run + 1 if r["correct"] else 0
        best = max(best, run)
    return current, best
