@echo off
rem Weekly step 1: write open suggestions from the live BRT database to suggestions\YYYY-MM-DD.md
rem That folder is git-ignored: suggestions carry teammates' names and the GitHub repo is public.
cd /d "%~dp0"
".venv\Scripts\flask.exe" --app app export-suggestions --out suggestions
