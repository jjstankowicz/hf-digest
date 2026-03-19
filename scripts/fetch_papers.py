"""Orchestrate daily paper fetching from all sources and write per-day JSON.

Usage:
    uv run python scripts/fetch_papers.py [--date YYYY-MM-DD]

If --date is omitted, targets yesterday (UTC). Exits cleanly with no output if
no papers are found for the target date (weekend/holiday).
"""

import argparse
import json
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import anthropic

from fetch_nature import fetch_nature_papers

HF_API_URL = "https://huggingface.co/api/daily_papers"
DATA_DIR = Path(__file__).parent.parent / "docs" / "data"
CACHE_PATH = DATA_DIR / "cache.json"
ROLLING_DAYS = 30
EXTRACTED_FIELDS = ("category", "task", "key_results", "comments", "model_io", "hypotheses")
ARRAY_FIELDS = {"model_io", "hypotheses"}
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
  key_results : 1-2 concrete quantitative results or main findings
  comments    : 1 sentence of your own perspective or a notable caveat
  model_io    : JSON array of {"model": ..., "inputs": [...], "outputs": [...]} objects
                describing the model architecture(s) and data flow; inputs and outputs
                are arrays of typed entities (strings); for ML papers this should
                almost always be non-empty, e.g.
                {"model": "(transformer) GPT-4o", "inputs": ["text prompt"],
                 "outputs": ["text completion"]}; may be [] only if truly absent
  hypotheses  : JSON array of {"hypothesis": ..., "result": ...} objects
                for explicit research questions tested and their outcomes; may be []

