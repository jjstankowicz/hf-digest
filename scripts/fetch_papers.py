"""Orchestrate daily paper fetching from all sources and write per-day JSON.

Usage:
    uv run python scripts/fetch_papers.py [--date YYYY-MM-DD]

If --date is omitted, targets yesterday (UTC). Exits cleanly with no output if
no papers are found for the target date (weekend/holiday).
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fetch_hf import fetch_hf_daily
from fetch_nature import fetch_nature_papers
from utils import ARRAY_FIELDS, EXTRACTED_FIELDS, normalize_model_io

DATA_DIR = Path(__file__).parent.parent / "docs" / "data"
CACHE_PATH = DATA_DIR / "cache.json"
ROLLING_DAYS = 30


def _normalize_cache_entry(entry: dict) -> dict:
    """Ensure a cache entry has all required fields with correct default types."""
    normalized: dict = {}
    for k in EXTRACTED_FIELDS:
        default: list | str = [] if k in ARRAY_FIELDS else ""
        normalized[k] = entry.get(k, default)
    if isinstance(normalized.get("model_io"), list):
        normalized["model_io"] = normalize_model_io(normalized["model_io"])
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
    parser = argparse.ArgumentParser(description="Fetch and process daily papers from all sources.")
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

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = load_cache()

    print("Fetching HF and Nature papers concurrently...")
    with ThreadPoolExecutor(max_workers=2) as executor:
        hf_future = executor.submit(fetch_hf_daily, target, cache)
        nature_future = executor.submit(fetch_nature_papers, target)
        hf_records, hf_cache_updates = hf_future.result()
        nature_records = nature_future.result()

    print(f"  {len(hf_records)} HF papers, {len(nature_records)} Nature papers")

    cache.update(hf_cache_updates)
    for r in nature_records:
        if r["uid"] not in cache:
            entry: dict = {}
            for k in EXTRACTED_FIELDS:
                default: list | str = [] if k in ARRAY_FIELDS else ""
                entry[k] = r.get(k, default)
            entry["category"] = entry["category"] or "Other"
            cache[r["uid"]] = entry
    if hf_cache_updates or nature_records:
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
