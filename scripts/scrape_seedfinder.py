"""Seedfinder.eu scraper — cannabis strain database with lineage information.

Seedfinder.eu has 40,000+ cannabis strains with detailed genetic lineage.
Site is alphabetically paginated (A-Z plus 0-9) at /en/database/strains/alphabetical/{letter}.

Usage:
  python scripts/scrape_seedfinder.py strains [limit]   — scrape listing pages
  python scripts/scrape_seedfinder.py lineage <slug> <breeder> — get one strain's lineage
"""

import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SEEDFINDER_BASE = "https://seedfinder.eu"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# All letter pages to scrape — 26 letters + digits
LETTER_PAGES = list("abcdefghijklmnopqrstuvwxyz") + ["1234567890"]


@dataclass
class SeedfinderStrain:
    name: str
    slug: str
    breeder: str
    breeder_slug: str
    strain_type: str  # indica, sativa, hybrid, mostly indica, mostly sativa, ruderalis, etc.
    flowering_days: Optional[int] = None
    seed_type: str = ""  # feminized, regular, clone only
    parents: list = field(default_factory=list)  # [{"name": "...", "slug": "...", "breeder": "..."}]
    descendants: list = field(default_factory=list)
    source_url: str = ""


@dataclass
class LineageEntry:
    name: str
    slug: str
    breeder: str
    relation: str = ""  # parent, grandparent, descendant, etc.


async def fetch_page(url: str, client: httpx.AsyncClient) -> str:
    """Fetch a page with retry and rate limiting."""
    for attempt in range(3):
        try:
            resp = await client.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"  [RATE-LIMITED] {url}, waiting {wait}s...")
                await asyncio.sleep(wait)
            elif resp.status_code == 404:
                print(f"  [404] {url}")
                return ""
            else:
                print(f"  [HTTP {resp.status_code}] {url}")
                if attempt < 2:
                    await asyncio.sleep(2)
        except Exception as e:
            print(f"  [ERROR] {url}: {e}")
            if attempt < 2:
                await asyncio.sleep(3)
    return ""


def parse_letter_page(html: str) -> list[dict]:
    """Parse strain listing table from a letter page.

    Each data row looks like:
      <tr>
        <td class="p-4 ..."><a class="link" href=".../strain-info/{slug}/{breeder}">Name</a></td>
        <td class="hidden md:table-cell">Breeder Name</td>
        <td class="leading-7 ...">63</td>
        <td class="leading-7 ...">indica / sativa</td>
        <td class="hidden md:table-cell">feminized</td>
      </tr>
    """
    strains = []
    # Match rows that contain a strain-info link
    row_pattern = re.compile(
        r'<tr[^>]*>(.*?)</tr>', re.DOTALL
    )
    for row_match in row_pattern.finditer(html):
        row_html = row_match.group(1)
        if '/en/strain-info/' not in row_html:
            continue

        # Extract strain name and link
        link_match = re.search(
            r'href="(?:https?://seedfinder\.eu)?/en/strain-info/([^"/]+)/([^"\'/]+)"[^>]*>([^<]+)</a>',
            row_html
        )
        if not link_match:
            continue

        slug = link_match.group(1)
        breeder_slug = link_match.group(2)
        name = html_decode(link_match.group(3).strip())

        # Extract breeder
        breeder_match = re.search(
            r'<td class="hidden md:table-cell">([^<]+)</td>', row_html
        )
        breeder = html_decode(breeder_match.group(1).strip()) if breeder_match else ""

        # Extract flowering time
        flowering_match = re.search(
            r'<td class="leading-7[^"]*md:leading-normal">\s*(\d+)\s*</td>', row_html
        )
        flowering_days = int(flowering_match.group(1)) if flowering_match else None

        # Extract strain heritage/type — 4th td
        tds = re.findall(r'<td[^>]*class="(?:hidden md:table-cell|leading-7[^"]*)"[^>]*>(.*?)</td>', row_html, re.DOTALL)
        strain_type = ""
        seed_type = ""
        if len(tds) >= 4:
            # 4th td is type, but we need to handle hidden md:table-cell vs leading-7
            # The columns are: 1.strain-name, 2.breeder(hidden), 3.flowering, 4.type, 5.seed-type(hidden)
            pass

        # Better approach: extract all 4 data tds in order
        all_tds = re.findall(r'<td[^>]*class="([^"]*)"[^>]*>(.*?)</td>', row_html, re.DOTALL)
        data_tds = [(cls, content.strip()) for cls, content in all_tds]

        # Parse by column index - each row has 5 TD columns
        col_idx = 0
        for cls, content in data_tds:
            col_idx += 1
            if col_idx == 3:  # Flowering time
                flowering_match = re.search(r'(\d+)', content)
                flowering_days = int(flowering_match.group(1)) if flowering_match else None
            elif col_idx == 4:  # Strain type
                strain_type = html_decode(re.sub(r'<[^>]+>', '', content).strip())
            elif col_idx == 5:  # Seed type (feminized/regular/clone only)
                seed_type = html_decode(re.sub(r'<[^>]+>', '', content).strip())

        source_url = f"{SEEDFINDER_BASE}/en/strain-info/{slug}/{breeder_slug}"

        strains.append({
            "name": name,
            "slug": slug,
            "breeder": breeder,
            "breeder_slug": breeder_slug,
            "strain_type": strain_type,
            "flowering_days": flowering_days,
            "seed_type": seed_type,
            "source_url": source_url,
        })

    return strains


