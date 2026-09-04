"""Full lineage enrichment for all 34K seedfinder-sourced strains.

Fetches each strain's info page, extracts immediate parents from the
#lineage section, fills genetics field, and creates StrainLink records.

Resumable — checkpoint file saves progress every 100 strains.
Concurrent (3 workers) to finish in ~2 hours instead of 7.

Usage:
  python scripts/seedfinder_full_lineage.py
  python scripts/seedfinder_full_lineage.py --checkpoint  (resume from last save)
"""

import asyncio
import json
import re
import sqlite3
import uuid
import sys
from pathlib import Path
from typing import Optional

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "weed.db"
CHECKPOINT = DATA_DIR / "lineage_checkpoint.json"
SEEDFINDER_BASE = "https://seedfinder.eu"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# 3 concurrent workers — polite to Seedfinder, ~2h total
CONCURRENCY = 3
DELAY_BETWEEN = 0.5  # seconds between requests per worker


def normalize(name: str) -> str:
    """Normalize strain name for matching."""
    n = name.lower().strip()
    n = n.replace('-', ' ').replace('_', ' ')
    n = re.sub(r'[^a-z0-9\s]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def extract_parents_from_html(html: str) -> list[dict]:
    """Extract immediate parents from a strain info page's #lineage section."""
    idx = html.find('id="lineage"')
    if idx < 0:
        idx = html.find('Lineage / Genealogy')
    if idx < 0:
        return []

    # Find the first »»» and grab the parent links that follow
    m = re.search(r'»»»\s*', html[idx:idx + 5000])
    if not m:
        return []

    after = html[idx:idx + 5000][m.end():m.end() + 500]

    # Match: <a class='link' href='.../strain-info/{slug}/{breeder}'>Name</a>
    parents = []
    for slug, breeder_slug, name in re.findall(
        r"<a[^>]*class=['\"]link['\"][^>]*href=['\"]https?://seedfinder\.eu/en/strain-info/([^\"'/]+)/([^\"'/]+)['\"][^>]*>([^<]+)</a>",
        after
    )[:2]:  # Max 2 immediate parents
        decoded = name.replace("&#039;", "'").replace("&#39;", "'").replace("&amp;", "&").replace("&quot;", '"')
        parents.append({
            "name": decoded.strip(),
            "slug": slug,
            "breeder_slug": breeder_slug,
        })

    return parents


def load_checkpoint() -> set:
    """Load processed strain IDs from checkpoint file."""
    if CHECKPOINT.exists():
        data = json.loads(CHECKPOINT.read_text())
        return set(data.get("processed", []))
    return set()


def save_checkpoint(processed: set):
    """Save processed strain IDs to checkpoint file."""
    CHECKPOINT.write_text(json.dumps({"processed": sorted(processed)}))


def build_db_map() -> dict[str, str]:
    """Build normalized_name -> db_id map from the DB."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name FROM strains")
    mapping = {}
    for db_id, name in c.fetchall():
        mapping[normalize(name)] = db_id
    conn.close()
    return mapping


def get_seedfinder_strains() -> list[dict]:
    """Get all seedfinder strains from the DB that need genetics."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, name FROM strains 
        WHERE source = 'seedfinder' AND (genetics IS NULL OR genetics = '')
    """)
    strains = [{"db_id": row[0], "db_name": row[1]} for row in c.fetchall()]
    conn.close()
    return strains


def build_sf_index() -> dict[str, list[dict]]:
    """Build normalized_name -> [seedfinder records] index from JSON."""
    with open(DATA_DIR / "seedfinder_strains.json") as f:
        sf_strains = json.load(f)
    index = {}
    for s in sf_strains:
        key = normalize(s["name"])
        index.setdefault(key, []).append(s)
    return index


async def fetch_lineage(
    slug: str, breeder_slug: str, sem: asyncio.Semaphore, client: httpx.AsyncClient
) -> list[dict]:
    """Fetch a strain info page and extract parents."""
    url = f"{SEEDFINDER_BASE}/en/strain-info/{slug}/{breeder_slug}"
    async with sem:
        for attempt in range(3):
            try:
                resp = await client.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
                if resp.status_code == 200:
                    return extract_parents_from_html(resp.text)
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


async def main():
    resume = "--checkpoint" in sys.argv or "--resume" in sys.argv

    print("=" * 60)
    print("Seedfinder Full Lineage Enrichment")
    print("=" * 60)

    # 1. Load state
    print("\n1. Loading state...")
    processed = load_checkpoint() if resume else set()
    db_map = build_db_map()
    sf_index = build_sf_index()
    all_strains = get_seedfinder_strains()
    total = len(all_strains)

    print(f"   DB strains needing genetics: {total:,}")
    if processed:
        print(f"   Already processed: {len(processed):,}")
        all_strains = [s for s in all_strains if s["db_id"] not in processed]
        print(f"   Remaining: {len(all_strains):,}")

    # 2. Build lookup — map each DB strain to its seedfinder slugs
    queue = []
    no_match = 0
    for s in all_strains:
        key = normalize(s["db_name"])
        if key in sf_index:
            sf = sf_index[key][0]
            queue.append({
                "db_id": s["db_id"],
                "db_name": s["db_name"],
                "slug": sf["slug"],
                "breeder_slug": sf["breeder_slug"],
            })
        else:
            no_match += 1

    print(f"   Matched to seedfinder slugs: {len(queue):,}")
    print(f"   No slug match (skipping): {no_match:,}")

    # 3. Fetch lineage in batches
    print(f"\n2. Fetching lineage for {len(queue):,} strains (3 concurrent workers)...")
    print(f"   Estimated time: ~{len(queue) * DELAY_BETWEEN / CONCURRENCY / 60:.0f} minutes")
    print(f"   Checkpoint: {CHECKPOINT}")
    if not resume:
        print("   Fresh run — delete checkpoint file to restart mid-way")

    sem = asyncio.Semaphore(CONCURRENCY)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    updated = 0
    links_created = 0
    batch_size = 100

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        batches = [queue[i:i + batch_size] for i in range(0, len(queue), batch_size)]
        for batch_idx, batch in enumerate(batches):
            tasks = [fetch_lineage(s["slug"], s["breeder_slug"], sem, client) for s in batch]
            results = await asyncio.gather(*tasks)

            for strain, parents in zip(batch, results):
                if parents:
                    genetics_str = " x ".join(p["name"] for p in parents)
                    c.execute(
                        "UPDATE strains SET genetics = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (genetics_str, strain["db_id"]),
                    )
                    updated += 1

                    # Create StrainLinks for parents that exist in DB
                    for parent in parents:
                        parent_key = normalize(parent["name"])
                        parent_db_id = db_map.get(parent_key)
                        if parent_db_id:
                            try:
                                link_id = f"{parent_db_id[:6]}_{strain['db_id'][:6]}"
                                c.execute("""
                                    INSERT OR IGNORE INTO strain_links
                                    (id, parent_id, child_id, rel_type, confidence, source, notes)
                                    VALUES (?, ?, ?, 'parent', 0.8, 'seedfinder', ?)
                                """, (link_id, parent_db_id, strain["db_id"],
                                      json.dumps({"seedfinder_slug": parent["slug"]})))
                                links_created += c.rowcount
                            except Exception:
                                pass

                processed.add(strain["db_id"])

            conn.commit()
            save_checkpoint(processed)

            pct = (batch_idx + 1) * batch_size / len(queue) * 100
            print(f"   {min((batch_idx + 1) * batch_size, len(queue)):>6}/{len(queue)} ({pct:.0f}%) "
                  f"— genetics: {updated:,}  links: {links_created:,}")

    conn.close()
    print(f"\n{'='*60}")
    print(f"COMPLETE")
    print(f"  Strains updated with genetics: {updated:,}")
    print(f"  StrainLinks created: {links_created:,}")
    print(f"  Checkpoint saved: {CHECKPOINT}")
    print(f"  To resume if interrupted: python scripts/seedfinder_full_lineage.py --resume")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())