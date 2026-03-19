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
- `nature-remaining-feeds`
- `per-feed-sources`

# Priority (Sorted)

- `unified-schema`
- `card-rendering`
- `read-unread-markers`
- `digest-search`

# Backlog (Unsorted)

- `unified-schema` -- Redesign extraction schema: replace flat model/inputs/outputs
  scalars and parallel hypotheses[]/results[] arrays with two array-of-object fields:
  `model_io: [{model, inputs, outputs}]` and `hypotheses: [{hypothesis, result}]`.
  LLM decides which (or both) apply per paper; empty arrays are skipped in render.
  Re-ingest all existing dates (no cache migration -- just re-extract cleanly).

- `card-rendering` -- Update card UI to match new schema: render model_io as
  triplets (model | inputs -> outputs), hypotheses as side-by-side pairs,
  move key_results and comments to bottom of card.

- `graph-viz` -- Category theory graph across ML/DL papers: inputs/outputs as
  objects, models as morphisms. Requires unified-schema (model_io tuples) first.
  Needs controlled vocabulary or normalization pass to canonicalize type names.

- `read-unread-markers` -- Client-side read/unread state stored in
  `localStorage`. Each paper card gets a checkbox or click-to-mark.
  Persists across page loads. No server needed.

- `digest-search` -- Add client-side full-text search across loaded JSON.