def html_decode(text: str) -> str:
    """Decode HTML entities in text."""
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#039;", "'")
    text = text.replace("&#39;", "'")
    text = text.replace("&#x27;", "'")
    text = text.replace("&nbsp;", " ")
    # Generic numeric entities
    text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)
    return text


def extract_parents_from_lineage_section(html: str) -> list[dict]:
    """Extract immediate parents from the lineage section of a strain info page.

    The lineage section has structure:
      »»» Parent1 x Parent2

    Returns list of parent dicts with name, slug, breeder_slug.
    """
    # Find the lineage section
    idx = html.find('id="lineage"')
    if idx < 0:
        idx = html.find('Lineage / Genealogy')
    if idx < 0:
        idx = html.find('Ancestors / Parents')
    if idx < 0:
        return []

    section = html[idx:idx + 5000]

    # Look for the »»» pattern followed by parent links separated by "x"
    # Pattern 1: »»» <a class='link' href='...'>Parent1</a> x <a class='link' href='...'>Parent2</a>
    parents = []
    # Find all "»»»" occurrences and check what follows
    for match in re.finditer(r'»»»\s*(.*?)(?:</[^>]+>\s*)*$', section, re.DOTALL):
        pass

    # Simpler: find all links that appear after »»» before the next "x" or parent structure
    # Find »»» markers and extract the following parent links
    for m in re.finditer(r'»»»\s*', section):
        after = section[m.end():m.end()+500]
        # Extract links in this segment
        parent_links = re.findall(
            r'<a[^>]*class=[\'"]link[\'\"][^>]*href=[\'"]https?://seedfinder\.eu/en/strain-info/([^"\'/]+)/([^"\'/]+)[\'"][^>]*>([^<]+)</a>',
            after
        )
        # But many of these are deeper lineage. The first set after »»» are the immediate parents
        # Look for the immediate pattern: Parent1 x Parent2
        # In the page source, after »»» we have <span>Parent1-link</span> x <span>Parent2-link</span>
        immediate_pattern = re.compile(
            r'<a[^>]*class=[\'"]link[\'\"][^>]*href=[\'"]https?://seedfinder\.eu/en/strain-info/([^"\'/]+)/([^"\'/]+)[\'"][^>]*>([^<]+)</a>'
        )
        # Find first two links after »»»
        im_links = immediate_pattern.findall(after)
        for slug, breeder_slug, name in im_links[:2]:
            parent = {
                "name": html_decode(name.strip()),
                "slug": slug,
                "breeder_slug": breeder_slug,
            }
            if parent not in parents:
                parents.append(parent)
        break  # Only first »»» block has immediate parents

    return parents


