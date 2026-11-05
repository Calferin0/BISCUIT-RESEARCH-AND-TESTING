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
from .scoring import AVATARS, CATEGORY_KEYS

SCHEMA_VERSION = 4

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
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
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
    updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

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
        # v2 -> v3 -> v4 only add tables, which SCHEMA's CREATE ... IF NOT EXISTS covers.
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


# --- drops ------------------------------------------------------------------------------

DROP_FIELDS = ("name", "brand", "kind", "starts_on", "ends_on", "shops", "source_url", "notes")


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