Be terse. Do not add fields or wrap in markdown."""


def fetch_hf_papers(target: date) -> list[dict]:
    """Return papers from the HF daily papers API for target date, sorted by upvotes desc."""
    url = f"{HF_API_URL}?date={target.isoformat()}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        papers = json.loads(resp.read())
    papers.sort(key=lambda x: x.get("paper", {}).get("upvotes", 0), reverse=True)
    return papers


def _normalize_cache_entry(entry: dict) -> dict:
    """Ensure a cache entry has all required fields with correct default types."""
    normalized: dict = {}
    for k in EXTRACTED_FIELDS:
        default: list | str = [] if k in ARRAY_FIELDS else ""
        normalized[k] = entry.get(k, default)
    if isinstance(normalized.get("model_io"), list):
        normalized["model_io"] = _normalize_model_io(normalized["model_io"])
    return normalized


def load_cache() -> dict[str, dict]:
    """Load uid -> extracted fields cache from disk, seeding from existing day files if absent."""
    if CACHE_PATH.exists():
        raw = json.loads(CACHE_PATH.read_text())
        return {uid: _normalize_cache_entry(entry) for uid, entry in raw.items()}

    cache: dict[str, dict] = {}
    for f in DATA_DIR.glob("????-??-??.json"):
        for record in json.loads(f.read_text()):
            uid = record.get("uid")
            if uid:
                entry = {}
                for k in EXTRACTED_FIELDS:
                    default: list | str = [] if k in ARRAY_FIELDS else ""
                    entry[k] = record.get(k, default)
                cache[uid] = entry
    CACHE_PATH.write_text(json.dumps(cache, indent=2))
    return cache


def save_cache(cache: dict[str, dict]) -> None:
    """Persist the cache to disk."""
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def _normalize_model_io(model_io: list[dict]) -> list[dict]:
    """Ensure inputs/outputs in each model_io entry are lists, not strings."""
    normalized = []
    for entry in model_io:
        normalized.append({
            "model": entry.get("model", ""),
            "inputs": entry["inputs"] if isinstance(entry.get("inputs"), list) else [entry["inputs"]] if entry.get("inputs") else [],
            "outputs": entry["outputs"] if isinstance(entry.get("outputs"), list) else [entry["outputs"]] if entry.get("outputs") else [],
        })
    return normalized


def extract_fields(papers: list[dict], client: anthropic.Anthropic) -> list[dict]:
    """Call Claude once with all abstracts; return list of extracted field dicts."""
    numbered = "\n\n".join(
        f"[{i + 1}] Title: {p['paper'].get('title', '')}\n"
        f"Abstract: {p['paper'].get('summary', '')}"
        for i, p in enumerate(papers)
    )
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16000,
        system=EXTRACTION_SYSTEM,
        messages=[{"role": "user", "content": numbered}],
    )
    text_blocks = [b.text for b in message.content if b.type == "text"]
    if not text_blocks:
        raise RuntimeError("Claude returned no text content in extraction response")
    text = text_blocks[0].strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    result = json.loads(text)
    if not isinstance(result, list) or not all(isinstance(e, dict) for e in result):
        raise RuntimeError(f"Unexpected extraction response shape: {type(result).__name__}")
    for entry in result:
        if isinstance(entry.get("model_io"), list):
            entry["model_io"] = _normalize_model_io(entry["model_io"])
    return result


def build_records(papers: list[dict], cache: dict[str, dict]) -> list[dict]:
    """Build output records from HF metadata and cached extracted fields."""
    records = []
    for paper in papers:
        p = paper.get("paper", {})
        paper_id = p.get("id", "")
        if not paper_id:
            title = p.get("title", "(no title)")
            print(f"Warning: skipping paper with missing id: {title}", file=sys.stderr)
            continue
        source = "hf"
        uid = f"{source}:{paper_id}"
        fields = cache.get(uid, {})
        records.append(
            {
                "uid": uid,
                "source": source,
                "id": paper_id,
                "title": p.get("title", ""),
                "publishedAt": p.get("publishedAt", ""),
                "submittedOnDailyAt": p.get("submittedOnDailyAt", ""),
                "upvotes": p.get("upvotes", 0),
                "projectPage": (p.get("projectPage") or None),
                "category": fields.get("category", "Systems"),
                "task": fields.get("task", ""),
                "key_results": fields.get("key_results", ""),
                "comments": fields.get("comments", ""),
                "model_io": fields.get("model_io", []),
                "hypotheses": fields.get("hypotheses", []),
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

    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=ROLLING_DAYS)).isoformat()
    dates = [d for d in dates if d >= cutoff]

    index_path.write_text(json.dumps({"dates": dates}))


def prune_old_files(keep_dates: list[str]) -> None:
    """Delete per-day JSON files not in keep_dates."""
    keep = set(keep_dates)
    for f in DATA_DIR.glob("????-??-??.json"):
        if f.stem not in keep:
            f.unlink()


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
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
    print(f"Target date: {target_str}")

    print("Fetching HF papers...")
    papers = fetch_hf_papers(target)
    print(f"  {len(papers)} HF papers found")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = load_cache()

    uncached = [
        p for p in papers
        if p.get("paper", {}).get("id", "") and f"hf:{p['paper']['id']}" not in cache
    ]

    client: anthropic.Anthropic | None = None

    if uncached:
        print(f"  Extracting fields for {len(uncached)} uncached HF papers...")
        client = anthropic.Anthropic()
        extracted = extract_fields(uncached, client)
        if not isinstance(extracted, list) or len(extracted) != len(uncached):
            raise RuntimeError(
                f"Extraction mismatch: expected {len(uncached)} records, got "
                f"{len(extracted) if isinstance(extracted, list) else type(extracted).__name__}"
            )
        for paper, fields in zip(uncached, extracted):
            paper_id = paper["paper"]["id"]
            entry: dict = {}
            for k in EXTRACTED_FIELDS:
                default: list | str = [] if k in ARRAY_FIELDS else ""
                entry[k] = fields.get(k, default)
            entry["category"] = entry["category"] or "Systems"
            cache[f"hf:{paper_id}"] = entry
        save_cache(cache)
    else:
        print("  All HF papers cached")

    hf_records = build_records(papers, cache)

    print("Fetching Nature papers...")
    nature_records = fetch_nature_papers(target, client)
    print(f"  {len(nature_records)} Nature papers found")
    for r in nature_records:
        if r["uid"] not in cache:
            entry = {}
            for k in EXTRACTED_FIELDS:
                default = [] if k in ARRAY_FIELDS else ""
                entry[k] = r.get(k, default)
            entry["category"] = entry["category"] or "Other"
            cache[r["uid"]] = entry
    if nature_records:
        save_cache(cache)

    seen: set[str] = set()
    deduped: list[dict] = []
    for r in hf_records + nature_records:
        if r["uid"] not in seen:
            seen.add(r["uid"])
            deduped.append(r)
    records = deduped

    if not records:
        print("No papers found; exiting.")
        sys.exit(0)

    print(f"Writing {len(records)} total papers to {target_str}.json")
    out_path = DATA_DIR / f"{target_str}.json"
    out_path.write_text(json.dumps(records, indent=2))

    update_index(target_str)

    index_dates = json.loads((DATA_DIR / "index.json").read_text())["dates"]
    prune_old_files(index_dates)


if __name__ == "__main__":
    main()
