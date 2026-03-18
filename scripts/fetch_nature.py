"""Fetch Nature RSS feed papers, scrape abstracts, extract fields via Claude.

Usage (standalone):
    uv run python scripts/fetch_nature.py [--date YYYY-MM-DD]

Returns a list of paper records conforming to the unified schema.
Intended to be called by fetch_papers.py, not run directly in production.
"""

import re
import time
import urllib.request
from datetime import date
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import anthropic

PHYSICS_FEED = "https://www.nature.com/subjects/physics.rss"

# Maps Nature article slug prefix to journal name.
JOURNAL_CODES: dict[str, str] = {
    "41467": "Nature Communications",
    "41524": "npj Computational Materials",
    "41560": "Nature Energy",
    "41566": "Nature Photonics",
    "41567": "Nature Physics",
    "41598": "Scientific Reports",
    "41928": "Nature Electronics",
    "42005": "Communications Physics",
    "44172": "Nature Reviews Physics",
    "44182": "Nature Reviews Materials",
}

PHYSICS_CATEGORIES = [
    "Condensed Matter",
    "Quantum",
    "High Energy/Particle",
    "Astrophysics/Cosmology",
    "Optics/Photonics",
    "Mathematical Physics",
    "Applied Physics",
    "Other",
]

EXTRACTION_SYSTEM = """\
You are a concise technical analyst. For each paper, extract structured fields
from the abstract. Reply with a JSON array -- one object per paper, preserving
the input order. Use exactly these fields:

  category    : one of {categories}
  task        : the specific problem being solved (1 short phrase)
  model       : theoretical framework or experimental system, e.g. "(tight-binding) Bose-Hubbard"
                or "(experiment) optical lattice"; use "N/A" if not applicable
  inputs      : what the system takes as input or initial conditions (1 short phrase)
  outputs     : what is measured or derived (1 short phrase)
  key_results : 1-2 concrete quantitative results or main findings
  comments    : 1 sentence of your own perspective or a notable caveat
  hypotheses  : JSON array of hypotheses or research questions tested (may be empty)
  results     : JSON array of outcomes aligned to hypotheses (same length; may be empty)

Be terse. Do not add fields or wrap in markdown.""".format(
    categories=" | ".join(PHYSICS_CATEGORIES)
)


def fetch_feed(feed_url: str) -> list[ET.Element]:
    """Return all <item> elements from an RSS feed URL."""
    with urllib.request.urlopen(feed_url, timeout=30) as resp:
        root = ET.fromstring(resp.read())
    return root.findall(".//item")


def parse_item_date(item: ET.Element) -> date | None:
    """Parse pubDate from an RSS item; return date or None on failure."""
    pub = item.findtext("pubDate", "")
    if not pub:
        return None
    try:
        return parsedate_to_datetime(pub).date()
    except Exception:
        return None


def slug_to_doi(slug: str) -> str:
    """Convert a Nature article slug to a DOI (10.1038/slug)."""
    return f"10.1038/{slug}"


def slug_to_journal(slug: str) -> str:
    """Derive journal name from article slug."""
    m = re.match(r"s(\d+)-", slug)
    if m:
        return JOURNAL_CODES.get(m.group(1), "Nature Portfolio")
    return "Nature Portfolio"


def scrape_abstract(url: str) -> str | None:
    """Fetch a Nature article page and extract the abstract text, or None if unavailable."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        m = re.search(r'id="Abs1-content".*?<p>(.*?)</p>', html, re.DOTALL)
        if m:
            # Strip any inline HTML tags
            return re.sub(r"<[^>]+>", "", m.group(1)).strip()
    except Exception:
        pass
    return None


def filter_items(items: list[ET.Element], target: date) -> list[ET.Element]:
    """Return items published on target date."""
    return [it for it in items if parse_item_date(it) == target]


def extract_fields(papers: list[dict], client: anthropic.Anthropic) -> list[dict]:
    """Call Claude once with all abstracts; return list of extracted field dicts."""
    numbered = "\n\n".join(
        f"[{i + 1}] Title: {p['title']}\nAbstract: {p['abstract']}"
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
    import json
    return json.loads(text)


def fetch_nature_papers(target: date, client: anthropic.Anthropic) -> list[dict]:
    """Fetch Nature physics papers for target date, scrape abstracts, extract fields.

    Returns records conforming to the unified paper schema.
    """
    import json

    items = fetch_feed(PHYSICS_FEED)
    day_items = filter_items(items, target)
    if not day_items:
        return []

    # Scrape abstracts; drop papers where abstract is unavailable (paywalled).
    papers_with_abstracts = []
    for item in day_items:
        link = item.findtext("link", "").rstrip("/")
        slug = link.split("/")[-1]
        title = item.findtext("title", "").strip()
        abstract = scrape_abstract(link)
        if not abstract:
            continue
        papers_with_abstracts.append(
            {
                "title": title,
                "link": link,
                "slug": slug,
                "doi": slug_to_doi(slug),
                "journal": slug_to_journal(slug),
                "publishedAt": target.isoformat(),
                "abstract": abstract,
            }
        )
        time.sleep(0.5)  # polite crawl rate

    if not papers_with_abstracts:
        return []

    extracted = extract_fields(papers_with_abstracts, client)
    if not isinstance(extracted, list) or len(extracted) != len(papers_with_abstracts):
        raise RuntimeError(
            f"Extraction mismatch: expected {len(papers_with_abstracts)} records, got "
            f"{len(extracted) if isinstance(extracted, list) else type(extracted).__name__}"
        )

    records = []
    for paper, fields in zip(papers_with_abstracts, extracted):
        source = "nature"
        uid = f"{source}:{paper['doi']}"
        records.append(
            {
                "uid": uid,
                "source": source,
                "id": paper["doi"],
                "title": paper["title"],
                "journal": paper["journal"],
                "publishedAt": paper["publishedAt"],
                "category": fields.get("category", "Other"),
                "task": fields.get("task", ""),
                "model": fields.get("model", ""),
                "inputs": fields.get("inputs", ""),
                "outputs": fields.get("outputs", ""),
                "key_results": fields.get("key_results", ""),
                "comments": fields.get("comments", ""),
                "hypotheses": fields.get("hypotheses") or [],
                "results": fields.get("results") or [],
            }
        )
    return records
