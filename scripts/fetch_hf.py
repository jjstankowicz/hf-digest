"""Fetch and extract HuggingFace daily papers."""

import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

import anthropic

from utils import ARRAY_FIELDS, EXTRACTED_FIELDS, normalize_model_io

HF_API_URL = "https://huggingface.co/api/daily_papers"

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


def fetch_papers(target: date) -> list[dict]:
    """Return papers from the HF daily papers API for target date, sorted by upvotes desc."""
    url = f"{HF_API_URL}?date={target.isoformat()}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        papers = json.loads(resp.read())
    papers.sort(key=lambda x: x.get("paper", {}).get("upvotes", 0), reverse=True)
    return papers


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
            entry["model_io"] = normalize_model_io(entry["model_io"])
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
        uid = f"hf:{paper_id}"
        fields = cache.get(uid, {})
        records.append(
            {
                "uid": uid,
                "source": "hf",
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


def fetch_hf_daily(
    target: date, cache: dict[str, dict]
) -> tuple[list[dict], dict[str, dict]]:
    """Fetch, extract, and build HF records for target date.

    Returns (records, cache_updates) where cache_updates contains only newly
    extracted entries; the caller is responsible for merging into the main cache.
    """
    print("Fetching HF papers...")
    papers = fetch_papers(target)
    print(f"  {len(papers)} HF papers found")

    uncached = [
        p for p in papers
        if p.get("paper", {}).get("id", "") and f"hf:{p['paper']['id']}" not in cache
    ]

    cache_updates: dict[str, dict] = {}
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
            cache_updates[f"hf:{paper_id}"] = entry
    else:
        print("  All HF papers cached")

    merged_cache = {**cache, **cache_updates}
    records = build_records(papers, merged_cache)
    return records, cache_updates
