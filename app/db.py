"""SQLite access: schema, migrations, connection handling and every query the app runs.

One connection per request, stored on flask.g and closed on teardown. A sqlite3 connection
must not be shared across waitress worker threads, and opening a local file is cheap.
All values go through ? placeholders. The only SQL built with f-strings is CATS_IN, made
from scoring.CATEGORY_KEYS: code constants validated as [a-z_]+, never user input.
"""
from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path

import click
from flask import Flask, current_app, g
from flask.cli import with_appcontext

from . import similarity
from .points import NOTE_MIN_CHARS
from .scoring import AVATARS, CATEGORY_KEYS

SCHEMA_VERSION = 9

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    avatar     TEXT    NOT NULL DEFAULT '🍪',
    token      TEXT    NOT NULL UNIQUE,
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS biscuits (
    id           INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL,
    brand        TEXT    NOT NULL DEFAULT '',
    image        TEXT,                -- filename in the uploads dir
    image_hash   TEXT,                -- sha256 of the photo bytes, for duplicate detection
    image_source TEXT,                -- 'upload', 'Open Food Facts' or the pasted URL
    added_by     INTEGER REFERENCES members(id),
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    case_status  TEXT    NOT NULL DEFAULT 'open',  -- v5: open | closed (no longer in shops)
    closed_at    TEXT,                             -- v5
    rarity_override TEXT                           -- v8: admin-set tier; NULL = team vote decides
);
CREATE INDEX IF NOT EXISTS idx_biscuits_image_hash ON biscuits(image_hash);

CREATE TABLE IF NOT EXISTS ratings (
    id         INTEGER PRIMARY KEY,
    member_id  INTEGER NOT NULL REFERENCES members(id),
    biscuit_id INTEGER NOT NULL REFERENCES biscuits(id),
    comment    TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (member_id, biscuit_id)    -- one report per agent per biscuit
);
CREATE INDEX IF NOT EXISTS idx_ratings_biscuit ON ratings(biscuit_id);

-- Long format: one row per (rating, category). Categories live in code (scoring.py), so they
-- can change without a migration.
CREATE TABLE IF NOT EXISTS scores (
    rating_id INTEGER NOT NULL REFERENCES ratings(id) ON DELETE CASCADE,
    category  TEXT    NOT NULL,
    value     INTEGER NOT NULL CHECK (value BETWEEN 1 AND 5),
    PRIMARY KEY (rating_id, category)
) WITHOUT ROWID;

