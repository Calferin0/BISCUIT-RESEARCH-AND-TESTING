# BRT: Biscuit Research & Testing 🍪

A small, silly web app for an office team to rate biscuits from their phones. It runs on one PC
on the office network: Flask, SQLite and waitress, with no build step and no cloud.

- **Agents** join from a personal link (no passwords) and file blind "field reports" across 10
  categories. Other people's results stay sealed until you've filed your own.
- **Awards Night** leaderboard: podium, category champions, party-game agent awards, and each
  agent's Soulmate and Nemesis biscuit.
- Photos come from your phone or an Open Food Facts pack-shot search, with duplicate-biscuit and
  duplicate-photo checks.
- **Control room** (admin, only reachable from the host PC itself): recruit agents with QR-code
  join links, see who's live, export CSV.

## Run it

Windows, CPython 3.14:

```powershell
py -3.14 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pytest                 # tests
.\start-brt.bat                      # background server on :8080
.\stop-brt.bat                       # stop (warns if anyone is mid-review)
```

Admin: `http://127.0.0.1:8080/admin/` on the host PC. Teammates use the join links it shows.

Data (database, uploads, log) lives in `%LOCALAPPDATA%\BRT\` and is **never** committed.
`CLAUDE.md` has the architecture and design decisions.
