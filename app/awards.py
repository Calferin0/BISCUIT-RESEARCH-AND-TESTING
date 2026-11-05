"""Awards night: party-game superlatives for biscuits and agents.

Pure functions over plain data (db.awards_data()), with no Flask and no SQL, so every award is
easy to unit test. Ties are shared: all joint winners are named.
Keep the tags work-appropriate: tease the biscuit, be kind to the people.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import mean, pstdev

from .scoring import CATEGORIES, is_purist

MIN_REPORTS = 2        # agents need this many reports for "taste" awards
MIN_BISCUITS_FOR_SPOON = 3


def _award(icon: str, title: str, tag: str, winners: list[str], detail: str,
           winner_ids: list[int] | None = None) -> dict:
    # winner_ids: biscuit ids, parallel to winners, so the page can redact biscuits the viewer
    # hasn't rated yet (blind rating). Empty for agent awards.
    return {"icon": icon, "title": title, "tag": tag, "winners": winners, "detail": detail,
            "winner_ids": winner_ids or []}


def _best(values: dict, *, highest: bool = True) -> tuple[list, float] | None:
    """Keys sharing the best value (ties included), plus that value. None if empty."""
    if not values:
        return None
    pick = max if highest else min
    best = pick(values.values())
    keys = sorted(k for k, v in values.items() if round(v, 3) == round(best, 3))
    return keys, best


def _overall(rating: dict) -> float | None:
    vals = list(rating["scores"].values())
    return mean(vals) if vals else None


def _cat_avg(ratings: list[dict], key: str) -> float | None:
    vals = [r["scores"][key] for r in ratings if key in r["scores"]]
    return mean(vals) if vals else None


def agent_awards(ratings: list[dict], agents: list) -> list[dict]:
    names = {a["id"]: f"{a['avatar']} {a['name']}" for a in agents}
    by_agent: dict[int, list[dict]] = defaultdict(list)
    for r in ratings:
        if r["member_id"] in names:
            by_agent[r["member_id"]].append(r)
    eligible = {m: rs for m, rs in by_agent.items() if len(rs) >= MIN_REPORTS}
    out: list[dict] = []

    def add(icon, title, tag, values, fmt, *, highest=True, need=1):
        if len(values) < need:
            return
        got = _best(values, highest=highest)
        if got:
            keys, best = got
            out.append(_award(icon, title, tag, [names[k] for k in keys], fmt(best)))

    add("🕵️", "Lead Investigator", "Has eaten the evidence. All of it.",
        {m: len(rs) for m, rs in by_agent.items()}, lambda v: f"{v} field reports filed")

    happy = {m: sum(1 for r in rs if (_overall(r) or 0) >= 4) for m, rs in by_agent.items()}
    add("😊", "Easily Pleased", "Happy with the most biscuits. A joy to share a tin with.",
        {m: v for m, v in happy.items() if v}, lambda v: f"{v} biscuit{'s' if v != 1 else ''} rated 4+")

    given = {m: mean(s for r in rs for s in r["scores"].values()) for m, rs in eligible.items()
             if any(r["scores"] for r in rs)}
    add("🐶", "Golden Retriever", "Loves every biscuit. Unconditionally.",
        given, lambda v: f"average score given: {v:.1f}", need=2)
    add("🧐", "The Food Critic", "Has standards. Has never once lowered them.",
        given, lambda v: f"average score given: {v:.1f}", highest=False, need=2)

    spread = {m: pstdev([s for r in rs for s in r["scores"].values()]) for m, rs in eligible.items()
              if sum(len(r["scores"]) for r in rs) >= 2}
    add("🎲", "The Wildcard", "Scores like a dice roll. Nobody knows what's next.",
        spread, lambda v: f"score spread: ±{v:.1f}", need=2)

    threes = {}
    for m, rs in eligible.items():
        vals = [s for r in rs for s in r["scores"].values()]
        if vals and vals.count(3):
            threes[m] = vals.count(3) / len(vals)
    add("🧘", "The Fence Sitter", "Three out of five. Always three out of five.",
        threes, lambda v: f"{v:.0%} of scores were a 3")

    # Contrarian: how far each agent's verdict lands from everyone else's on the same biscuit.
    by_biscuit: dict[int, list[dict]] = defaultdict(list)
    for r in ratings:
        by_biscuit[r["biscuit_id"]].append(r)
    gaps: dict[int, list[float]] = defaultdict(list)
    for rs in by_biscuit.values():
        for r in rs:
            mine = _overall(r)
            others = [o for o in (_overall(x) for x in rs if x is not r) if o is not None]
            if mine is not None and others and r["member_id"] in names:
                gaps[r["member_id"]].append(abs(mine - mean(others)))
    add("🙃", "The Contrarian", "If the team loves it, they don't. And vice versa.",
        {m: mean(g) for m, g in gaps.items() if len(g) >= MIN_REPORTS},
        lambda v: f"{v:.1f} points off the team consensus", need=2)

    for key, icon, title, tag in (
        ("dunk_better", "🫖", "Dunk Lord", "Has never met a biscuit they wouldn't dunk."),
        ("excitement", "🎉", "Hype Machine", "Gets excited by a closed packet."),
        ("sniff", "👃", "The Nose", "Sniffs first, asks questions later."),
    ):
        avgs = {m: v for m, rs in eligible.items() if (v := _cat_avg(rs, key)) is not None}
        add(icon, title, tag, avgs, lambda v: f"average {v:.1f} given", need=2)

    words = {m: sum(r["comment_len"] or 0 for r in rs) for m, rs in by_agent.items()}
    add("✍️", "The Wordsmith", "Field notes longer than the biscuit.",
        {m: v for m, v in words.items() if v}, lambda v: f"{v} characters of field notes")

    firsts: dict[int, int] = defaultdict(int)
    for rs in by_biscuit.values():
        first = min(rs, key=lambda r: (r["created_at"], r["id"]))
        if first["member_id"] in names:
            firsts[first["member_id"]] += 1
    add("🐦", "Early Bird", "First to the tin, every time.",
        dict(firsts), lambda v: f"first to review {v} biscuit{'s' if v != 1 else ''}")

    add("🧭", "Specimen Hunter", "Keeps finding biscuits nobody knew we had.",
        {a["id"]: a["added"] for a in agents if a["added"]},
        lambda v: f"{v} specimen{'s' if v != 1 else ''} logged")

    dry = {m: sum(1 for r in rs if is_purist(r["scores"])) for m, rs in by_agent.items()}
    add("🏜️", "The Purist", "Tea is for drinking. Biscuits are for eating. Never the twain shall meet.",
        {m: v for m, v in dry.items() if v}, lambda v: f"{v} biscuit{'s' if v != 1 else ''} eaten bone dry")
    return out


def biscuit_awards(ratings: list[dict]) -> tuple[list[dict], list[dict]]:
    """(special awards, per-category champions)."""
    by_biscuit: dict[int, list[dict]] = defaultdict(list)
    names: dict[int, str] = {}
    for r in ratings:
        by_biscuit[r["biscuit_id"]].append(r)
        names[r["biscuit_id"]] = r["biscuit"]

    specials: list[dict] = []

    def add(target, icon, title, tag, values, fmt, *, highest=True):
        got = _best(values, highest=highest)
        if got:
            keys, best = got
            target.append(_award(icon, title, tag, [names[k] for k in keys], fmt(best), list(keys)))

    overalls = {b: [o for o in map(_overall, rs) if o is not None] for b, rs in by_biscuit.items()}

    add(specials, "⚖️", "Most Divisive", "The team is split. Friendships have been tested.",
        {b: pstdev(os) for b, os in overalls.items() if len(os) >= 2 and pstdev(os) > 0},
        lambda v: f"reviews ±{v:.1f} apart")

    hype_gap = {}
    for b, rs in by_biscuit.items():
        hype, taste = _cat_avg(rs, "excitement"), _cat_avg(rs, "taste")
        if hype is not None and taste is not None:
            hype_gap[b] = hype - taste
    add(specials, "🎈", "Most Overhyped", "The excitement wrote a cheque the taste couldn't cash.",
        {b: v for b, v in hype_gap.items() if v > 0}, lambda v: f"hype beat taste by {v:.1f}")
    add(specials, "🐎", "Dark Horse", "Nobody expected it. Everybody loved it.",
        {b: -v for b, v in hype_gap.items() if v < 0}, lambda v: f"taste beat hype by {v:.1f}")

    add(specials, "🔬", "Most Investigated", "Everyone's had a go. Some twice, emotionally.",
        {b: len(rs) for b, rs in by_biscuit.items() if len(rs) >= 2}, lambda v: f"{v} field reports")

    means = {b: mean(os) for b, os in overalls.items() if os}
    if len(means) >= MIN_BISCUITS_FOR_SPOON:
        add(specials, "🥄", "The Wooden Spoon", "Someone has to come last. Sorry, little biscuit.",
            means, lambda v: f"overall {v:.1f} / 5", highest=False)

    champions: list[dict] = []
    for c in CATEGORIES:
        avgs = {b: v for b, rs in by_biscuit.items() if (v := _cat_avg(rs, c.key)) is not None}
        add(champions, c.award_icon, c.award_title, c.award_tag, avgs,
            lambda v, label=c.label: f"{label}: {v:.1f} / 5")
    return specials, champions


def agent_favourites(ratings: list[dict]) -> dict[int, dict]:
    """Per agent: their 'Soulmate' (highest-rated biscuit) and 'Nemesis' (lowest), ties shared.

    Returns {member_id: {"soulmate": [(biscuit_id, name)], "soulmate_score": float,
                         "nemesis": [...], "nemesis_score": float | None}}.
    The nemesis is omitted (empty, None) when it would just repeat the soulmate, i.e. one rating
    or every rating tied.
    """
    by_agent: dict[int, dict[int, tuple[str, float]]] = defaultdict(dict)
    for r in ratings:
        o = _overall(r)
        if o is not None:
            by_agent[r["member_id"]][r["biscuit_id"]] = (r["biscuit"], o)

    out: dict[int, dict] = {}
    for member, scored in by_agent.items():
        values = {b: o for b, (_, o) in scored.items()}
        top_ids, top = _best(values)
        low_ids, low = _best(values, highest=False)
        same = round(top, 3) == round(low, 3)
        out[member] = {
            "soulmate": [(b, scored[b][0]) for b in top_ids], "soulmate_score": top,
            "nemesis": [] if same else [(b, scored[b][0]) for b in low_ids],
            "nemesis_score": None if same else low,
        }
    return out


def compute(data: dict) -> dict:
    specials, champions = biscuit_awards(data["ratings"])
    return {"biscuit_specials": specials, "champions": champions,
            "agents": agent_awards(data["ratings"], data["agents"]),
            "favourites": agent_favourites(data["ratings"])}
