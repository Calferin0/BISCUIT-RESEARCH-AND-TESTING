# Weekly loop: suggestions → AI drafts → you approve → deploy

The live BRT runs from **this folder on `main`**. Nothing edits it directly except `deploy-brt.bat`.

## 1. Export (on the BRT PC)
Double-click `export-suggestions.bat`. It writes `suggestions\YYYY-MM-DD.md`: the open
suggestions with author, +1 votes and status. **Git-ignored**: it has teammates' names, and the
GitHub repo is public.

## 2. AI drafts the changes (in a worktree, never in the live folder)
```powershell
git worktree add ..\brt-weekly -b weekly/2026-11-12   # once per week, with that week's date
```
Open Claude Code in `..\brt-weekly` and say:

> Read `<path to live folder>\suggestions\<date>.md`. Pick the most +1'd suggestions that are
> feasible this week. Implement them with tests. Add a dated entry to `app/roadmap.json`
> "updates", citing suggestion `#ids` with no names. Move roadmap items' status. Commit, push the
> branch and open a PR. Tell me which suggestion ids to mark planned/building/shipped/declined.

Why a worktree: switching branches in the live folder would swap files under the running server.

## 3. You approve
Review the PR on GitHub and merge it into `main`. In the control room → 📮 Suggestions, set each
suggestion's status and reply. People see that on the Ideas tab straight away.

## 4. Deploy (on the BRT PC)
Double-click `deploy-brt.bat`. It checks nobody's mid-review (asks if they are), pulls `main`,
installs requirements, **runs the tests and refuses to restart if they fail**, then restarts BRT.

Roadmap-only edits (`app/roadmap.json`) show without a restart. Code changes need step 4.
