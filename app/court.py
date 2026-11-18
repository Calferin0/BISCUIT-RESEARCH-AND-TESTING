"""Biscuit Court: OBJECTION! to another agent's field report, a jury, and Judge Tony.

Pure (no Flask, no SQL), like duel.py: the verdict is rebuilt from the votes and the clock every
time, never stored, so there's no "settle" step that could be missed or run twice.

Rules (CF, 2026-11-18):
  * object to another agent's report you can see (same visibility as 👍, so blind rating holds);
  * the defendant may file a short defence while the case is open;
  * any other agent who can see the report may sit on the jury: one final vote each;
  * a case closes at JURY_SIZE votes or after SITTING_HOURS, whichever comes first;
  * more Sustained than Overruled sustains it. Ties and empty juries are overruled: the report
    gets the benefit of the doubt;
  * no Biscuit Points either way. A sustained objection only stamps the report CONTESTED.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

JURY_SIZE = 3
SITTING_HOURS = 24
REASON_MIN, REASON_MAX = 5, 200
DEFENCE_MAX = 200
VOTES = ("sustained", "overruled")

# Judge Tony's rulings. Picked by case number, so a case always reads the same.
SUSTAINED_LINES = (
    "Objection sustained. The court has tasted the evidence and is not convinced.",
    "Sustained. Let the record show the crumbs do not lie.",
    "Sustained. The report is stamped CONTESTED. Tony's moustache twitches in disapproval.",
    "Sustained. The court reminds all agents that opinions, like biscuits, can go soft.",
)
OVERRULED_LINES = (
    "Overruled. The report stands. Agents are entitled to their questionable taste.",
    "Overruled. The court finds no crumb of wrongdoing.",
    "Overruled. Tony has spoken, mostly through his moustache.",
    "Overruled. Case dismissed. Everyone have a biscuit.",
)
EMPTY_JURY_LINE = "Dismissed. No jury turned up, so the report gets the benefit of the doubt."


@dataclass(frozen=True)
class Ruling:
    open: bool
    verdict: str | None      # 'sustained' | 'overruled' once closed, None while open
    sustained: int
    overruled: int
    closes_at: datetime
    line: str                # Judge Tony's words ('' while open)


def parse_ts(text: str) -> datetime:
    """SQLite's datetime('now') text (UTC, naive) -> datetime."""
    return datetime.fromisoformat(text)


def rule(case_id: int, created_at: datetime, sustained: int, overruled: int, now: datetime) -> Ruling:
    closes_at = created_at + timedelta(hours=SITTING_HOURS)
    if sustained + overruled < JURY_SIZE and now < closes_at:
        return Ruling(True, None, sustained, overruled, closes_at, "")
    if sustained > overruled:
        return Ruling(False, "sustained", sustained, overruled, closes_at,
                      SUSTAINED_LINES[case_id % len(SUSTAINED_LINES)])
    line = EMPTY_JURY_LINE if sustained + overruled == 0 else OVERRULED_LINES[case_id % len(OVERRULED_LINES)]
    return Ruling(False, "overruled", sustained, overruled, closes_at, line)


def can_object(viewer_id: int, defendant_id: int) -> bool:
    return viewer_id != defendant_id


def can_serve(viewer_id: int, objector_id: int, defendant_id: int) -> bool:
    """Jury duty: anyone but the two parties. (Visibility is checked separately, in the view.)"""
    return viewer_id not in (objector_id, defendant_id)


def clean_reason(text: str) -> str | None:
    """The objection's reason, trimmed; None if too short to be a real objection."""
    text = " ".join(text.split())[:REASON_MAX]
    return text if len(text) >= REASON_MIN else None
