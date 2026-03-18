# Session Handoff

## Context

This project was just renamed from `hf-digest` to `paper-digest`. The folder
rename happens after this session ends. When you resume, the working directory
will be `/home/jj/projects/paper-digest`.

## State at Handoff

- GitHub repo: `jjstankowicz/paper-digest` (rename complete)
- Git remote: `git@github.com:jjstankowicz/paper-digest.git` (updated)
- GitHub Pages: `https://jjstankowicz.github.io/paper-digest/` (will be live
  once Pages rebuilds -- may take a minute after folder rename + reopen)
- Local branch: `main`, clean

## What is Working

- Daily cron at 08:00 UTC fetches HF papers via `scripts/fetch_papers.py`
  and auto-commits to `docs/data/`. First real auto-run is 2026-03-18 08:00 UTC.
- Site at GitHub Pages renders cards with category filters and date prev/next nav.
- `workflow_dispatch` supports `--date YYYY-MM-DD` for manual/backfill runs.
- `ANTHROPIC_API_KEY` is set as a repo secret.

## Immediate Next Task: `rename-repo`

The rename task is 90% done. Verify:
1. `https://jjstankowicz.github.io/paper-digest/` loads correctly
2. `git push` works from the new folder location
3. Mark `rename-repo` complete in `plans/next-steps.md`

## Next Tasks in Order (from next-steps.md)

1. `paper-id-namespace` -- add `uid` (`source:id`) and `source` fields to all
   existing paper records; update fetch script accordingly
2. `hf-api-date-param` -- switch fetch to `?date=YYYY-MM-DD` param (currently
   filters a rolling response; date param returns complete set for that day)
3. `nature-schema` -- brainstorm with user on LLM extraction fields for Nature
   papers (hypothesis / methods / finding / significance vs. ML schema)
4. `nature-rss-feed` -- implement `scripts/fetch_nature.py` for first feed
   (`http://www.nature.com/subjects/physics.rss`)
5. `paper-id-cache` -- `docs/data/cache.json` keyed on `uid` to avoid LLM
   re-processing on reruns

## Key Facts

- Package name: `padi`
- Eight Nature RSS feeds total (see next-steps.md backlog for full list)
- Nature papers: DOI as ID, different schema from HF/ML papers
- Source selector in site UI: prev/next arrow style (same as date selector)
- Read/unread markers: client-side via localStorage, no server needed
- User has dry/witty humor, extensive physics/ML background, prefers brevity
- Always PR/CR (never commit directly to main); Copilot reviews automatically
- Use `uv run python` not `python` or `pip`