def extract_descendants_from_lineage(html: str) -> list[dict]:
    """Extract descendants (hybrids) from the lineage page.

    Below the lineage tree there's a table of direct crosses/descendants like:
      <tr><td>Descendant Name (Breeder)</td><td>Parent1 x Parent2</td></tr>
    """
    descendants = []

    # Find the section after lineage tree - look for "genealogy" section with table
    idx = html.find('class="w-full table-auto alternating-table"')
    if idx < 0:
        idx = html.find('direct crosses')

    if idx >= 0:
        section = html[idx:idx + 5000]
        # Find the descendant links
        desc_links = re.findall(
            r'<a[^>]*href=[\'"]https?://seedfinder\.eu/en/strain-info/([^"\'/]+)/([^"\'/]+)[\'"][^>]*>([^<]+)</a>',
            section
        )
        seen = set()
        for slug, breeder_slug, name in desc_links:
            key = (slug, breeder_slug)
            if key not in seen:
                seen.add(key)
                descendants.append({
                    "name": html_decode(name.strip()),
                    "slug": slug,
                    "breeder_slug": breeder_slug,
                })

    return descendants


async def scrape_strain_list(max_strains: Optional[int] = None) -> list[dict]:
    """Scrape all strain listing pages (A-Z + 0-9)."""
    all_strains = []

    async with httpx.AsyncClient(timeout=30) as client:
        for letter in LETTER_PAGES:
            url = f"{SEEDFINDER_BASE}/en/database/strains/alphabetical/{letter}"
            print(f"Scraping letter '{letter}'...")
            html = await fetch_page(url, client)
            if not html:
                print(f"  Skipping '{letter}' — no content")
                continue

            strains = parse_letter_page(html)
            print(f"  Found {len(strains)} strains for letter '{letter}'")
            all_strains.extend(strains)

            # Rate limiting
            await asyncio.sleep(0.5)

            if max_strains and len(all_strains) >= max_strains:
                all_strains = all_strains[:max_strains]
                print(f"  Reached limit of {max_strains}, stopping")
                break

    return all_strains


async def scrape_strain_lineage(slug: str, breeder_slug: str) -> dict:
    """Scrape lineage info for a single strain.

    Returns dict with parents and descendants.
    """
    # Fetch the genealogy page
    url = f"{SEEDFINDER_BASE}/en/strain-info/{slug}/{breeder_slug}/genealogy"
    async with httpx.AsyncClient(timeout=30) as client:
        html = await fetch_page(url, client)

    if not html:
        # Try the strain info page instead
        url = f"{SEEDFINDER_BASE}/en/strain-info/{slug}/{breeder_slug}"
        async with httpx.AsyncClient(timeout=30) as client:
            html = await fetch_page(url, client)

    if not html:
        return {"slug": slug, "breeder_slug": breeder_slug, "parents": [], "descendants": []}

    parents = extract_parents_from_lineage_section(html)
    descendants = extract_descendants_from_lineage(html)

    return {
        "slug": slug,
        "breeder_slug": breeder_slug,
        "parents": parents,
        "descendants": descendants,
    }


