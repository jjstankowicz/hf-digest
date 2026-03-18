# Project Context

## Goal

Publish a daily multi-source papers digest as a GitHub Pages site, automatically
updated each morning. Papers from HuggingFace daily picks and Nature topical RSS
feeds are stored as per-day JSON and rendered client-side with date and source
selectors. No per-day HTML generation.

## Two Modes

**Automated pipeline** (primary): Python scripts fetch HF API and Nature RSS feeds,
call the Anthropic API for field extraction, and write per-day JSON to `docs/data/`.
A GitHub Actions cron workflow runs this daily. `docs/index.html` is a single-page
site that renders the JSON client-side with date and source selectors.

**Interactive skill** (secondary): The `daily-digest` Claude Code skill uses browser
MCP tools for in-session review and discussion. It maintains its own standalone
HTML template for interactive sessions.

## GitHub Repository

`git@github.com:jjstankowicz/paper-digest.git`
GitHub Pages: `https://jjstankowicz.github.io/paper-digest/`

# Development Guidelines

## Workflow

For codebase exploration (reading files, tracing modules, investigating structure),
use subagents and report back summaries. Keep the main context for implementation.
Let the user handle commits and pushes to the repository.

## Planning Docs

For active tasks, create a focused planning doc (e.g., `plans/<task-name>.md`) on
the feature branch. These are working documents that get deleted when the branch
merges -- they don't pollute main. `plans/next-steps.md` is permanent (on main);
task-specific docs are ephemeral.

## File Organization

- One file for related simple functions
- Separate files for complex modules (50+ lines)

## Dependencies

- `anthropic`, `requests` or `urllib` (stdlib preferred)
- Minimize beyond that

## PR/CR: Pull requests and code reviews

CRITICAL: Never commit directly to `main`. Always work on a feature branch.
At the START of any task that will involve commits, check `git branch` and create
a new branch if on main. Do not wait for the user to remember -- proactively create
the branch.
Use plain branch names only (e.g., `add-automation`), not slash-prefixed forms.
Do NOT create PRs without explicit user approval. Push the branch and let the user
decide when to PR.
We use Copilot to review PRs.
When done with a branch (as told by the user), create a PR. Copilot review starts
automatically -- do NOT attempt to request it manually.
Share the link to the PR with the user so they can easily access by clicking.
After creating the PR, poll GitHub in the background for Copilot review completion
(do not wait for the user to report that comments are up).
When the review lands, read/respond to/resolve Copilot PR comments.
Include the user in the loop in the process.
When all comments are resolved, merge to main, and delete the remote and local
versions of the branch.

### Copilot Review Polling

After creating a PR, start a background poll loop (Copilot review starts automatically):

```bash
# Poll every 30s until Copilot review appears
while true; do
  count=$(gh api repos/jjstankowicz/paper-digest/pulls/PR_NUM/reviews \
    --jq '[.[] | select(.user.login | test("copilot"))] | length')
  if [ "$count" -gt 0 ]; then
    echo "COPILOT_REVIEW_READY"
    gh api repos/jjstankowicz/paper-digest/pulls/PR_NUM/comments \
      --jq '.[] | {id, path, body: .body[0:120]}'
    break
  fi
  sleep 30
done
```

Run this with `run_in_background`. When the output shows COPILOT_REVIEW_READY,
proceed directly to reading and responding to comments.

### GitHub CLI Safety

Avoid accidental command execution from shell interpolation when using `gh`.

- Never put backticks inside double-quoted shell arguments.
- For `gh pr create`, always use `--body-file`.
- Do not inline markdown command examples with backticks in shell arguments.
- For review replies and long `gh api` bodies, always write message text to a temp
  file and pass it with `-F body=@/tmp/file.md`.
- Keep inline shell message bodies short and plain text only; no markdown code
  spans in inline arguments.

### PR Review Comment Workflow

1. **Read comments:**
   ```bash
   gh api repos/jjstankowicz/paper-digest/pulls/PR_NUM/comments \
     | jq '.[] | {id, path, body: .body[0:80]}'
   ```

2. **Reply to a comment** (use `in_reply_to` with comment ID):
   ```bash
   printf '%s\n' 'Fixed in COMMIT.' > /tmp/reply.md
   gh api repos/jjstankowicz/paper-digest/pulls/PR_NUM/comments \
     -F body=@/tmp/reply.md -F in_reply_to=COMMENT_ID
   ```

3. **Resolve threads** (batch with aliases):
   ```bash
   gh api graphql -f query='
   mutation {
     t1: resolveReviewThread(input: {threadId: "THREAD_ID_1"}) { thread { isResolved } }
   }'
   ```

# Repository Structure

```
paper-digest/
    docs/                              # GitHub Pages root (served from main/docs)
        index.html                     # single-page site; renders JSON client-side
        data/
            index.json                 # manifest of available dates (30-day window)
            cache.json                 # uid -> extracted fields cache
            YYYY-MM-DD.json            # per-day paper data (all sources)
    scripts/
        fetch_papers.py                # orchestrator: runs fetchers, updates data/
        fetch_hf.py                    # HuggingFace daily papers fetcher
        fetch_nature.py                # Nature RSS feed fetcher
    .github/
        workflows/
            daily-digest.yml           # cron schedule, commit, push
    plans/
        next-steps.md
```

# Python Environment

## Package Manager

This project uses uv (not pip, not poetry, not conda).
Do NOT try to activate venvs manually or run pip commands.

## Running Commands

For ad-hoc Python: `uv run python scripts/fetch_papers.py`
Dependencies declared in `pyproject.toml`.

## GitHub Actions

The workflow installs uv and runs `uv run python scripts/fetch_papers.py`.
`ANTHROPIC_API_KEY` is passed as a repository secret.
