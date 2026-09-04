"""Cross-reference Seedfinder strains against the WEED database to fill genetics/breeder gaps.

Strategy:
  1. Match DB strains to Seedfinder strains by normalized name
  2. Fill: strain_type, breeder, genetics (from parent info)
  3. Create StrainLink entries for parent relationships
  4. Optionally fetch lineage pages for deeper enrichment

Usage:
  python scripts/seedfinder_enrich.py               — run enrichment (match only, no extra HTTP)
  python scripts/seedfinder_enrich.py --fetch-links  — also fetch lineage pages for parents
"""

import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

SEEDFINDER_FILE = DATA_DIR / "seedfinder_strains.json"
DB_PATH = DATA_DIR / "weed.db"


def normalize(name: str) -> str:
    """Aggressive name normalization for matching."""
    n = name.lower().strip()
    n = n.replace('-', ' ').replace('_', ' ')
    n = re.sub(r'[^a-z0-9\s]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def normalize_aggressive(name: str) -> list[str]:
    """Try multiple normalizations for fuzzy matching."""
    base = normalize(name)
    candidates = [base]

    # Strip leading numeric prefix like "98-White-Widow" → "White Widow"
    stripped = re.sub(r'^[0-9\$#@]+\s*', '', base).strip()
    if stripped != base:
        candidates.append(stripped)

    # Strip leading text like "Original " or "OG "
    for prefix in ['original ', 'og ', 'the ', 'auto ']:
        if base.startswith(prefix):
            candidates.append(base[len(prefix):])

    return candidates


def load_seedfinder_index() -> dict[str, list[dict]]:
    """Build normalized -> strains index from Seedfinder JSON."""
    with open(SEEDFINDER_FILE) as f:
        strains = json.load(f)

    index = {}
    for s in strains:
        key = normalize(s['name'])
        index.setdefault(key, []).append(s)
        # Also index by aggressive normalizations
        for alt in normalize_aggressive(s['name']):
            if alt != key:
                index.setdefault(alt, []).append(s)

    return index


def get_db_strains():
    """Get all strains from the local SQLite DB."""
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, source FROM strains")
    rows = cursor.fetchall()
    conn.close()
    return rows


def match_strains(db_strains: list, sf_index: dict) -> tuple[list, list, list]:
    """Match DB strains to Seedfinder strains.

    Returns: (matched_pairs, unmatched_db, match_stats)
    """
    matched = []
    unmatched = []
    stats = {"exact": 0, "aggressive": 0}

    for db_row in db_strains:
        db_id = db_row["id"]
        db_name = db_row["name"]
        db_source = db_row["source"]

        found = None

        # Try exact normalized match first
        candidates = normalize_aggressive(db_name)
        for n in candidates:
            if n in sf_index:
                found = sf_index[n][0]  # Take first match
                stats["exact" if n == candidates[0] else "aggressive"] += 1
                break

        if found:
            matched.append((db_id, db_name, db_source, found))
        else:
            unmatched.append((db_id, db_name, db_source))

    return matched, unmatched, stats


async def fetch_lineage(slug: str, breeder_slug: str) -> list[dict]:
    """Fetch strain info page and extract immediate parents."""
    url = f"https://seedfinder.eu/en/strain-info/{slug}/{breeder_slug}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for attempt in range(3):
            try:
                resp = await client.get(url, headers=HEADERS, timeout=30)
                if resp.status_code == 200:
                    return extract_parents_from_lineage(resp.text)
                elif resp.status_code == 429:
                    await asyncio.sleep(5 * (attempt + 1))
                else:
                    if attempt < 2:
                        await asyncio.sleep(2)
                    else:
                        return []
            except Exception:
                if attempt < 2:
                    await asyncio.sleep(3)
                else:
                    return []
    return []


def extract_parents_from_lineage(html: str) -> list[dict]:
    """Extract immediate parents from a strain info page's #lineage section."""
    idx = html.find('id="lineage"')
    if idx < 0:
        idx = html.find('Lineage / Genealogy')
    if idx < 0:
        return []

    # Find the first »»» section and grab the immediate parent links
    m = re.search(r'»»»\s*', html[idx:idx+5000])
    if not m:
        return []

    after = html[idx:idx+5000][m.end():m.end()+500]

    # Find parent links: <a class='link' href='.../strain-info/{slug}/{breeder}'>Name</a>
    parents = []
    for slug, breeder_slug, name in re.findall(
        r"<a[^>]*class=['\"]link['\"][^>]*href=['\"]https?://seedfinder\.eu/en/strain-info/([^\"'/]+)/([^\"'/]+)['\"][^>]*>([^<]+)</a>",
        after
    )[:2]:  # Max 2 parents
        parents.append({
            "name": re.sub(r'&#?\w+;', '', name).strip(),
            "slug": slug,
            "breeder_slug": breeder_slug,
        })

    return parents


async def enrich_with_lineage(matched: list, sf_index: dict) -> list[dict]:
    """Enrich matched strains with parent lineage by fetching strain info pages."""
    enriched = []
    total = len(matched)

    print(f"\nEnriching {total} strains with lineage data (fetching strain info pages)...")
    print(f"  Estimated time: ~{total * 0.5 / 60:.0f} minutes at 0.5s between requests")

    for i, (db_id, db_name, db_source, sf_strain) in enumerate(matched):
        if i % 50 == 0 and i > 0:
            print(f"  {i}/{total} ({i/total*100:.0f}%)")

        genetics_str = ""
        parents = await fetch_lineage(sf_strain["slug"], sf_strain["breeder_slug"])
        if parents:
            genetics_str = " x ".join(p["name"] for p in parents)

        enriched.append({
            "db_id": db_id,
            "db_name": db_name,
            "sf_name": sf_strain["name"],
            "breeder": sf_strain["breeder"],
            "strain_type": sf_strain["strain_type"],
            "genetics": genetics_str,
            "parents": parents,
            "sf_slug": sf_strain["slug"],
            "sf_breeder_slug": sf_strain["breeder_slug"],
        })

        await asyncio.sleep(0.5)

    return enriched


def build_sql_updates(enriched: list[dict], create_strainlinks: bool = True) -> tuple[list[str], int]:
    """Build SQL update statements.

    Returns (updates_sql, strainlink_sql_count)
    """
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    updates = 0
    link_count = 0

    for item in enriched:
        # Map Seedfinder strain_type to DB format (indica/sativa/hybrid mainly)
        sf_type = item["strain_type"].lower()
        # Map type: "mostly indica" -> "indica", "indica / sativa" -> "hybrid", etc.
        if sf_type in ("indica",):
            db_type = "indica"
        elif sf_type in ("sativa",):
            db_type = "sativa"
        elif sf_type in ("mostly indica", "mostly sativa"):
            db_type = "indica" if "indica" in sf_type else "sativa"
        elif sf_type in ("ruderalis / indica", "ruderalis / sativa", "ruderalis / indica / sativa", "ruderalis"):
            db_type = "hybrid"
        elif "indica" in sf_type and "sativa" in sf_type:
            db_type = "hybrid"
        elif "indica" in sf_type:
            db_type = "indica"
        elif "sativa" in sf_type:
            db_type = "sativa"
        else:
            db_type = "hybrid"

        cursor.execute("""
            UPDATE strains 
            SET breeder = ?, genetics = ?, strain_type = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            item["breeder"],
            item["genetics"],
            db_type,
            item["db_id"],
        ))
        updates += cursor.rowcount

        # Create StrainLink entries if parents exist
        if create_strainlinks and item["parents"]:
            for parent in item["parents"]:
                # Check if parent strain exists in our DB by name
                cursor.execute(
                    "SELECT id FROM strains WHERE name = ? COLLATE NOCASE",
                    (parent["name"],)
                )
                parent_row = cursor.fetchone()
                if parent_row:
                    parent_id = parent_row[0]
                    # Insert link (skip on conflict)
                    try:
                        cursor.execute("""
                            INSERT OR IGNORE INTO strain_links 
                            (id, parent_id, child_id, rel_type, confidence, source, notes)
                            VALUES (?, ?, ?, 'parent', 0.8, 'seedfinder', ?)
                        """, (
                            f"{parent_id[:6]}_{item['db_id'][:6]}",
                            parent_id,
                            item["db_id"],
                            json.dumps({"seedfinder_slug": parent["slug"]})
                        ))
                        link_count += 1
                    except Exception as e:
                        pass

    conn.commit()
    conn.close()
    return updates, link_count


async def main():
    fetch_links = "--fetch-links" in sys.argv

    print("=" * 60)
    print("Seedfinder Cross-Reference Enrichment")
    print("=" * 60)

    # 1. Load Seedfinder index
    print("\n1. Loading Seedfinder strain index (41,737 strains)...")
    sf_index = load_seedfinder_index()
    print(f"   Index has {len(sf_index)} unique normalized names")

    # 2. Get DB strains
    print("\n2. Loading DB strains (4,800)...")
    db_strains = get_db_strains()
    print(f"   Found {len(db_strains)} strains in DB")

    # 3. Match
    print("\n3. Matching strains...")
    matched, unmatched, stats = match_strains(db_strains, sf_index)
    print(f"   Matched: {len(matched)} (exact={stats['exact']}, aggressive={stats['aggressive']})")
    print(f"   Unmatched: {len(unmatched)}")

    # 4. Show unmatched
    if unmatched:
        print(f"\n   Unmatched strains (sample):")
        for _, name, source in unmatched[:15]:
            print(f"     {name:35s} (source: {source})")

    # 5. Enrich
    if fetch_links:
        enriched = await enrich_with_lineage(matched, sf_index)
    else:
        # Build from already-known data (no HTTP)
        enriched = []
        for db_id, db_name, db_source, sf_strain in matched:
            enriched.append({
                "db_id": db_id,
                "db_name": db_name,
                "sf_name": sf_strain["name"],
                "breeder": sf_strain["breeder"],
                "strain_type": sf_strain["strain_type"],
                "genetics": "",  # No parent info without fetching
                "parents": [],
                "sf_slug": sf_strain["slug"],
                "sf_breeder_slug": sf_strain["breeder_slug"],
            })

    # 6. Write updates
    print(f"\n4. Applying updates ({'with' if fetch_links else 'without'} lineage)...")
    updates, link_count = build_sql_updates(enriched, create_strainlinks=fetch_links)
    print(f"   Updated {updates} strains in DB")
    if fetch_links:
        print(f"   Created {link_count} StrainLink entries")

    # 7. Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"  DB strains total:         {len(db_strains)}")
    print(f"  Matched to Seedfinder:   {len(matched)} ({len(matched)/len(db_strains)*100:.1f}%)")
    print(f"  Updated with breeder:    {updates}")
    print(f"  Unmatched (no ref):      {len(unmatched)} ({len(unmatched)/len(db_strains)*100:.1f}%)")
    if fetch_links:
        print(f"  StrainLinks created:     {link_count}")
    print()
    print(f"  Unmatched strains may be:")
    print(f"    - Rare/kaggle-only legacy strains")
    print(f"    - Strains named differently in Seedfinder")
    print(f"    - Misspelled or alternate-format names")
    print()
    print(f"  To also fetch lineage: python scripts/seedfinder_enrich.py --fetch-links")
    print(f"  (This fetches ~{len(matched)} strain info pages at 0.5s intervals ≈ {len(matched)*0.5/60:.0f} min)")


if __name__ == "__main__":
    asyncio.run(main())