async def scrape_strains_with_lineage(max_strains: int = 100) -> list[dict]:
    """Scrape strain listing and enrich with lineage data."""
    # First get the full listing
    strains = await scrape_strain_list(max_strains=max_strains)

    print(f"\nEnriching {len(strains)} strains with lineage data...")

    async with httpx.AsyncClient(timeout=30) as client:
        for i, strain in enumerate(strains):
            if i % 10 == 0:
                print(f"  Lineage {i}/{len(strains)}")

            slug = strain["slug"]
            breeder_slug = strain["breeder_slug"]
            url = f"{SEEDFINDER_BASE}/en/strain-info/{slug}/{breeder_slug}"

            html = await fetch_page(url, client)
            if html:
                parents = extract_parents_from_lineage_section(html)
                descendants = extract_descendants_from_lineage(html)
                strain["parents"] = parents
                strain["descendants"] = descendants

            await asyncio.sleep(0.5)

    return strains


async def main():
    """CLI entry point."""
    command = sys.argv[1] if len(sys.argv) > 1 else "help"

    if command == "strains":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        include_lineage = "--lineage" in sys.argv or "--details" in sys.argv

        if count:
            max_strains = count
        else:
            max_strains = None

        if include_lineage and max_strains and max_strains > 500:
            print("Warning: lineage enrichment is slow for large datasets. Consider using a lower limit.")
            print("Recommended: python scripts/scrape_seedfinder.py strains 100 --lineage")

        if include_lineage:
            strains = await scrape_strains_with_lineage(max_strains=max_strains or 500)
        else:
            strains = await scrape_strain_list(max_strains=max_strains)

        output = DATA_DIR / "seedfinder_strains.json"
        with open(output, "w") as f:
            json.dump(strains, f, indent=2, default=str)
        print(f"\nSaved {len(strains)} strains to {output}")

    elif command == "lineage":
        slug = sys.argv[2] if len(sys.argv) > 2 else ""
        breeder_slug = sys.argv[3] if len(sys.argv) > 3 else ""

        if not slug:
            print("Usage: python scripts/scrape_seedfinder.py lineage <slug> [breeder]")
            print("  Strain slugs can be found in the listing output or on seedfinder.eu URLs.")
            print("  e.g. python scripts/scrape_seedfinder.py lineage a-cheesy-mist kalis-fruitful-cannabis-seeds")
            return

        result = await scrape_strain_lineage(slug, breeder_slug)
        print(json.dumps(result, indent=2, default=str))

    elif command == "detail":
        # Scrape single strain info page
        slug = sys.argv[2] if len(sys.argv) > 2 else ""
        breeder_slug = sys.argv[3] if len(sys.argv) > 3 else ""
        if not slug or not breeder_slug:
            print("Usage: python scripts/scrape_seedfinder.py detail <slug> <breeder>")
            return

        url = f"{SEEDFINDER_BASE}/en/strain-info/{slug}/{breeder_slug}"
        async with httpx.AsyncClient(timeout=30) as client:
            html = await fetch_page(url, client)

        result = {
            "slug": slug,
            "breeder_slug": breeder_slug,
            "url": url,
            "parents": extract_parents_from_lineage_section(html) if html else [],
            "descendants": extract_descendants_from_lineage(html) if html else [],
        }
        print(json.dumps(result, indent=2, default=str))

    else:
        print("""Seedfinder.eu Cannabis Strain Scraper
========================================
Usage:
  python scripts/scrape_seedfinder.py strains [limit] [--lineage]
  python scripts/scrape_seedfinder.py lineage <slug> <breeder>
  python scripts/scrape_seedfinder.py detail <slug> <breeder>

Commands:
  strains    Scrape all strain listing pages (A-Z + 0-9).
             Optional limit: max number of strains.
             Optional --lineage: also fetch each strain's parents.
  lineage    Get one strain's lineage (parents + descendants).
  detail     Get detailed info about a single strain.

Examples:
  python scripts/scrape_seedfinder.py strains
  python scripts/scrape_seedfinder.py strains 200 --lineage
  python scripts/scrape_seedfinder.py lineage a-cheesy-mist kalis-fruitful-cannabis-seeds
  python scripts/scrape_seedfinder.py detail a-cheesy-mist kalis-fruitful-cannabis-seeds
""")


if __name__ == "__main__":
    asyncio.run(main())