"""Fetch Nature RSS feed papers, scrape abstracts, extract fields via Claude.

Returns a list of paper records conforming to the unified schema.
Intended to be called by fetch_papers.py as a library module.
"""

import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from email.utils import parsedate_to_datetime
from threading import Lock
from xml.etree import ElementTree as ET

import anthropic
from tqdm import tqdm

# All Nature RSS feeds with their per-feed category lists.
FEEDS: dict[str, dict] = {
    "physics": {
        "url": "https://www.nature.com/subjects/physics.rss",
        "categories": [
            "Condensed Matter",
            "Quantum",
            "High Energy/Particle",
            "Astrophysics/Cosmology",
            "Optics/Photonics",
            "Mathematical Physics",
            "Applied Physics",
            "Other",
        ],
    },
    "biophysics": {
        "url": "https://www.nature.com/subjects/biophysics.rss",
        "categories": [
            "Structural Biology",
            "Membrane Biophysics",
            "Single Molecule",
            "Mechanobiology",
            "Protein Dynamics",
            "Computational Biophysics",
            "Neural Biophysics",
            "Other",
        ],
    },
    "biotechnology": {
        "url": "https://www.nature.com/subjects/biotechnology/nature.rss",
        "categories": [
            "Synthetic Biology",
            "Gene Editing",
            "Protein Engineering",
            "Cell/Gene Therapy",
            "Diagnostics",
            "Bioprocessing",
            "Agricultural Biotech",
            "Other",
        ],
    },
    "cell-biology": {
        "url": "https://www.nature.com/subjects/cell-biology.rss",
        "categories": [
            "Cell Signaling",
            "Cell Division/Cycle",
            "Organelles",
            "Apoptosis/Cell Death",
            "Development",
            "Cytoskeleton",
            "Epigenetics",
            "Other",
        ],
    },
    "computational-biology": {
        "url": "https://www.nature.com/subjects/computational-biology-and-bioinformatics.rss",
        "categories": [
            "Genomics",
            "Proteomics",
            "Structural Prediction",
            "Network Biology",
            "Single Cell",
            "Evolutionary Biology",
            "Statistical Methods",
            "Other",
        ],
    },
    "mathematics-and-computing": {
        "url": "https://www.nature.com/subjects/mathematics-and-computing.rss",
        "categories": [
            "Combinatorics/Graph Theory",
            "Number Theory",
            "Analysis",
            "Topology/Geometry",
            "Algorithms",
            "ML Theory",
            "Statistics/Probability",
            "Other",
        ],
    },
    "neuroscience": {
        "url": "https://www.nature.com/subjects/neuroscience/nature.rss",
        "categories": [
            "Synaptic Plasticity",
            "Neural Circuits",
            "Cognition/Behavior",
            "Sensory Systems",
            "Neurodegeneration",
            "Development",
            "Computational Neuroscience",
            "Other",
        ],
    },
    "systems-biology": {
        "url": "https://www.nature.com/subjects/systems-biology.rss",
        "categories": [
            "Metabolic Networks",
            "Gene Regulation",
            "Signaling Pathways",
            "Evolutionary Dynamics",
            "Multi-scale Modeling",
            "Synthetic Circuits",
            "Other",
        ],
    },
}

# Maps Nature article slug prefix to journal name.
JOURNAL_CODES: dict[str, str] = {
    "41422": "Cell Research",
    "41467": "Nature Communications",
    "41477": "Nature Plants",
    "41524": "npj Computational Materials",
    "41551": "Nature Biomedical Engineering",
    "41560": "Nature Energy",
    "41562": "Nature Human Behaviour",
    "41563": "Nature Materials",
    "41564": "Nature Microbiology",
    "41565": "Nature Nanotechnology",
    "41566": "Nature Photonics",
    "41567": "Nature Physics",
    "41568": "Nature Reviews Immunology",
    "41570": "Nature Reviews Chemistry",
    "41571": "Nature Reviews Clinical Oncology",
    "41572": "Nature Reviews Disease Primers",
    "41573": "Nature Reviews Drug Discovery",
    "41574": "Nature Reviews Endocrinology",
    "41575": "Nature Reviews Gastroenterology",
    "41576": "Nature Reviews Genetics",
    "41577": "Nature Reviews Immunology",
    "41578": "Nature Reviews Materials",
    "41579": "Nature Reviews Microbiology",
    "41580": "Nature Reviews Molecular Cell Biology",
    "41581": "Nature Reviews Nephrology",
    "41582": "Nature Reviews Neurology",
    "41583": "Nature Reviews Neuroscience",
    "41584": "Nature Reviews Rheumatology",
    "41585": "Nature Reviews Urology",
    "41586": "Nature",
    "41587": "Nature Biotechnology",
    "41588": "Nature Genetics",
    "41589": "Nature Chemical Biology",
    "41590": "Nature Immunology",
    "41591": "Nature Medicine",
    "41592": "Nature Methods",
    "41593": "Nature Neuroscience",
    "41594": "Nature Structural & Molecular Biology",
    "41595": "Nature Sustainability",
    "41596": "Nature Protocols",
    "41597": "Scientific Data",
    "41598": "Scientific Reports",
    "41928": "Nature Electronics",
    "42003": "Communications Biology",
    "42004": "Communications Chemistry",
    "42005": "Communications Physics",
    "42255": "Nature Portfolio",
    "44161": "Nature Cities",
    "44172": "Nature Reviews Physics",
    "44182": "Nature Reviews Materials",
    "44220": "Nature Chemical Engineering",
    "44221": "Nature Synthesis",
    "44222": "Nature Aging",
    "44260": "Nature Cardiovascular Research",
    "44263": "Nature Mental Health",
    "44264": "Nature Cancer",
    "44298": "Nature Water",
    "44319": "Nature Ecology & Evolution",
    "44328": "Nature Astronomy",
}