-- v3: the suggestion box. Linked to the author; status is moved along by the weekly loop.
CREATE TABLE IF NOT EXISTS suggestions (
    id         INTEGER PRIMARY KEY,
    member_id  INTEGER NOT NULL REFERENCES members(id),
    kind       TEXT    NOT NULL DEFAULT 'idea',
    body       TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'new',   -- new | planned | building | shipped | declined
    response   TEXT    NOT NULL DEFAULT '',      -- control room's reply, shown to everyone
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS suggestion_votes (
    suggestion_id INTEGER NOT NULL REFERENCES suggestions(id) ON DELETE CASCADE,
    member_id     INTEGER NOT NULL REFERENCES members(id),
    PRIMARY KEY (suggestion_id, member_id)       -- one +1 per agent per suggestion
) WITHOUT ROWID;

-- v4: biscuit drops (limited editions / seasonal / new / returning), entered by the team.
-- No public feed exists for UK biscuit releases, so this is a team-maintained, team-corrected list.
CREATE TABLE IF NOT EXISTS drops (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    brand      TEXT    NOT NULL DEFAULT '',
    kind       TEXT    NOT NULL DEFAULT 'limited',  -- limited | seasonal | new | returning
    starts_on  TEXT,                                -- ISO date; NULL = date TBC
    ends_on    TEXT,                                -- ISO date; NULL = open-ended / unknown
    shops      TEXT    NOT NULL DEFAULT '',
    source_url TEXT    NOT NULL DEFAULT '',
    notes      TEXT    NOT NULL DEFAULT '',
    added_by   INTEGER REFERENCES members(id),
    updated_by INTEGER REFERENCES members(id),
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now')),
    biscuit_id INTEGER REFERENCES biscuits(id)      -- v8: the specimen this drop is (if logged)
);

-- v5: requests to reopen a closed case because the biscuit is back in shops.
CREATE TABLE IF NOT EXISTS reopen_requests (
    id          INTEGER PRIMARY KEY,
    biscuit_id  INTEGER NOT NULL REFERENCES biscuits(id),
    member_id   INTEGER NOT NULL REFERENCES members(id),
    note        TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'pending',  -- pending | approved | declined
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT
);

-- v5: thumbs-up on other agents' field notes (feeds Biscuit Points).
CREATE TABLE IF NOT EXISTS report_votes (
    rating_id INTEGER NOT NULL REFERENCES ratings(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id),
    PRIMARY KEY (rating_id, member_id)
) WITHOUT ROWID;

-- v6: the Biscuit Shop. Earnings are computed (points.py); this is the ledger of *spends*.
-- UNIQUE stops a double-click buying the same item twice.
CREATE TABLE IF NOT EXISTS purchases (
    id         INTEGER PRIMARY KEY,
    member_id  INTEGER NOT NULL REFERENCES members(id),
    item_key   TEXT    NOT NULL,
    cost       INTEGER NOT NULL CHECK (cost >= 0),   -- price at time of purchase
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    source     TEXT    NOT NULL DEFAULT 'shop',      -- v8: shop | loot (loot items cost 0 here)
    UNIQUE (member_id, item_key)
);
CREATE TABLE IF NOT EXISTS equipped (
    member_id INTEGER NOT NULL REFERENCES members(id),
    slot      TEXT    NOT NULL,                      -- title | color | frame
    item_key  TEXT    NOT NULL,
    PRIMARY KEY (member_id, slot)
) WITHOUT ROWID;

-- v7: Biscuit Radar. Shops from OpenStreetMap (osm_ref) or added by agents (by postcode).
CREATE TABLE IF NOT EXISTS shops (
    id         INTEGER PRIMARY KEY,
    osm_ref    TEXT    UNIQUE,                       -- 'node/123' / 'way/456'; NULL if agent-added
    name       TEXT    NOT NULL,
    brand      TEXT    NOT NULL DEFAULT '',
    kind       TEXT    NOT NULL DEFAULT '',          -- supermarket | convenience | ...
    lat        REAL    NOT NULL,
    lng        REAL    NOT NULL,
    postcode   TEXT    NOT NULL DEFAULT '',
    added_by   INTEGER REFERENCES members(id),
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
-- Every price report is kept (history). The latest per (shop, biscuit) is the current price,
-- so "correcting" a price is just reporting a newer one.
CREATE TABLE IF NOT EXISTS prices (
    id         INTEGER PRIMARY KEY,
    shop_id    INTEGER NOT NULL REFERENCES shops(id),
    biscuit_id INTEGER NOT NULL REFERENCES biscuits(id),
    pence      INTEGER NOT NULL CHECK (pence BETWEEN 1 AND 10000),
    pack       TEXT    NOT NULL DEFAULT '',
    member_id  INTEGER REFERENCES members(id),
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    active     INTEGER NOT NULL DEFAULT 1            -- v8: admin can retract a wrong report
);
CREATE INDEX IF NOT EXISTS idx_prices_lookup ON prices(shop_id, biscuit_id, id);

-- v8: rarity is a team vote (one vote per agent per biscuit); biscuits.rarity_override wins.
CREATE TABLE IF NOT EXISTS rarity_votes (
    biscuit_id INTEGER NOT NULL REFERENCES biscuits(id),
    member_id  INTEGER NOT NULL REFERENCES members(id),
    tier       TEXT    NOT NULL,
    PRIMARY KEY (biscuit_id, member_id)
) WITHOUT ROWID;

-- v8: points movements that aren't "earned" (computed) or shop purchases: lootbox costs,
-- loot refunds, duel stakes, winnings and refunds. Balance = earned - shop spend + SUM(delta).
CREATE TABLE IF NOT EXISTS ledger (
    id         INTEGER PRIMARY KEY,
    member_id  INTEGER NOT NULL REFERENCES members(id),
    delta      INTEGER NOT NULL,
    reason     TEXT    NOT NULL,
    ref        TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ledger_member ON ledger(member_id);

-- v8: Biscuit VS duels (Dunk / Snap / Crumble, first to 2 round wins).
CREATE TABLE IF NOT EXISTS duels (
    id            INTEGER PRIMARY KEY,
    challenger_id INTEGER NOT NULL REFERENCES members(id),
    opponent_id   INTEGER NOT NULL REFERENCES members(id),
    wager         INTEGER NOT NULL DEFAULT 0 CHECK (wager >= 0),
    biscuit_iou   INTEGER NOT NULL DEFAULT 0,       -- 1 = loser buys the winner a packet
    status        TEXT    NOT NULL DEFAULT 'pending', -- pending | active | done | declined | cancelled
    winner_id     INTEGER REFERENCES members(id),   -- NULL on a draw
    iou_paid      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    accepted_at   TEXT,
    finished_at   TEXT
);
CREATE TABLE IF NOT EXISTS duel_moves (
    duel_id   INTEGER NOT NULL REFERENCES duels(id),
    round     INTEGER NOT NULL,
    member_id INTEGER NOT NULL REFERENCES members(id),
    move      TEXT    NOT NULL,                     -- dunk | snap | crumble
    PRIMARY KEY (duel_id, round, member_id)         -- one move per player per round
) WITHOUT ROWID;

-- v8: the Dunk-O-Meter. How long did it survive in the tea?
CREATE TABLE IF NOT EXISTS dunks (
    id         INTEGER PRIMARY KEY,
    member_id  INTEGER NOT NULL REFERENCES members(id),
    biscuit_id INTEGER NOT NULL REFERENCES biscuits(id),
    seconds    REAL    NOT NULL CHECK (seconds > 0 AND seconds <= 900),
    drink      TEXT    NOT NULL DEFAULT 'tea',
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    active     INTEGER NOT NULL DEFAULT 1           -- v9: admin can remove a silly record
);

-- v9: control-room settings (feature switches). key -> value as text.
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;
"""

# v4 -> v5 adds columns to an existing table, which CREATE TABLE IF NOT EXISTS can't do.
# Applied only where missing, so the migration is idempotent (safe to re-run on any file).
ADDED_COLUMNS = {
    "biscuits": (("case_status", "TEXT NOT NULL DEFAULT 'open'"), ("closed_at", "TEXT"),
                 ("rarity_override", "TEXT")),                                   # v8
    "prices": (("active", "INTEGER NOT NULL DEFAULT 1"),),                       # v8
    "purchases": (("source", "TEXT NOT NULL DEFAULT 'shop'"),),                  # v8: shop | loot
    "drops": (("biscuit_id", "INTEGER"),),                                       # v8: explicit specimen link
    "dunks": (("active", "INTEGER NOT NULL DEFAULT 1"),),                        # v9: admin removal
}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    for table, columns in ADDED_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not have:
            continue  # table doesn't exist yet: SCHEMA creates it with every column
        for name, decl in columns:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

# v1 had one column per category (dunk, crunch, ...). Those categories don't map onto the v2
# set, so v1 ratings are parked in ratings_v1 rather than converted. Nothing is deleted.
MIGRATE_1_TO_2 = """
ALTER TABLE ratings RENAME TO ratings_v1;
ALTER TABLE biscuits ADD COLUMN image_hash TEXT;
ALTER TABLE biscuits ADD COLUMN image_source TEXT;
"""

CATS_IN = "(" + ", ".join(f"'{k}'" for k in CATEGORY_KEYS) + ")"
SCORES_JOIN = f"LEFT JOIN scores s ON s.rating_id = r.id AND s.category IN {CATS_IN}"


# --- connection lifecycle ---------------------------------------------------------------

def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # off by default in SQLite, per connection
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = _connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc: BaseException | None = None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def _backup(conn: sqlite3.Connection, path: Path, version: int) -> Path:
    """Consistent copy via SQLite's online backup API (a plain file copy can tear under WAL)."""
    dest = path.with_name(f"{path.stem}.v{version}-backup{path.suffix}")
    target = sqlite3.connect(dest)
    try:
        conn.backup(target)
    finally:
        target.close()
    return dest


def init_db(path: Path) -> None:
    """Create or migrate the schema, keyed on PRAGMA user_version."""
    conn = _connect(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"{path} is schema v{version}; this code only knows v{SCHEMA_VERSION}.")
        # WAL lets phones read while someone else writes. It's a property of the file.
        conn.execute("PRAGMA journal_mode = WAL")
        if 0 < version < SCHEMA_VERSION:
            _backup(conn, path, version)  # every upgrade, even additive ones, keeps a pre-upgrade copy
        if version == 1:
            conn.executescript(MIGRATE_1_TO_2)
        if version > 0:
            _add_missing_columns(conn)
        # Everything else from v2 on only adds tables, which SCHEMA's CREATE ... IF NOT EXISTS covers.
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    finally:
        conn.close()


def init_app(app: Flask) -> None:
    init_db(app.config["DATABASE"])
    app.teardown_appcontext(close_db)
    app.cli.add_command(demo_seed)
    app.cli.add_command(export_suggestions)


def _attach_scores(rows) -> list[dict]:
    """Turn rating rows (which must include `id`) into dicts with a `scores` {category: value} map."""
    out = [{**dict(r), "scores": {}} for r in rows]
    if not out:
        return out
    by_id = {r["id"]: r for r in out}
    marks = ", ".join("?" for _ in by_id)
    for s in get_db().execute(
        f"SELECT rating_id, category, value FROM scores WHERE rating_id IN ({marks}) AND category IN {CATS_IN}",
        tuple(by_id),
    ):
        by_id[s["rating_id"]]["scores"][s["category"]] = s["value"]
    return out


# --- members ----------------------------------------------------------------------------

def new_token() -> str:
    # 72 random bits: plenty for a LAN biscuit app, and short enough to keep the QR code small.
    return secrets.token_urlsafe(9)


def member_by_token(token: str) -> sqlite3.Row | None:
    return get_db().execute(
        "SELECT * FROM members WHERE token = ? AND active = 1", (token,)
    ).fetchone()


def list_members() -> list[sqlite3.Row]:
    return get_db().execute(
        """SELECT m.*, COUNT(r.id) AS n
           FROM members m LEFT JOIN ratings r ON r.member_id = m.id
           GROUP BY m.id
           ORDER BY m.active DESC, m.name COLLATE NOCASE"""
    ).fetchall()


def member_name_taken(name: str) -> bool:
    return get_db().execute(
        "SELECT 1 FROM members WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone() is not None


def add_member(name: str, avatar: str) -> str:
    token = new_token()
    conn = get_db()
    conn.execute("INSERT INTO members (name, avatar, token) VALUES (?, ?, ?)", (name, avatar, token))
    conn.commit()
    return token


def toggle_member(member_id: int) -> None:
    conn = get_db()
    conn.execute("UPDATE members SET active = 1 - active WHERE id = ?", (member_id,))
    conn.commit()


def rotate_token(member_id: int) -> None:
    conn = get_db()
    conn.execute("UPDATE members SET token = ? WHERE id = ?", (new_token(), member_id))
    conn.commit()


# --- biscuits ---------------------------------------------------------------------------
# A biscuit's overall = the mean of each rating's own average: one agent, one vote. Averaging
# raw score rows instead would give dunkers (10 scores) more weight than Dry Land Purists (8).
RATING_OVERALLS = f"""(SELECT r.id, r.biscuit_id, r.member_id, AVG(s.value) AS overall
                       FROM ratings r JOIN scores s ON s.rating_id = r.id AND s.category IN {CATS_IN}
                       GROUP BY r.id)"""


def list_biscuits(member_id: int | None, include_inactive: bool = False) -> list[sqlite3.Row]:
    """Biscuits with aggregate scores. `mine` = 1 if member_id has rated it. Unrated-by-me first."""
    return get_db().execute(
        f"""SELECT b.*, COUNT(ro.id) AS n, AVG(ro.overall) AS overall,
                   COALESCE(MAX(ro.member_id = :me), 0) AS mine
            FROM biscuits b
            LEFT JOIN {RATING_OVERALLS} ro ON ro.biscuit_id = b.id
            WHERE b.active = 1 OR :all
            GROUP BY b.id
            ORDER BY mine, b.name COLLATE NOCASE""",
        {"me": member_id, "all": int(include_inactive)},
    ).fetchall()


def get_biscuit(biscuit_id: int) -> sqlite3.Row | None:
    return get_db().execute(
        f"""SELECT b.*, m.name AS added_by_name, COUNT(ro.id) AS n, AVG(ro.overall) AS overall
            FROM biscuits b
            LEFT JOIN members m ON m.id = b.added_by
            LEFT JOIN {RATING_OVERALLS} ro ON ro.biscuit_id = b.id
            WHERE b.id = ?
            GROUP BY b.id""",
        (biscuit_id,),
    ).fetchone()


def biscuit_name(biscuit_id: int) -> str | None:
    row = get_db().execute("SELECT name FROM biscuits WHERE id = ?", (biscuit_id,)).fetchone()
    return row["name"] if row else None


def similar_biscuits(name: str, brand: str) -> list[similarity.Match]:
    rows = get_db().execute("SELECT id, name, brand FROM biscuits WHERE active = 1").fetchall()
    return similarity.find_matches(name, brand, rows)


def biscuit_with_image_hash(image_hash: str, exclude_id: int | None = None) -> sqlite3.Row | None:
    return get_db().execute(
        "SELECT id, name FROM biscuits WHERE image_hash = ? AND id IS NOT ?", (image_hash, exclude_id)
    ).fetchone()


def add_biscuit(name: str, brand: str, image: str | None, added_by: int | None,
                image_hash: str | None = None, image_source: str | None = None) -> int:
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO biscuits (name, brand, image, image_hash, image_source, added_by)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, brand, image, image_hash, image_source, added_by),
    )
    conn.commit()
    return cur.lastrowid


def set_biscuit_image(biscuit_id: int, image: str, image_hash: str, image_source: str) -> None:
    # The old file stays in uploads/. Nothing is deleted, and it's recoverable if replaced by mistake.
    conn = get_db()
    conn.execute(
        "UPDATE biscuits SET image = ?, image_hash = ?, image_source = ? WHERE id = ?",
        (image, image_hash, image_source, biscuit_id),
    )
    conn.commit()


def toggle_biscuit(biscuit_id: int) -> None:
    conn = get_db()
    conn.execute("UPDATE biscuits SET active = 1 - active WHERE id = ?", (biscuit_id,))
    conn.commit()


# --- ratings ----------------------------------------------------------------------------

def rated_biscuit_ids(member_id: int) -> set[int]:
    return {r[0] for r in get_db().execute("SELECT biscuit_id FROM ratings WHERE member_id = ?", (member_id,))}


def get_rating(member_id: int, biscuit_id: int) -> dict | None:
    row = get_db().execute(
        "SELECT * FROM ratings WHERE member_id = ? AND biscuit_id = ?", (member_id, biscuit_id)
    ).fetchone()
    return _attach_scores([row])[0] if row else None


def upsert_rating(member_id: int, biscuit_id: int, scores: dict[str, int], comment: str,
                  skipped: tuple[str, ...] = ()) -> None:
    """`skipped`: categories deliberately left blank (Dry Land Purist). Any old scores for them
    are removed, so switching from dunker to purist on an amend doesn't leave stale dunk scores."""
    conn = get_db()
    # `with conn` = one transaction: the rating and all its scores land together or not at all.
    with conn:
        conn.execute(
            """INSERT INTO ratings (member_id, biscuit_id, comment) VALUES (?, ?, ?)
               ON CONFLICT (member_id, biscuit_id) DO UPDATE SET
                   comment = excluded.comment, updated_at = datetime('now')""",
            (member_id, biscuit_id, comment),
        )
        rating_id = conn.execute(
            "SELECT id FROM ratings WHERE member_id = ? AND biscuit_id = ?", (member_id, biscuit_id)
        ).fetchone()[0]
        conn.executemany(
            """INSERT INTO scores (rating_id, category, value) VALUES (?, ?, ?)
               ON CONFLICT (rating_id, category) DO UPDATE SET value = excluded.value""",
            [(rating_id, k, v) for k, v in scores.items()],
        )
        conn.executemany("DELETE FROM scores WHERE rating_id = ? AND category = ?",
                         [(rating_id, k) for k in skipped])


def ratings_for_biscuit(biscuit_id: int) -> list[dict]:
    rows = get_db().execute(
        f"""SELECT r.*, m.name, m.avatar, AVG(s.value) AS overall
            FROM ratings r JOIN members m ON m.id = r.member_id
            {SCORES_JOIN}
            WHERE r.biscuit_id = ?
            GROUP BY r.id
            ORDER BY r.updated_at DESC""",
        (biscuit_id,),
    ).fetchall()
    return _attach_scores(rows)


def category_averages(biscuit_id: int) -> dict[str, float]:
    rows = get_db().execute(
        f"""SELECT s.category, AVG(s.value) AS avg
            FROM scores s JOIN ratings r ON r.id = s.rating_id
            WHERE r.biscuit_id = ? AND s.category IN {CATS_IN}
            GROUP BY s.category""",
        (biscuit_id,),
    ).fetchall()
    return {r["category"]: r["avg"] for r in rows}


def leaderboard() -> list[sqlite3.Row]:
    return get_db().execute(
        f"""SELECT b.*, COUNT(ro.id) AS n, AVG(ro.overall) AS overall
            FROM biscuits b
            JOIN {RATING_OVERALLS} ro ON ro.biscuit_id = b.id
            WHERE b.active = 1
            GROUP BY b.id
            HAVING overall IS NOT NULL
            ORDER BY overall DESC, n DESC, b.name COLLATE NOCASE"""
    ).fetchall()


def agent_stats() -> list[sqlite3.Row]:
    return get_db().execute(
        f"""SELECT m.id, m.name, m.avatar, COUNT(DISTINCT r.id) AS n, AVG(s.value) AS given,
                   (SELECT COUNT(*) FROM biscuits b WHERE b.added_by = m.id AND b.active = 1) AS added
            FROM members m
            LEFT JOIN ratings r ON r.member_id = m.id
            {SCORES_JOIN}
            WHERE m.active = 1
            GROUP BY m.id
            ORDER BY n DESC, m.name COLLATE NOCASE"""
    ).fetchall()


def awards_data() -> dict:
    """Raw material for awards.compute(): every live rating with its scores."""
    ratings = _attach_scores(get_db().execute(
        """SELECT r.id, r.member_id, m.name AS member, m.avatar, r.biscuit_id, b.name AS biscuit,
                  length(r.comment) AS comment_len, r.created_at
           FROM ratings r
           JOIN members m ON m.id = r.member_id AND m.active = 1
           JOIN biscuits b ON b.id = r.biscuit_id AND b.active = 1"""
    ).fetchall())
    return {"ratings": ratings, "agents": agent_stats()}


def export_ratings() -> list[dict]:
    return _attach_scores(get_db().execute(
        """SELECT r.id, m.name AS agent, b.name AS biscuit, b.brand, r.comment, r.created_at, r.updated_at
           FROM ratings r
           JOIN members m ON m.id = r.member_id
           JOIN biscuits b ON b.id = r.biscuit_id
           ORDER BY b.name COLLATE NOCASE, m.name COLLATE NOCASE"""
    ).fetchall())


# --- suggestions ------------------------------------------------------------------------

SUGGESTION_KINDS = {"idea": "💡 Feature idea", "bug": "🐛 Something's broken",
                    "biscuit": "🍪 Biscuit request", "other": "📎 Other"}
SUGGESTION_STATUSES = {"new": "📥 In the inbox", "planned": "🗓️ Planned", "building": "🚧 Working on it",
                       "shipped": "✅ Shipped", "declined": "🙅 Not this time"}
_STATUS_ORDER = "CASE s.status WHEN 'building' THEN 0 WHEN 'planned' THEN 1 WHEN 'new' THEN 2 WHEN 'shipped' THEN 3 ELSE 4 END"


def add_suggestion(member_id: int, kind: str, body: str) -> int:
    conn = get_db()
    cur = conn.execute("INSERT INTO suggestions (member_id, kind, body) VALUES (?, ?, ?)", (member_id, kind, body))
    conn.commit()
    return cur.lastrowid


def list_suggestions(viewer_id: int | None = None, statuses: tuple[str, ...] | None = None) -> list[sqlite3.Row]:
    """Suggestions with author, +1 count and whether the viewer has voted. Busiest work first."""
    where, params = "", [viewer_id]
    if statuses:
        where = f"WHERE s.status IN ({', '.join('?' for _ in statuses)})"
        params += list(statuses)
    return get_db().execute(
        f"""SELECT s.*, m.name, m.avatar,
                   (SELECT COUNT(*) FROM suggestion_votes v WHERE v.suggestion_id = s.id) AS votes,
                   EXISTS (SELECT 1 FROM suggestion_votes v WHERE v.suggestion_id = s.id AND v.member_id = ?) AS voted
            FROM suggestions s JOIN members m ON m.id = s.member_id
            {where}
            ORDER BY {_STATUS_ORDER}, votes DESC, s.created_at DESC""",
        params,
    ).fetchall()


def toggle_vote(suggestion_id: int, member_id: int) -> None:
    conn = get_db()
    with conn:
        removed = conn.execute("DELETE FROM suggestion_votes WHERE suggestion_id = ? AND member_id = ?",
                               (suggestion_id, member_id)).rowcount
        if not removed:
            conn.execute("INSERT INTO suggestion_votes (suggestion_id, member_id) VALUES (?, ?)",
                         (suggestion_id, member_id))


def suggestion_exists(suggestion_id: int) -> bool:
    return get_db().execute("SELECT 1 FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone() is not None


def set_suggestion_status(suggestion_id: int, status: str, response: str) -> None:
    conn = get_db()
    conn.execute("UPDATE suggestions SET status = ?, response = ?, updated_at = datetime('now') WHERE id = ?",
                 (status, response, suggestion_id))
    conn.commit()


# --- case lifecycle ---------------------------------------------------------------------

def set_case_status(biscuit_id: int, closed: bool) -> None:
    conn = get_db()
    with conn:
        conn.execute(
            "UPDATE biscuits SET case_status = ?, closed_at = CASE WHEN ? THEN datetime('now') END WHERE id = ?",
            ("closed" if closed else "open", int(closed), biscuit_id),
        )
        if not closed:  # reopening settles any outstanding requests for it
            conn.execute("""UPDATE reopen_requests SET status = 'approved', resolved_at = datetime('now')
                            WHERE biscuit_id = ? AND status = 'pending'""", (biscuit_id,))


def add_reopen_request(biscuit_id: int, member_id: int, note: str) -> bool:
    """False if this agent already has a pending request for this biscuit."""
    conn = get_db()
    if conn.execute("SELECT 1 FROM reopen_requests WHERE biscuit_id = ? AND member_id = ? AND status = 'pending'",
                    (biscuit_id, member_id)).fetchone():
        return False
    conn.execute("INSERT INTO reopen_requests (biscuit_id, member_id, note) VALUES (?, ?, ?)",
                 (biscuit_id, member_id, note))
    conn.commit()
    return True


def pending_reopen_requests() -> list[sqlite3.Row]:
    return get_db().execute(
        """SELECT q.*, b.name AS biscuit, m.name AS member, m.avatar
           FROM reopen_requests q JOIN biscuits b ON b.id = q.biscuit_id JOIN members m ON m.id = q.member_id
           WHERE q.status = 'pending' ORDER BY q.created_at"""
    ).fetchall()


def decline_reopen_request(request_id: int) -> None:
    conn = get_db()
    conn.execute("UPDATE reopen_requests SET status = 'declined', resolved_at = datetime('now') WHERE id = ?",
                 (request_id,))
    conn.commit()


def reopen_request_count(biscuit_id: int) -> int:
    return get_db().execute("SELECT COUNT(*) FROM reopen_requests WHERE biscuit_id = ? AND status = 'pending'",
                            (biscuit_id,)).fetchone()[0]


# --- thumbs-up on field notes -----------------------------------------------------------

def rating_owner(rating_id: int) -> sqlite3.Row | None:
    return get_db().execute("SELECT member_id, biscuit_id FROM ratings WHERE id = ?", (rating_id,)).fetchone()


def toggle_report_vote(rating_id: int, member_id: int) -> None:
    conn = get_db()
    with conn:
        removed = conn.execute("DELETE FROM report_votes WHERE rating_id = ? AND member_id = ?",
                               (rating_id, member_id)).rowcount
        if not removed:
            conn.execute("INSERT INTO report_votes (rating_id, member_id) VALUES (?, ?)", (rating_id, member_id))


def report_votes(biscuit_id: int, viewer_id: int) -> dict[int, dict]:
    """{rating_id: {"count": n, "mine": bool}} for one biscuit's reports."""
    rows = get_db().execute(
        """SELECT v.rating_id, COUNT(*) AS n, MAX(v.member_id = ?) AS mine
           FROM report_votes v JOIN ratings r ON r.id = v.rating_id
           WHERE r.biscuit_id = ? GROUP BY v.rating_id""",
        (viewer_id, biscuit_id),
    ).fetchall()
    return {r["rating_id"]: {"count": r["n"], "mine": bool(r["mine"])} for r in rows}


# --- biscuit points ---------------------------------------------------------------------

def points_activity(member_id: int | None = None) -> list[sqlite3.Row]:
    """Per active agent, the activity counts that points.RULES turn into Biscuit Points."""
    where, params = ("AND m.id = ?", (member_id,)) if member_id is not None else ("", ())
    return get_db().execute(
        f"""SELECT m.id, m.name, m.avatar,
              (SELECT COUNT(*) FROM ratings r WHERE r.member_id = m.id) AS reports,
              (SELECT COUNT(*) FROM ratings r WHERE r.member_id = m.id
                 AND length(trim(r.comment)) >= {NOTE_MIN_CHARS}) AS notes,
              (SELECT COUNT(*) FROM report_votes v JOIN ratings r ON r.id = v.rating_id
                 WHERE r.member_id = m.id AND v.member_id != m.id) AS thumbs,
              (SELECT COUNT(*) FROM biscuits b WHERE b.added_by = m.id AND b.active = 1) AS specimens,
              (SELECT COUNT(*) FROM drops d WHERE d.added_by = m.id AND d.active = 1) AS drops,
              (SELECT COUNT(*) FROM suggestions s WHERE s.member_id = m.id) AS suggestions,
              (SELECT COUNT(*) FROM suggestions s WHERE s.member_id = m.id AND s.status = 'shipped') AS shipped
            FROM members m
            WHERE m.active = 1 {where}
            ORDER BY m.name COLLATE NOCASE""",
        params,
    ).fetchall()


# --- the shop ---------------------------------------------------------------------------

def points_spent(member_id: int) -> int:
    return get_db().execute("SELECT COALESCE(SUM(cost), 0) FROM purchases WHERE member_id = ?",
                            (member_id,)).fetchone()[0]


def inventory(member_id: int) -> list[sqlite3.Row]:
    """Everything this agent owns, with where it came from (shop | loot) and when."""
    return get_db().execute("SELECT item_key, source, cost, created_at FROM purchases WHERE member_id = ? ORDER BY id",
                            (member_id,)).fetchall()


def owned_items(member_id: int) -> set[str]:
    return {r[0] for r in get_db().execute("SELECT item_key FROM purchases WHERE member_id = ?", (member_id,))}


def ledger_total(member_id: int) -> int:
    return get_db().execute("SELECT COALESCE(SUM(delta), 0) FROM ledger WHERE member_id = ?",
                            (member_id,)).fetchone()[0]


def ledger_add(member_id: int, delta: int, reason: str, ref: str = "", conn=None) -> None:
    """Record a points movement. Pass `conn` to join a caller's transaction."""
    (conn or get_db()).execute("INSERT INTO ledger (member_id, delta, reason, ref) VALUES (?, ?, ?, ?)",
                               (member_id, delta, reason, ref))
    if conn is None:
        get_db().commit()


def grant_loot(member_id: int, item_key: str, cost: int, refund: int, reason: str) -> None:
    """One transaction: pay for the tin, then either own the item or bank the refund."""
    conn = get_db()
    with conn:
        ledger_add(member_id, -cost, reason, "tin", conn)
        if refund:
            ledger_add(member_id, refund, f"{reason}: points back", "tin", conn)
        if item_key:
            conn.execute("INSERT OR IGNORE INTO purchases (member_id, item_key, cost, source) VALUES (?, ?, 0, 'loot')",
                         (member_id, item_key))


# --- duels ------------------------------------------------------------------------------
# Stakes are escrowed through the ledger: the challenger's on challenge, the opponent's on
# accept. The pot (2 x wager) goes to the winner; draws, declines and cancels refund.

def create_duel(challenger: int, opponent: int, wager: int, iou: bool) -> int:
    conn = get_db()
    with conn:
        cur = conn.execute("INSERT INTO duels (challenger_id, opponent_id, wager, biscuit_iou) VALUES (?, ?, ?, ?)",
                           (challenger, opponent, wager, int(iou)))
        if wager:
            ledger_add(challenger, -wager, "Duel stake (held)", f"duel/{cur.lastrowid}", conn)
    return cur.lastrowid


def get_duel(duel_id: int) -> sqlite3.Row | None:
    return get_db().execute(
        """SELECT d.*, c.name AS challenger, c.avatar AS c_avatar, o.name AS opponent, o.avatar AS o_avatar
           FROM duels d JOIN members c ON c.id = d.challenger_id JOIN members o ON o.id = d.opponent_id
           WHERE d.id = ?""", (duel_id,)
    ).fetchone()


def duel_moves(duel_id: int) -> list[tuple[int, int, str]]:
    return [(r["round"], r["member_id"], r["move"]) for r in
            get_db().execute("SELECT round, member_id, move FROM duel_moves WHERE duel_id = ?", (duel_id,))]


def accept_duel(duel_id: int, opponent: int, wager: int) -> bool:
    conn = get_db()
    with conn:
        ok = conn.execute("""UPDATE duels SET status = 'active', accepted_at = datetime('now')
                             WHERE id = ? AND opponent_id = ? AND status = 'pending'""",
                          (duel_id, opponent)).rowcount == 1
        if ok and wager:
            ledger_add(opponent, -wager, "Duel stake (held)", f"duel/{duel_id}", conn)
    return ok


def close_pending_duel(duel_id: int, status: str) -> bool:
    """Decline (opponent) or cancel (challenger) a pending duel; refunds the challenger's stake."""
    conn = get_db()
    with conn:
        d = conn.execute("SELECT * FROM duels WHERE id = ? AND status = 'pending'", (duel_id,)).fetchone()
        if d is None:
            return False
        conn.execute("UPDATE duels SET status = ?, finished_at = datetime('now') WHERE id = ?", (status, duel_id))
        if d["wager"]:
            ledger_add(d["challenger_id"], d["wager"], f"Duel {status}: stake back", f"duel/{duel_id}", conn)
    return True


def add_move(duel_id: int, rnd: int, member_id: int, move: str) -> bool:
    conn = get_db()
    try:
        with conn:
            conn.execute("INSERT INTO duel_moves (duel_id, round, member_id, move) VALUES (?, ?, ?, ?)",
                         (duel_id, rnd, member_id, move))
        return True
    except sqlite3.IntegrityError:
        return False  # already moved this round (double tap)


def finish_duel(duel_id: int, winner_id: int | None) -> bool:
    """Settle exactly once: the status guard means two simultaneous final moves can't pay twice."""
    conn = get_db()
    with conn:
        d = conn.execute("SELECT * FROM duels WHERE id = ?", (duel_id,)).fetchone()
        settled = conn.execute("""UPDATE duels SET status = 'done', winner_id = ?, finished_at = datetime('now')
                                  WHERE id = ? AND status = 'active'""", (winner_id, duel_id)).rowcount == 1
        if settled and d["wager"]:
            ref = f"duel/{duel_id}"
            if winner_id is None:
                ledger_add(d["challenger_id"], d["wager"], "Duel drawn: stake back", ref, conn)
                ledger_add(d["opponent_id"], d["wager"], "Duel drawn: stake back", ref, conn)
            else:
                ledger_add(winner_id, 2 * d["wager"], "Duel won: the pot", ref, conn)
    return settled


def list_duels(member_id: int | None = None, limit: int = 40) -> list[sqlite3.Row]:
    where, params = ("WHERE d.challenger_id = ? OR d.opponent_id = ?", (member_id, member_id)) \
        if member_id is not None else ("", ())
    return get_db().execute(
        f"""SELECT d.*, c.name AS challenger, c.avatar AS c_avatar, o.name AS opponent, o.avatar AS o_avatar,
                   w.name AS winner
            FROM duels d JOIN members c ON c.id = d.challenger_id JOIN members o ON o.id = d.opponent_id
            LEFT JOIN members w ON w.id = d.winner_id
            {where} ORDER BY d.id DESC LIMIT ?""", (*params, limit)
    ).fetchall()


def mark_iou_paid(duel_id: int, winner_id: int) -> bool:
    conn = get_db()
    with conn:
        return conn.execute("""UPDATE duels SET iou_paid = 1 WHERE id = ? AND winner_id = ?
                               AND biscuit_iou = 1 AND status = 'done'""", (duel_id, winner_id)).rowcount == 1


def duel_records() -> list[sqlite3.Row]:
    return get_db().execute(
        """SELECT m.id, m.name, m.avatar,
                  SUM(d.winner_id = m.id) AS wins,
                  SUM(d.winner_id IS NOT NULL AND d.winner_id != m.id) AS losses,
                  SUM(d.winner_id IS NULL) AS draws
           FROM members m JOIN duels d ON (d.challenger_id = m.id OR d.opponent_id = m.id) AND d.status = 'done'
           WHERE m.active = 1 GROUP BY m.id ORDER BY wins DESC, losses ASC, m.name"""
    ).fetchall()


# --- dunk-o-meter ---------------------------------------------------------------------

def add_dunk(member_id: int, biscuit_id: int, seconds: float, drink: str) -> None:
    conn = get_db()
    conn.execute("INSERT INTO dunks (member_id, biscuit_id, seconds, drink) VALUES (?, ?, ?, ?)",
                 (member_id, biscuit_id, round(seconds, 2), drink))
    conn.commit()


def dunk_hall_of_fame(limit: int = 10) -> list[sqlite3.Row]:
    return get_db().execute(
        """SELECT k.*, m.name AS agent, m.avatar, b.name AS biscuit FROM dunks k
           JOIN members m ON m.id = k.member_id JOIN biscuits b ON b.id = k.biscuit_id AND b.active = 1
           WHERE k.active = 1
           ORDER BY k.seconds DESC LIMIT ?""", (limit,)
    ).fetchall()


def dunk_by_biscuit() -> list[sqlite3.Row]:
    """Per biscuit: dunks logged, average and best survival time."""
    return get_db().execute(
        """SELECT b.id, b.name, COUNT(k.id) AS n, AVG(k.seconds) AS avg_s, MAX(k.seconds) AS best_s
           FROM biscuits b JOIN dunks k ON k.biscuit_id = b.id AND k.active = 1 WHERE b.active = 1
           GROUP BY b.id ORDER BY avg_s DESC"""
    ).fetchall()


# --- control room -----------------------------------------------------------------------

def get_settings() -> dict[str, str]:
    return {r["key"]: r["value"] for r in get_db().execute("SELECT key, value FROM settings")}


def set_setting(key: str, value: str) -> None:
    conn = get_db()
    with conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                     "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))


def all_dunks(limit: int = 60) -> list[sqlite3.Row]:
    return get_db().execute(
        """SELECT k.*, m.name AS agent, b.name AS biscuit FROM dunks k
           JOIN members m ON m.id = k.member_id JOIN biscuits b ON b.id = k.biscuit_id
           ORDER BY k.id DESC LIMIT ?""", (limit,)
    ).fetchall()


def toggle_dunk(dunk_id: int) -> None:
    conn = get_db()
    conn.execute("UPDATE dunks SET active = 1 - active WHERE id = ?", (dunk_id,))
    conn.commit()


def all_prices(limit: int = 80) -> list[sqlite3.Row]:
    return get_db().execute(
        """SELECT p.*, s.name AS shop, b.name AS biscuit, m.name AS reporter FROM prices p
           JOIN shops s ON s.id = p.shop_id JOIN biscuits b ON b.id = p.biscuit_id
           LEFT JOIN members m ON m.id = p.member_id ORDER BY p.id DESC LIMIT ?""", (limit,)
    ).fetchall()


def admin_grants(limit: int = 30) -> list[sqlite3.Row]:
    return get_db().execute(
        """SELECT l.*, m.name AS agent FROM ledger l JOIN members m ON m.id = l.member_id
           WHERE l.ref = 'admin' ORDER BY l.id DESC LIMIT ?""", (limit,)
    ).fetchall()


def clear_rarity_votes(biscuit_id: int) -> None:
    conn = get_db()
    conn.execute("DELETE FROM rarity_votes WHERE biscuit_id = ?", (biscuit_id,))
    conn.commit()


def void_duel(duel_id: int) -> bool:
    """Admin: call off a pending or active duel and refund every stake that was held."""
    conn = get_db()
    with conn:
        d = conn.execute("SELECT * FROM duels WHERE id = ? AND status IN ('pending', 'active')", (duel_id,)).fetchone()
        if d is None:
            return False
        conn.execute("UPDATE duels SET status = 'cancelled', finished_at = datetime('now') WHERE id = ?", (duel_id,))
        if d["wager"]:
            ref = f"duel/{duel_id}"
            ledger_add(d["challenger_id"], d["wager"], "Duel voided by control room: stake back", ref, conn)
            if d["status"] == "active":  # the opponent's stake was only held once they accepted
                ledger_add(d["opponent_id"], d["wager"], "Duel voided by control room: stake back", ref, conn)
    return True


def set_iou(duel_id: int, paid: int) -> None:
    """Admin: 1 = mark paid, 2 = void (forgiven)."""
    conn = get_db()
    conn.execute("UPDATE duels SET iou_paid = ? WHERE id = ? AND biscuit_iou = 1", (paid, duel_id))
    conn.commit()


def recent_ledger(member_id: int, limit: int = 12) -> list[sqlite3.Row]:
    return get_db().execute("SELECT * FROM ledger WHERE member_id = ? ORDER BY id DESC LIMIT ?",
                            (member_id, limit)).fetchall()


def buy(member_id: int, item_key: str, cost: int, balance: int) -> str | None:
    """Record a purchase. Returns an error message, or None on success.

    `balance` is checked here *and* the insert is guarded by UNIQUE, so two fast taps can't buy
    the same item twice. (Two different items bought in the same instant could in theory both
    pass the balance check; for ~10 agents buying cosmetics that race isn't worth a lock.)
    """
    if cost > balance:
        return f"You need {cost - balance} more points for that."
    conn = get_db()
    try:
        with conn:
            conn.execute("INSERT INTO purchases (member_id, item_key, cost) VALUES (?, ?, ?)",
                         (member_id, item_key, cost))
    except sqlite3.IntegrityError:
        return "You already own that."
    return None


def equip(member_id: int, slot: str, item_key: str | None) -> None:
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM equipped WHERE member_id = ? AND slot = ?", (member_id, slot))
        if item_key:
            conn.execute("INSERT INTO equipped (member_id, slot, item_key) VALUES (?, ?, ?)",
                         (member_id, slot, item_key))


def equipped_items() -> dict[int, list[str]]:
    """{member_id: [equipped item keys]} for everyone: small enough to load once per page."""
    out: dict[int, list[str]] = {}
    for r in get_db().execute("SELECT member_id, item_key FROM equipped"):
        out.setdefault(r["member_id"], []).append(r["item_key"])
    return out


# --- radar: shops and prices -------------------------------------------------------------

def list_shops(include_hidden: bool = False) -> list[sqlite3.Row]:
    return get_db().execute("SELECT * FROM shops WHERE active = 1 OR ? ORDER BY name COLLATE NOCASE",
                            (int(include_hidden),)).fetchall()


def get_shop(shop_id: int) -> sqlite3.Row | None:
    return get_db().execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()


def add_shop(shop: dict, member_id: int | None) -> int | None:
    """Insert a shop; returns its id, or None if that OpenStreetMap ref is already imported."""
    conn = get_db()
    try:
        with conn:
            cur = conn.execute(
                """INSERT INTO shops (osm_ref, name, brand, kind, lat, lng, postcode, added_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (shop.get("osm_ref"), shop["name"], shop.get("brand", ""), shop.get("kind", ""),
                 shop["lat"], shop["lng"], shop.get("postcode", ""), member_id),
            )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def toggle_shop(shop_id: int) -> None:
    conn = get_db()
    conn.execute("UPDATE shops SET active = 1 - active WHERE id = ?", (shop_id,))
    conn.commit()


def add_price(shop_id: int, biscuit_id: int, pence: int, pack: str, member_id: int) -> None:
    conn = get_db()
    conn.execute("INSERT INTO prices (shop_id, biscuit_id, pence, pack, member_id) VALUES (?, ?, ?, ?, ?)",
                 (shop_id, biscuit_id, pence, pack, member_id))
    conn.commit()


def current_prices() -> list[sqlite3.Row]:
    """The latest report per (shop, biscuit), for active shops and biscuits."""
    return get_db().execute(
        """SELECT p.*, b.name AS biscuit, m.name AS reporter
           FROM prices p
           JOIN biscuits b ON b.id = p.biscuit_id AND b.active = 1
           JOIN shops s ON s.id = p.shop_id AND s.active = 1
           LEFT JOIN members m ON m.id = p.member_id
           WHERE p.active = 1
             AND p.id = (SELECT MAX(p2.id) FROM prices p2
                         WHERE p2.shop_id = p.shop_id AND p2.biscuit_id = p.biscuit_id AND p2.active = 1)
           ORDER BY b.name COLLATE NOCASE, p.pence"""
    ).fetchall()


def prices_for_biscuit(biscuit_id: int) -> list[sqlite3.Row]:
    """Every price report for one biscuit, newest first, including retracted ones (admin edit)."""
    return get_db().execute(
        """SELECT p.*, s.name AS shop, m.name AS reporter FROM prices p
           JOIN shops s ON s.id = p.shop_id LEFT JOIN members m ON m.id = p.member_id
           WHERE p.biscuit_id = ? ORDER BY p.id DESC""", (biscuit_id,)
    ).fetchall()


def update_price(price_id: int, pence: int, pack: str) -> None:
    conn = get_db()
    conn.execute("UPDATE prices SET pence = ?, pack = ? WHERE id = ?", (pence, pack, price_id))
    conn.commit()


def toggle_price(price_id: int) -> None:
    conn = get_db()
    conn.execute("UPDATE prices SET active = 1 - active WHERE id = ?", (price_id,))
    conn.commit()


def update_shop(shop_id: int, name: str) -> None:
    conn = get_db()
    conn.execute("UPDATE shops SET name = ? WHERE id = ?", (name, shop_id))
    conn.commit()


# --- admin edits ------------------------------------------------------------------------

def update_biscuit(biscuit_id: int, name: str, brand: str, rarity_override: str | None) -> None:
    conn = get_db()
    conn.execute("UPDATE biscuits SET name = ?, brand = ?, rarity_override = ? WHERE id = ?",
                 (name, brand, rarity_override, biscuit_id))
    conn.commit()


def update_member(member_id: int, name: str, avatar: str) -> None:
    conn = get_db()
    conn.execute("UPDATE members SET name = ?, avatar = ? WHERE id = ?", (name, avatar, member_id))
    conn.commit()


def get_member(member_id: int) -> sqlite3.Row | None:
    return get_db().execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()


# --- rarity votes -----------------------------------------------------------------------

def vote_rarity(biscuit_id: int, member_id: int, tier: str) -> None:
    conn = get_db()
    with conn:
        conn.execute("""INSERT INTO rarity_votes (biscuit_id, member_id, tier) VALUES (?, ?, ?)
                        ON CONFLICT (biscuit_id, member_id) DO UPDATE SET tier = excluded.tier""",
                     (biscuit_id, member_id, tier))


def rarity_votes() -> dict[int, list[str]]:
    """{biscuit_id: [tier, ...]}: all votes, small enough to load per page."""
    out: dict[int, list[str]] = {}
    for r in get_db().execute("SELECT biscuit_id, tier FROM rarity_votes"):
        out.setdefault(r["biscuit_id"], []).append(r["tier"])
    return out


def my_rarity_vote(biscuit_id: int, member_id: int) -> str | None:
    row = get_db().execute("SELECT tier FROM rarity_votes WHERE biscuit_id = ? AND member_id = ?",
                           (biscuit_id, member_id)).fetchone()
    return row["tier"] if row else None


# --- drops ------------------------------------------------------------------------------

DROP_FIELDS = ("name", "brand", "kind", "starts_on", "ends_on", "shops", "source_url", "notes", "biscuit_id")


def list_drops(include_hidden: bool = False) -> list[sqlite3.Row]:
    return get_db().execute(
        """SELECT d.*, a.name AS added_by_name, u.name AS updated_by_name
           FROM drops d
           LEFT JOIN members a ON a.id = d.added_by
           LEFT JOIN members u ON u.id = d.updated_by
           WHERE d.active = 1 OR ?
           ORDER BY COALESCE(d.starts_on, '9999'), d.name COLLATE NOCASE""",
        (int(include_hidden),),
    ).fetchall()


def get_drop(drop_id: int) -> sqlite3.Row | None:
    return get_db().execute("SELECT * FROM drops WHERE id = ?", (drop_id,)).fetchone()


def add_drop(values: dict, member_id: int | None) -> int:
    conn = get_db()
    cur = conn.execute(
        f"INSERT INTO drops ({', '.join(DROP_FIELDS)}, added_by, updated_by) "
        f"VALUES ({', '.join('?' for _ in DROP_FIELDS)}, ?, ?)",
        (*(values[f] for f in DROP_FIELDS), member_id, member_id),
    )
    conn.commit()
    return cur.lastrowid


def update_drop(drop_id: int, values: dict, member_id: int | None) -> None:
    conn = get_db()
    conn.execute(
        f"UPDATE drops SET {', '.join(f'{f} = ?' for f in DROP_FIELDS)}, updated_by = ?, "
        f"updated_at = datetime('now') WHERE id = ?",
        (*(values[f] for f in DROP_FIELDS), member_id, drop_id),
    )
    conn.commit()


def toggle_drop(drop_id: int) -> None:
    conn = get_db()
    conn.execute("UPDATE drops SET active = 1 - active WHERE id = ?", (drop_id,))
    conn.commit()


def member_ratings(member_id: int) -> dict[int, float]:
    """{biscuit_id: this agent's own overall} for their ratings. Their own data, so no blind-rating issue."""
    rows = get_db().execute(
        f"SELECT biscuit_id, overall FROM {RATING_OVERALLS} ro WHERE ro.member_id = ?", (member_id,)
    ).fetchall()
    return {r["biscuit_id"]: r["overall"] for r in rows}


@click.command("export-suggestions")
@click.option("--out", "out_dir", default="suggestions", show_default=True,
              help="Folder to write into. Git-ignored: suggestions carry teammates' names and the repo is public.")
@with_appcontext
def export_suggestions(out_dir: str) -> None:
    """Write open suggestions (inbox, planned, building) to a dated Markdown file for the weekly AI session."""
    from datetime import date
    rows = list_suggestions(None, ("new", "planned", "building"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{date.today():%Y-%m-%d}.md"
    lines = [f"# BRT suggestions export {date.today():%Y-%m-%d}", "",
             "Work through these on a branch. Update each one's status in the control room",
             "(/admin/suggestions) and add shipped items to app/roadmap.json. Never commit this file.", ""]
    for s in rows:
        lines += [f"## #{s['id']} [{s['status']}] {SUGGESTION_KINDS.get(s['kind'], s['kind'])}  (+{s['votes']})",
                  f"From: {s['name']} · {s['created_at'][:10]}", "", s["body"], ""]
        if s["response"]:
            lines += [f"> Control room: {s['response']}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    click.echo(f"Wrote {len(rows)} open suggestion(s) to {path}")


# --- CLI --------------------------------------------------------------------------------

@click.command("demo-seed")
@with_appcontext
def demo_seed() -> None:
    """Fill an EMPTY database with demo agents and biscuits, to see the app populated."""
    conn = get_db()
    if conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]:
        raise click.ClickException("Database already has members; demo-seed only runs on an empty DB.")

    agents = ["Ada", "Brunel", "Curie", "Dyson", "Eames"]
    ids = []
    for i, name in enumerate(agents):
        add_member(name, AVATARS[i])
        ids.append(conn.execute("SELECT id FROM members WHERE name = ?", (name,)).fetchone()[0])

    demo = [("Chocolate Hobnob", "McVitie's"), ("Custard Cream", ""), ("Jammie Dodger", "Burton's"),
            ("Rich Tea", ""), ("Bourbon", ""), ("Fig Roll", "")]
    rng = secrets.SystemRandom()
    for name, brand in demo:
        bid = add_biscuit(name, brand, None, rng.choice(ids))
        for mid in ids[: rng.randint(1, len(ids))]:
            upsert_rating(mid, bid, {k: rng.randint(1, 5) for k in CATEGORY_KEYS},
                          rng.choice(["", "", "Solid.", "Would dunk again."]))
    click.echo(f"Seeded {len(agents)} agents and {len(demo)} biscuits.")
