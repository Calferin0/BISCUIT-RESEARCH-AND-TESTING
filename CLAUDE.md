# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# BRT (Biscuit Research & Testing) — Claude brief

A lightweight, silly, Motion Impossible-themed web app for CF's team (~10 people) to log biscuit
reviews. It runs in the background on CF's Windows PC; teammates on the office Wi-Fi open their
personal link on their phones and rate. Theme: a classified R&D dossier, with "agents", "specimens",
"field reports", rubber stamps and film-set verdicts. It's a fun gag, not company tooling.

**Status (2026-11-06):** live BRT is on schema v9, deployed 09:09: everything through the
control-room powers (feature switches, point grants, removals), the Locker and the points-page
balance fix. 156 tests pass. Backup before the upgrade: `brt.v8-backup.sqlite3`. In use by the team from phones over the office Wi-Fi [MEASURED: 3 agents live].
Git: `github.com/Calferin0/BISCUIT-RESEARCH-AND-TESTING` (CF's personal account; the
CF-Motion-Impossible org repo refused this PC's credentials). It's **public**, so nothing
internal goes in it (see `.gitignore`).

## Decisions (no `00_Planner/` yet, so they live here)
- **D1: code lives in this OneDrive folder, under git** (git added 2026-11-05 at CF's request).
  This deliberately breaks the workspace "code in bitbucket-local" rule, because it's a gag. Risk:
  OneDrive syncing `.git/` can corrupt it, so if git starts misbehaving, move the repo out.
- **D2: data lives outside OneDrive.** The DB, uploads, secret key, log and pid file go in
  `%LOCALAPPDATA%\BRT\` (override with `BRT_DATA_DIR`). `create_app` refuses any path containing
  "OneDrive".
- **D3: stack.** CPython 3.14, Flask, stdlib `sqlite3` in WAL mode, Jinja templates,
  hand-written CSS and a little vanilla JS. `waitress` serves it and `segno` makes the QR codes.
  No framework, no build step, no CDN.
- **D4: identity.** Each member has a personal link `/join/<token>` that sets a long-lived
  httponly cookie (`brt_agent`). There are no passwords. A new token kills the old link.
- **D5: admin auth.** `/admin/*` accepts only `remote_addr` in {127.0.0.1, ::1}, and
  X-Forwarded-For is deliberately ignored. CF must open admin at `127.0.0.1`: the PC's own LAN IP
  gets 403.
- **D6: soft delete.** Members and biscuits toggle `active`. Ratings are never deleted from the UI.
- **D7: scores in long format** (`scores(rating_id, category, value)`, CF 2026-11-05). Categories
  live only in `scoring.CATEGORIES`, so changing them needs no migration. v1's column-per-category
  ratings were parked in `ratings_v1`, not converted.
- **D8: photos.** Sources: upload, an Open Food Facts pick, or a pasted URL (admin only). The
  server always stores a local copy. Any agent can add a missing photo; only admin can replace one.
- **D9: no duplicate biscuits.** An exact name match (normalised, compatible brand) is blocked.
  A near-match needs a "mine is different" tick. An identical photo (same sha256) is rejected.
- **D10: blind rating.** A biscuit's results (scores, verdict, others' reports, its leaderboard
  place and awards) aren't *sent* to an agent until they've filed their own report. Enforced in
  the views and templates, not CSS. After filing, they can still amend with results visible.
- **D11: live presence in memory** (`app/presence.py`, per process). It's fed by page loads plus
  a 25 s JS heartbeat that also flags unsaved form input. The admin "Live now" panel and
  `/admin/live-count` (used by `stop-brt.bat`) read it. **Only correct with a single server
  process** (see D12).
- **D12: single instance.** `run.py` binds with `SO_EXCLUSIVEADDRUSE`. Waitress's default
  SO_REUSEADDR lets several processes share a port on Windows (three copies ran on 2026-11-05
  [MEASURED]). `stop-brt.bat` kills every `.venv\Scripts\pythonw.exe` with `/T`.
- **D13: Dry Land Purists.** Categories marked `skippable` (the dunk pair) can be skipped with
  one tickbox, stored as *no score row*. That makes biscuit overalls the **mean of each rating's
  own average** (`db.RATING_OVERALLS`): one agent, one vote. A raw average over score rows would
  over-weight dunkers.
- **D14: suggestions and the weekly loop** (schema v3, CF 2026-11-05). Suggestions carry the
  author's name, so they stay in the DB and git-ignored exports, **never** in the public repo.
  The weekly AI session works in a **git worktree** (`..\brt-weekly`), never in this folder,
  because the live server runs from here. Live changes only arrive via `deploy-brt.bat`, which
  checks presence, pulls, tests, then restarts. Runbook: `WEEKLY.md`. `app/roadmap.json` drives
  the WORKING ON IT page, is re-read per request (no restart needed) and must cite suggestions
  by `#id`, never by name.
- **D15: Dashboard** (schema v4, 2026-11-05). Drops are **team-entered**: there's no public feed
  of UK biscuit releases, so never invent drops. Any agent can add or correct one; admin hides
  them. The timeline is computed from dates only (`app/drops.py`, pure). "Your next tasting" is
  weighted by the viewer's *own* ratings and by report counts, never others' scores (D10). The
  scouting report uses Open Food Facts' structured query `brands_tags AND categories_tags:en:biscuits
  AND countries_tags:en:united-kingdom` (plain text search drags in non-UK and non-biscuit
  items), is cached 6 h per query, and loads via JS so a slow OFF never blocks the page.
- **D16: case lifecycle** (schema v5, CF 2026-11-05; relaxes D10). A case goes **public**
  7 days after the biscuit was logged, or immediately when **closed** (biscuit gone from shops;
  admin closes, agents *request* reopens, admin approves). The rule lives in `app/cases.py`
  (`can_see`). The leaderboard shows every biscuit's **name and place** to everyone and seals
  only scores and anything derived from them (verdict stamp, award detail, an agent's score for
  it, an agent's "avg given", which is computed only over biscuits the viewer can see). Known
  residual: agent-award details (e.g. Golden Retriever's average) still average over all of an
  agent's reports (2 or more), a blurred hint rather than a single score. Closed cases take no
  new or amended reports.
- **Thumbs-up on field reports** (`report_votes`): only on others' reports, only once you can
  see them. These feed Biscuit Points.
- **Migrations are idempotent:** columns are added via `ADDED_COLUMNS` and only if missing.
- **D17: Biscuit Points are computed, not stored** (`app/points.py` RULES ×
  `db.points_activity()`), so there's no counter to drift and the rules can be retuned freely.
  Spending is a ledger (`purchases`, schema v6, UNIQUE per item): balance = earned − spent.
  **Ranks use lifetime earned**, so shopping never demotes. Cosmetics are agent flair (CF's
  pick): title, name colour, avatar frame (`app/shop.py` catalogue; item keys are permanent).
  The `_agent.html` macro renders flair wherever an agent's name appears.
- **D18: Biscuit Radar** (schema v7, `app/radar.py`, `/radar`). An SVG radar, not a tile map
  (no CDN, no tile-usage limits, works offline). **The centre lives in `DATA_DIR/site.json`, never
  in the repo** (public repo; it's where everyone works). Set it via the control room by postcode
  (postcodes.io). Shops come from an OpenStreetMap Overpass import (admin, deduped on `osm_ref`)
  or are added by agents by postcode. Prices are team-reported with full history; the newest
  per (shop, biscuit) is current. Overpass is slow and often "at capacity" (502), both seen
  2026-11-05 [MEASURED], hence a 45 s timeout and mirror fallback. A live import worked on
  2026-11-05 at 17:18 (26 shops) [MEASURED].
- **Running .bat files from Claude's shell:** the `&` in "R&D" breaks `cmd /c script.bat`. Use
  `Start-Process cmd.exe -ArgumentList ('/s /c ""<full path>\deploy-brt.bat" /yes"')` with
  redirected output. Never pipe a script that starts BRT, because the server inherits the pipe
  and the command never returns.
- **D19: rarity** (`app/rarity.py`, schema v8). Team vote, one vote per agent; the most-voted tier
  wins and ties go to the *rarer* tier. `biscuits.rarity_override` (admin) beats votes.
- **D20: drops never duplicate specimens.** `views.drop_links` resolves a drop to a specimen by
  explicit `drops.biscuit_id`, then exact name, then `drops.auto_link` (every word of a 2+ word
  specimen name appears in the drop name). Linked drops show as "already on file" chips and give
  the specimen an "on shelves now" badge.
- **D21: points ledger.** Balance = earned (computed) − shop spend + `SUM(ledger.delta)`, defined
  once in `views.balance`. Mystery Tins and duel stakes, pots and refunds all go through the
  ledger. Ranks still use lifetime *earned* only.
- **D22: Mystery Tins** (`app/loot.py`). Points only, never money; the odds table is shown in
  full; loot-only cosmetics (`shop.Item.loot_tier`) can't be bought; duplicates convert to points;
  Post/Redirect/Get so a refresh can't open a second tin.
- **D23: Biscuit VS** (`app/duel.py`, pure). Dunk > Snap > Crumble > Dunk; first to 2; draws replay;
  9-round cap. State is rebuilt from `duel_moves` and never stored. Stakes are escrowed via the
  ledger; `db.finish_duel` settles once (status-guarded UPDATE). The opponent's current-round
  move is never rendered until both have played. The "loser buys biscuits" IOU is just a flag
  plus a winner-marked `iou_paid`: no money goes through the app.
- **Auto price sweep: not possible from open data** (checked 2026-11-05: Open Prices had zero
  GBP prices for 100 UK biscuits; supermarket scraping breaks their terms). Prices stay
  team-reported. Don't invent them.
- Fun extras: Biscuit of the Day and horoscope (`app/fun.py`, seeded by date, no storage) and the
  Dunk-O-Meter (`dunks` table, `/dunk`).
- **D24: control room powers** (schema v9). Feature switches (`app/features.py`, `settings`
  table, `feature.<key>` = 1/0, missing = on) hide a feature from the nav and close its routes
  via `@features.required`. Data is never touched. Admin points grants go through the ledger
  (`ref = 'admin'`, ±1000 cap) and show on the agent's points page. Admin can soft-remove dunks,
  retract prices, void duels (refunding held stakes), mark biscuit IOUs paid or forgiven
  (`iou_paid` 1 or 2) and reset rarity votes.
- **Locker** (`/locker`): your look (avatar + equipped flair), avatar picker and inventory
  (shop + loot, by source). **Deliberately not behind the shop switch**: what you own stays wearable.
- **Every balance display must use `views.balance`.** The points page once computed its own
  (earned − shop) and missed the ledger, so Mystery Tins didn't show (CF report, 2026-11-06).
- **Next build:** suggestions from the weekly loop (`WEEKLY.md`).

## Architecture
- `app/__init__.py`: `create_app()` resolves the data dir, loads the agent from the cookie into
  `g.member` on every request, and injects `me`/`CATEGORIES`/`verdict`/`product` into all
  templates.
- `app/db.py`: the schema plus **every** SQL query. One connection per request on `flask.g`.
  `PRAGMA user_version` is the schema version; migrations go in `init_db`. It also has the
  `demo-seed` CLI.
- `app/scoring.py`: the 10 categories (each also defines its leaderboard champion award) and
  verdicts. Keys are stored in `scores.category`: renaming one orphans old scores, so treat keys
  as permanent and change labels freely.
- `app/awards.py`: pure functions (no Flask/SQL) that turn `db.awards_data()` into the leaderboard
  award cards. Ties are shared.
- `app/images.py`: the one path every photo takes (`attach_photo`). It checks magic bytes, never
  the extension, then sha256 dedupe, then saves under a random name. It also has the Open Food
  Facts search (new search API first, legacy endpoint as fallback). Agents can only make the
  server fetch from `images.openfoodfacts.org` (SSRF guard); admin can paste any URL.
- `app/similarity.py`: biscuit-name normalising and fuzzy matching (pure).
- `app/drops.py` (drop validation and timeline buckets) and `app/recommend.py` (tasting picks,
  team brands, OFF scouting with cache): pure or near-pure, used by `/dashboard`.
- `app/views.py` (agent pages, guarded by `@agent_required`, plus `/api/similar`,
  `/api/image-search` and the `/thumb` relay locked to the OFF host) and `app/admin.py` (loopback
  guard in `before_request`, photo replace page, CSV export with formula-injection escaping).
- `app/util.py`: LAN IP detection, QR codes, product images, CSV safety.
- `app/static/img/products/`: Motion Impossible product photos dropped in by CF. The footer
  shows a random one, captioned from its file name.
- E-STOP / WORK MODE button (`base.html` and `brt.js`, on every page): swaps the page for a fake
  work screen, a random image from `app/static/img/work/` or a built-in fake IDE if it's empty.
  Esc or another press exits; while active the button fades until hovered. Client-side only.

## Commands
```powershell
py -3.14 -m venv .venv; .venv\Scripts\pip install -r requirements.txt   # one-time setup
.venv\Scripts\pytest                                                     # all tests
.venv\Scripts\pytest tests\test_ratings.py::test_one_rating_per_member   # single test
.venv\Scripts\flask --app app run --debug --host 0.0.0.0 --port 8080     # dev, auto-reload
$env:BRT_DATA_DIR="<scratch dir>"; .venv\Scripts\flask --app app demo-seed   # demo data (empty DB only)
.\start-brt.bat    # background run via pythonw; log in %LOCALAPPDATA%\BRT\brt.log
.\stop-brt.bat     # warns if agents are live, then kills every .venv pythonw (/force skips the check)
.\export-suggestions.bat   # weekly: open suggestions -> suggestions\YYYY-MM-DD.md (git-ignored)
.\deploy-brt.bat           # weekly: presence check, pull main, pip, pytest, restart (refuses on red tests)
                           # /yes skips the presence question (unattended runs)
```
`.claude/launch.json` has a `brt-demo` preview config on **port 8090** with a scratchpad data
dir. Never point it at the real data dir or port 8080: CF's real BRT runs on 8080, and on
2026-11-05 a demo on 8080 briefly shared the port with it.

## Things every session must know
- **`python` on PATH is MSYS2 (`C:\msys64\ucrt64`).** It makes venvs with a `bin/` layout and
  breaks the scripts. Always use `py -3.14` (the only standard CPython installed) or `.venv\Scripts\…`.
- **LAN reachability is CF's job, not Claude's.** Windows Firewall needs an inbound rule for
  python/port 8080 on a *Private* network profile. Never change firewall, network or system
  settings. Corporate Wi-Fi may isolate clients from each other, so test from a phone first.
- **Join URLs use the live LAN IP** (`util.public_base_url`), never `request.host`: admin is
  viewed from 127.0.0.1, which is useless in a QR code. DHCP can move the IP and make printed QR
  codes stale. On a VPN the detected IP may be wrong, so set `BRT_PUBLIC_HOST`.
- The server dies when the PC sleeps. That's expected, not a bug.
- Open Food Facts' legacy `cgi/search.pl` intermittently returns 503 "temporarily unavailable".
  `search.openfoodfacts.org` is primary for that reason. The built-in browser pane blocks
  third-party image hosts, which is one reason thumbnails go through `/thumb`.
- Leaderboard tone: party-game awards show, but original. No Jackbox names, art or branding.
  Tags tease the biscuits and stay kind to the people.
- **Branding and images:** use only what CF puts in `static/img/products/`. Don't scrape the
  company site and don't invent product names or specs.

## Authorship split
All code is Claude-written (CF's choice for this project), so the workspace hard-10% rule is
waived. Still give the one-line "why" behind design choices.

## Project-specific hard stops
- Never expose the app beyond the LAN: no port forwarding, tunnels (ngrok etc.) or cloud hosting.
- Never put the database or uploads inside this OneDrive folder (D2).
- Any schema change that drops or rewrites existing rating data: back up `brt.sqlite3` first and ask.