EXTRACTION_SYSTEM_TEMPLATE = """\
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

Be terse. Do not add fields or wrap in markdown."""


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
            return re.sub(r"<[^>]+>", "", m.group(1)).strip()
    except Exception:
        pass
    return None


def filter_items(items: list[ET.Element], target: date) -> list[ET.Element]:
    """Return items published on target date."""
    return [it for it in items if parse_item_date(it) == target]


def extract_fields(
    papers: list[dict], categories: list[str], client: anthropic.Anthropic
) -> list[dict]:
    """Call Claude once with all abstracts; return list of extracted field dicts."""
    system = EXTRACTION_SYSTEM_TEMPLATE.format(categories=" | ".join(categories))
    numbered = "\n\n".join(
        f"[{i + 1}] Title: {p['title']}\nAbstract: {p['abstract']}"
        for i, p in enumerate(papers)
    )
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": numbered}],
    )
    text_blocks = [b.text for b in message.content if b.type == "text"]
    if not text_blocks:
        raise RuntimeError("Claude returned no text content in extraction response")
    text = text_blocks[0].strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text)


def _scrape_feed(
    feed_name: str,
    feed_cfg: dict,
    items: list[ET.Element],
    target: date,
    pbar: tqdm,
) -> list[dict]:
    """Scrape abstracts for one feed's filtered items; update shared progress bar."""
    papers = []
    for item in items:
        link = item.findtext("link", "").rstrip("/")
        slug = link.split("/")[-1]
        raw_title = item.findtext("title", "")
        title = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", raw_title).strip()
        abstract = scrape_abstract(link)
        if abstract:
            papers.append(
                {
                    "feed": feed_name,
                    "categories": feed_cfg["categories"],
                    "title": title,
                    "link": link,
                    "slug": slug,
                    "doi": slug_to_doi(slug),
                    "journal": slug_to_journal(slug),
                    "publishedAt": target.isoformat(),
                    "abstract": abstract,
                }
            )
        pbar.update(1)
        time.sleep(0.3)
    return papers


def _extract_feed(
    feed_name: str,
    papers: list[dict],
    client: anthropic.Anthropic,
) -> list[dict]:
    """Extract fields and build records for one feed."""
    categories = FEEDS[feed_name]["categories"]
    extracted = extract_fields(papers, categories, client)
    if not isinstance(extracted, list) or len(extracted) != len(papers):
        raise RuntimeError(
            f"Extraction mismatch for feed {feed_name}: expected {len(papers)} records, got "
            f"{len(extracted) if isinstance(extracted, list) else type(extracted).__name__}"
        )
    records = []
    for paper, fields in zip(papers, extracted):
        uid = f"nature:{paper['doi']}"
        records.append(
            {
                "uid": uid,
                "source": feed_name,
                "id": paper["doi"],
                "title": paper["title"],
                "projectPage": paper["link"],
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


def fetch_nature_papers(target: date, client: anthropic.Anthropic | None = None) -> list[dict]:
    """Fetch all Nature RSS feed papers for target date, extract fields via Claude.

    Returns records conforming to the unified paper schema. Feeds are processed
    in parallel; scraping within each feed uses a polite 0.3s delay.
    """
    # Phase 1: Fetch all RSS feeds in parallel.
    items_by_feed: dict[str, list[ET.Element]] = {}
    with tqdm(total=len(FEEDS), desc="Fetching RSS feeds", unit="feed") as pbar:
        with ThreadPoolExecutor(max_workers=len(FEEDS)) as pool:
            futures = {
                pool.submit(fetch_feed, cfg["url"]): name
                for name, cfg in FEEDS.items()
            }
            for fut in as_completed(futures):
                feed_name = futures[fut]
                try:
                    items_by_feed[feed_name] = filter_items(fut.result(), target)
                except Exception as exc:
                    print(
                        f"WARNING: {feed_name} RSS fetch failed: {exc}",
                        file=sys.stderr,
                    )
                    items_by_feed[feed_name] = []
                pbar.update(1)

    total_articles = sum(len(v) for v in items_by_feed.values())
    if total_articles == 0:
        return []

    # Phase 2: Scrape abstracts in parallel across feeds.
    papers_by_feed: dict[str, list[dict]] = {}
    with tqdm(total=total_articles, desc="Scraping abstracts", unit="article") as pbar:
        with ThreadPoolExecutor(max_workers=len(FEEDS)) as pool:
            futures = {
                pool.submit(_scrape_feed, name, FEEDS[name], items, target, pbar): name
                for name, items in items_by_feed.items()
                if items
            }
            for fut in as_completed(futures):
                feed_name = futures[fut]
                papers = fut.result()
                if papers:
                    papers_by_feed[feed_name] = papers

    if not papers_by_feed:
        return []

    if client is None:
        client = anthropic.Anthropic()

    # Phase 3: Extract fields via Claude in parallel across feeds.
    records: list[dict] = []
    lock = Lock()
    with tqdm(total=len(papers_by_feed), desc="Extracting fields", unit="feed") as pbar:
        with ThreadPoolExecutor(max_workers=len(papers_by_feed)) as pool:
            futures = {
                pool.submit(_extract_feed, name, papers, client): name
                for name, papers in papers_by_feed.items()
            }
            for fut in as_completed(futures):
                feed_name = futures[fut]
                try:
                    feed_records = fut.result()
                    with lock:
                        records.extend(feed_records)
                except Exception as exc:
                    print(
                        f"WARNING: extraction failed for {feed_name}: {exc}",
                        file=sys.stderr,
                    )
                pbar.update(1)

    return records
