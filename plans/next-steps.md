# Next Steps

- This document tracks the GitHub Pages automation project.
- Priority section is ordered. Mark complete when done.
- Backlog is unordered; items need prioritization before starting.

# Goal

Publish a daily multi-source papers digest as a GitHub Pages site, automatically
updated each morning. Papers from HuggingFace daily picks and Nature topical RSS
feeds are stored as per-day JSON; the site renders them client-side with date and
source selectors. No per-day HTML generation.

# Architecture

```
docs/
    index.html              # single-page site; fetches JSON on demand
    data/
        index.json          # manifest: {dates: [...], sources: [...]}
        cache.json          # paper ID -> extracted fields (avoid re-processing)
        YYYY-MM-DD.json     # one file per day, all sources, 30-day rolling window
scripts/
    fetch_hf.py             # HuggingFace daily papers fetcher
    fetch_nature.py         # Nature RSS feed fetcher
    fetch_papers.py         # orchestrator: runs fetchers, updates data/
```

**Paper ID namespace**: `source:id` (e.g., `hf:2603.12345`,
`nature:10.1038/s41586-026-12345-6`). Cache keyed on this.

**HF papers** (`fetch_hf.py`): fetches `https://huggingface.co/api/daily_papers?date=DATE`,
sorts by `paper.upvotes` descending. LLM extraction: category, task, model,
inputs, outputs, key_results, comments.

**Nature papers** (`fetch_nature.py`): fetches RSS feed(s), parses items by
publication date. LLM extraction schema TBD -- likely hypothesis, methods,
finding, significance (different decomposition from HF/ML papers).

**Site** (`docs/index.html`): date selector (prev/next) + source selector
(prev/next or tabs). Fetches selected day's JSON, filters by source client-side.

**JSON schema** (per paper, HF):
```json
{
  "uid": "hf:2603.12345",
  "source": "hf",
  "id": "2603.12345",
  "title": "...",
  "publishedAt": "2026-03-16T17:52:04.000Z",
  "submittedOnDailyAt": "2026-03-17T02:51:00.207Z",
  "upvotes": 42,
  "projectPage": "https://...",
  "category": "LLM/Reasoning",
  "task": "...",
  "model": "(transformer) ModelName",
  "inputs": "...",
  "outputs": "...",
  "key_results": "...",
  "comments": "..."
}
```

Nature schema TBD.

# Completed

- `setup-repo-structure`
- `build-site`
- `configure-github-pages`
- `write-fetch-script`
- `github-actions-workflow`
- `test-end-to-end`
- `rename-repo`
- `paper-id-namespace`
- `hf-api-date-param`
- `paper-id-cache`
- `nature-schema`
- `nature-rss-feed`

# Priority (Sorted)

- `nature-remaining-feeds`
- `read-unread-markers`
- `rss-feed`
- `digest-search`
- `email-summary`

# Backlog (Unsorted)

- `nature-remaining-feeds` -- Add remaining 7 Nature feeds:
  - `http://www.nature.com/subjects/biophysics.rss`
  - `https://www.nature.com/subjects/biotechnology/nature.rss`
  - `https://www.nature.com/subjects/cell-biology.rss`
  - `http://www.nature.com/subjects/computational-biology-and-bioinformatics.rss`
  - `http://www.nature.com/subjects/mathematics-and-computing.rss`
  - `https://www.nature.com/subjects/neuroscience/nature.rss`
  - `http://www.nature.com/subjects/systems-biology.rss`

- `read-unread-markers` -- Client-side read/unread state stored in
  `localStorage`. Each paper card gets a checkbox or click-to-mark.
  Persists across page loads. No server needed.

- `rss-feed` -- Generate `docs/feed.xml` from `index.json` so the digest
  can be followed in a feed reader.

- `digest-search` -- Add client-side full-text search across loaded JSON.

- `email-summary` -- After daily generation, send a short email of top 3-5
  papers relevant to drug discovery / molecular ML / Bayesian methods.
