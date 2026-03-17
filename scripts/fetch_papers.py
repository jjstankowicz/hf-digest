"""Fetch HuggingFace daily papers, extract structured fields via Claude, write JSON.

Usage:
    uv run python scripts/fetch_papers.py [--date YYYY-MM-DD]

If --date is omitted, targets yesterday (UTC). Exits cleanly with no output if
no papers are found for the target date (weekend/holiday).
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import anthropic

HF_API_URL = "https://huggingface.co/api/daily_papers"
DATA_DIR = Path(__file__).parent.parent / "docs" / "data"
ROLLING_DAYS = 30
CATEGORIES = [
    "Medical",
    "Molecular",
    "Generative",
    "LLM/Reasoning",
    "Agents/RL",
    "Vision",
    "Benchmark",
    "Systems",
]

EXTRACTION_SYSTEM = """\
You are a concise technical analyst. For each paper, extract structured fields
from the abstract. Reply with a JSON array -- one object per paper, preserving
the input order. Use exactly these fields:

  category    : one of Medical | Molecular | Generative | LLM/Reasoning |
                Agents/RL | Vision | Benchmark | Systems
  task        : the specific problem being solved (1 short phrase)
  model       : architecture type and model name, e.g. "(transformer) GPT-4o"
  inputs      : what the model takes as input (1 short phrase)
  outputs     : what the model produces (1 short phrase)
  key_results : 1-2 concrete quantitative results or main findings
  comments    : 1 sentence of your own perspective or a notable caveat

Be terse. Do not add fields or wrap in markdown."""


def fetch_hf_papers() -> list[dict]:
    """Return raw paper objects from the HF daily papers API."""
    with urllib.request.urlopen(HF_API_URL, timeout=30) as resp:
        return json.loads(resp.read())


def filter_papers(raw: list[dict], target: date) -> list[dict]:
    """Return papers submitted to HF daily feed on target date, sorted by upvotes desc."""
    out = []
    for item in raw:
        submitted = item.get("paper", {}).get("submittedOnDailyAt", "")
        if not submitted:
            continue
        try:
            d = datetime.fromisoformat(submitted.replace("Z", "+00:00")).date()
        except ValueError:
            continue
        if d == target:
            out.append(item)
    out.sort(key=lambda x: x.get("paper", {}).get("upvotes", 0), reverse=True)
    return out


def extract_fields(papers: list[dict], client: anthropic.Anthropic) -> list[dict]:
    """Call Claude once with all abstracts; return list of extracted field dicts."""
    numbered = "\n\n".join(
        f"[{i+1}] Title: {p['paper'].get('title', '')}\n"
        f"Abstract: {p['paper'].get('summary', '')}"
        for i, p in enumerate(papers)
    )
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16000,
        system=EXTRACTION_SYSTEM,
        messages=[{"role": "user", "content": numbered}],
    )
    text = next(b.text for b in message.content if b.type == "text")
    # Strip accidental markdown fences
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def build_records(papers: list[dict], extracted: list[dict]) -> list[dict]:
    """Merge HF metadata with Claude-extracted fields into the output schema."""
    records = []
    for paper, fields in zip(papers, extracted):
        p = paper.get("paper", {})
        records.append(
            {
                "id": p.get("id", ""),
                "title": p.get("title", ""),
                "publishedAt": p.get("publishedAt", ""),
                "submittedOnDailyAt": p.get("submittedOnDailyAt", ""),
                "upvotes": p.get("upvotes", 0),
                "projectPage": (p.get("projectPage") or None),
                "category": fields.get("category", "Systems"),
                "task": fields.get("task", ""),
                "model": fields.get("model", ""),
                "inputs": fields.get("inputs", ""),
                "outputs": fields.get("outputs", ""),
                "key_results": fields.get("key_results", ""),
                "comments": fields.get("comments", ""),
            }
        )
    return records


def update_index(target_date: str) -> None:
    """Add target_date to index.json and prune entries older than ROLLING_DAYS."""
    index_path = DATA_DIR / "index.json"
    if index_path.exists():
        dates = json.loads(index_path.read_text())["dates"]
    else:
        dates = []

    if target_date not in dates:
        dates.append(target_date)
    dates.sort()

    cutoff = (date.today() - timedelta(days=ROLLING_DAYS)).isoformat()
    dates = [d for d in dates if d >= cutoff]

    index_path.write_text(json.dumps({"dates": dates}))


def prune_old_files(keep_dates: list[str]) -> None:
    """Delete per-day JSON files not in keep_dates."""
    keep = set(keep_dates)
    for f in DATA_DIR.glob("????-??-??.json"):
        if f.stem not in keep:
            f.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and process HF daily papers.")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date YYYY-MM-DD (default: yesterday UTC)",
    )
    args = parser.parse_args()

    if args.date:
        target = date.fromisoformat(args.date)
    else:
        target = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    target_str = target.isoformat()

    raw = fetch_hf_papers()
    papers = filter_papers(raw, target)

    if not papers:
        sys.exit(0)

    client = anthropic.Anthropic()
    extracted = extract_fields(papers, client)
    records = build_records(papers, extracted)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / f"{target_str}.json"
    out_path.write_text(json.dumps(records, indent=2))

    update_index(target_str)

    index_dates = json.loads((DATA_DIR / "index.json").read_text())["dates"]
    prune_old_files(index_dates)


if __name__ == "__main__":
    main()
