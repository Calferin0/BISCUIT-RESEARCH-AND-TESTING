"""Daily silliness: Biscuit of the Day and the Biscuit Horoscope. Pure and deterministic.

Both are seeded by the date (and the agent, for horoscopes) so they're stable all day and change
at midnight, with no storage needed.
"""
from __future__ import annotations

import random
from datetime import date

HOROSCOPE = (
    "A Bourbon will cross your path. Do not trust it.",
    "Your lucky dunk time today is {n} seconds. Not one more.",
    "Mercury is in retrograde. Avoid anything with a jam filling.",
    "Someone in this office is hiding a packet of chocolate digestives. Find them.",
    "Today is a good day to finally admit you like Rich Tea.",
    "The stars say: snap, don't crumble.",
    "A colleague will offer you the last biscuit. It is a test.",
    "Your aura is distinctly ginger nut today.",
    "Beware of a stranger bearing custard creams.",
    "You will file {n} field reports this week. The tin has spoken.",
    "Today, dunk with confidence. The tea respects decisiveness.",
    "A great rarity approaches. Keep your phone charged.",
    "Your spirit biscuit today is the Jammie Dodger: sweet on the outside, chaotic at heart.",
    "Avoid duels before 11am. Your Crumble game is weak in the mornings.",
    "Someone will challenge you to Biscuit VS. Choose Dunk. Or don't. The stars are vague.",
    "Your crumb-to-keyboard ratio is dangerously high. Seek a plate.",
    "Lucky colour: Hobnob beige. Lucky number: {n}.",
    "The Biscuit Oracle sees… a free biscuit in your near future. (Not guaranteed.)",
)

SPECIAL_LINES = (
    "Today's honoured specimen. Treat it with respect.",
    "The tin has chosen. Who are we to argue?",
    "Chosen by a highly scientific process (random numbers).",
    "If you haven't reviewed this one, today is the day.",
    "Celebrate responsibly. One packet per agent.",
)


def biscuit_of_the_day(specimens, today: date):
    """One specimen per day, same for everyone. None if there are none."""
    pool = sorted(specimens, key=lambda b: b["id"])
    if not pool:
        return None, None
    rng = random.Random(today.toordinal())
    return rng.choice(pool), rng.choice(SPECIAL_LINES)


def horoscope(member_id: int, today: date) -> str:
    """Same reading all day for each agent; different for each agent."""
    rng = random.Random(f"{member_id}:{today.isoformat()}")
    return rng.choice(HOROSCOPE).format(n=rng.randint(2, 9))
