# Next Steps

- This document tracks the GitHub Pages automation project.
- Priority section is ordered. Mark complete when done.
- Backlog is unordered; items need prioritization before starting.

# Goal

Publish a daily AI/ML papers digest as a GitHub Pages site, automatically updated
each morning. Papers are stored as per-day JSON files; the site renders them
client-side with a date selector. No per-day HTML generation -- the site is a
single static page.

# Architecture

```
docs/
    index.html              # single-page site; fetches JSON on demand
    data/
        index.json          # manifest: list of available dates
        YYYY-MM-DD.json     # one file per day, 30-day rolling window
```

**Python script** (`scripts/fetch_papers.py`): fetches HF API, filters papers
by `publishedAt` == today, calls Anthropic API for field extraction, writes
`docs/data/YYYY-MM-DD.json`, updates `docs/data/index.json`, prunes entries
older than 30 days.

**Site** (`docs/index.html`): on load, fetches `data/index.json`, populates a
date selector, fetches the selected day's JSON, and renders the table client-side.
Uses the same CSS and filter logic as the original template.

**JSON schema** (per paper):
```json
{
  "id": "2603.12345",
  "title": "...",
  "publishedAt": "2026-03-17T00:00:00Z",
  "githubRepo": "https://github.com/...",
  "category": "LLM/Reasoning",
  "task": "...",
  "model": "(transformer) ModelName",
  "inputs": "...",
  "outputs": "...",
  "key_results": "...",
  "comments": "..."
}
```

# Priority (Sorted)

- `setup-repo-structure`
- `build-site`
- `configure-github-pages`
- `write-fetch-script`
- `github-actions-workflow`
- `test-end-to-end`
- `skill-path-update`
- `rss-feed`
- `digest-search`
- `email-summary`

# Backlog (Unsorted)

- `setup-repo-structure` -- Create `docs/data/`, `scripts/` directories.
  Add `pyproject.toml` with `anthropic` as dependency (uv). Add `docs/data/`
  to `.gitignore` exclusions if needed (it should be tracked).

- `build-site` -- Write `docs/index.html` as a self-contained single-page site.
  On load: fetch `data/index.json`, populate date selector (prev/next arrows +
  date display). On date change: fetch `data/YYYY-MM-DD.json`, render table.
  Reuse CSS and category filter JS from the existing skill template. The date
  selector should default to the most recent available date.
  Include stub data (`docs/data/index.json` + one `docs/data/YYYY-MM-DD.json`
  with a handful of mock papers) so the site renders correctly before real data
  is wired up.

- `write-fetch-script` -- Implement `scripts/fetch_papers.py`:
  - Fetch `https://huggingface.co/api/daily_papers`
  - Filter to papers whose `publishedAt` date matches today (or `--date`)
  - Call Anthropic API to extract structured fields from `ai_summary` and
    `ai_keywords` (single batch call for all papers)
  - Write `docs/data/YYYY-MM-DD.json`
  - Update `docs/data/index.json` (sorted list of available dates)
  - Delete JSON files and index entries older than 30 days
  - CLI: `uv run python scripts/fetch_papers.py [--date YYYY-MM-DD]`

- `github-actions-workflow` -- Create `.github/workflows/daily-digest.yml`:
  - Cron: `0 8 * * *` (08:00 UTC daily)
  - Steps: checkout, install uv, run script, commit + push if changed
  - `ANTHROPIC_API_KEY` as a repo secret
  - Exit cleanly (no commit) if API returns 0 papers for the day

- `configure-github-pages` -- Enable GitHub Pages from `main/docs`. Verify
  `https://jjstankowicz.github.io/hf-digest/` loads and the date selector works.

- `test-end-to-end` -- Run `uv run python scripts/fetch_papers.py` manually.
  Verify JSON output. Open `docs/index.html` locally, confirm rendering. Push
  to main, confirm GitHub Pages serves correctly.

- `skill-path-update` -- The `daily-digest` interactive skill currently uses its
  own copy of the template. Now that the site is client-side, decide whether the
  skill should generate standalone HTML (keeping the old fill-in template) or
  write a JSON file and open the hosted site. Simplest: keep a separate
  standalone template in the skill for interactive sessions.

- `rss-feed` -- Generate `docs/feed.xml` from `index.json` so the digest can be
  followed in a feed reader. Update the workflow to regenerate it on each run.

- `digest-search` -- Add client-side full-text search across all loaded (or
  lazily fetched) JSON files. Lunr.js or a simple regex filter over a merged
  dataset.

- `email-summary` -- After daily generation, send a short email of the top 3-5
  papers most relevant to drug discovery / molecular ML / Bayesian methods.
  GitHub Actions + sendgrid or a mail action.
