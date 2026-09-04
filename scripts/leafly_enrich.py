"""Cross-reference Leafly terpene/effect data with the WEED database.

Leafly's listing pages (514+ pages, 18 strains each) contain structured terpene profiles,
effects with scores, cannabinoid data, and ratings. This script scrapes all pages,
indexes by name, and merges into the DB — focusing on terpenes (95% gap).

Usage:
  python scripts/leafly_enrich.py               — scrape + cross-reference
  python scripts/leafly_enrich.py --dry-run      — show what would be updated without writing
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
DB_PATH = DATA_DIR / "weed.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
LEAFLY_BASE = "https://www.leafly.com"

# Rate limit between pages
PAGE_DELAY = 0.3


def normalize(name: str) -> str:
    """Aggressive name normalization for matching."""
    n = name.lower().strip()
    n = n.replace('-', ' ').replace('_', ' ')
    n = re.sub(r'[^a-z0-9\s]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def parse_leafly_strain(s: dict) -> dict:
    """Parse a Leafly strain dict from __NEXT_DATA__ into our format."""
    name = s.get("name", "")
    slug = s.get("slug", "")

    # Type
    category = s.get("category") or s.get("phenotype", "hybrid") or "hybrid"
    category = category.lower().strip()
    if category not in ("indica", "sativa", "hybrid"):
        category = "hybrid"

    # THC (single avg value)
    thc_val = s.get("thc")
    thc_min = thc_max = None
    if thc_val is not None:
        try:
            v = float(thc_val)
            thc_min = max(0, v - 4)
            thc_max = v + 4
        except (ValueError, TypeError):
            pass

    # Cannabinoids (dict with percentile data)
    cann = s.get("cannabinoids", {})
    cbd_min = cbd_max = None
    if isinstance(cann, dict):
        cbd_data = cann.get("cbd", {})
        if isinstance(cbd_data, dict):
            try:
                cbd_min = float(cbd_data.get("percentile25", 0) or 0)
                cbd_max = float(cbd_data.get("percentile75", cbd_data.get("percentile50", 0)) or 0)
            except (ValueError, TypeError):
                pass

    # Effects (dict with score)
    effects_raw = s.get("effects", {})
    effects = []
    if isinstance(effects_raw, dict):
        total = sum(float(e.get("score", 0) or 0) for e in effects_raw.values() if isinstance(e, dict))
        for slug_name, e in effects_raw.items():
            if isinstance(e, dict):
                score = float(e.get("score", 0) or 0)
                pct = round(score / total * 100, 0) if total > 0 else 0
                if pct >= 5:  # Only significant effects
                    effects.append(e.get("name", slug_name).title())

    # Terpenes (dict with score)
    terps_raw = s.get("terps", {})
    terpenes = []
    if isinstance(terps_raw, dict):
        total = sum(float(t.get("score", 0) or 0) for t in terps_raw.values() if isinstance(t, dict))
        for slug_name, t in terps_raw.items():
            if isinstance(t, dict):
                score = float(t.get("score", 0) or 0)
                pct = round(score / total * 100, 1) if total > 0 else 0
                if pct > 0:
                    terpenes.append({
                        "name": t.get("name", slug_name).lower(),
                        "percentage": pct,
                    })
        # Sort by percentage descending
        terpenes.sort(key=lambda x: x["percentage"], reverse=True)

    # Flavors — not directly in Leafly listing data, leave empty for now
    flavors = []

    rating = float(s.get("averageRating", 0) or 0)
    review_count = int(s.get("reviewCount", 0) or 0)
    image_url = s.get("nugImage", "") or s.get("flowerImageSvg", "")

    return {
        "name": name,
        "slug": slug,
        "strain_type": category,
        "rating": rating,
        "review_count": review_count,
        "thc_min": thc_min,
        "thc_max": thc_max,
        "cbd_min": cbd_min,
        "cbd_max": cbd_max,
        "effects": effects,
        "flavors": flavors,
        "terpenes": terpenes,
        "image_url": image_url,
        "top_effect": s.get("topEffect", ""),
        "top_terpene": s.get("strainTopTerp", ""),
    }


async def fetch_leafly_page(page: int, client: httpx.AsyncClient) -> list[dict]:
    """Fetch one Leafly listing page and return parsed strains."""
    url = f"{LEAFLY_BASE}/strains?page={page}"
    for attempt in range(3):
        try:
            resp = await client.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                match = re.search(
                    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                    resp.text, re.DOTALL
                )
                if match:
                    data = json.loads(match.group(1))
                    data_section = data.get("props", {}).get("pageProps", {}).get("data", {})
                    strains_raw = data_section.get("strains", [])
                    return [parse_leafly_strain(s) for s in strains_raw]
                return []
            elif resp.status_code == 429:
                await asyncio.sleep(5 * (attempt + 1))
            elif resp.status_code == 404:
                return None  # Signal end of pages
            else:
                if attempt < 2:
                    await asyncio.sleep(2)
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(3)
    return []


async def scrape_all_leafly(max_pages: int = 600) -> dict[str, dict]:
    """Scrape all Leafly listing pages and return name-indexed map.

    Returns {normalized_name: leafly_data}
    """
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        leafly_map = {}
        total_strains = 0

        for page in range(1, max_pages + 1):
            if page % 50 == 0 or page == 1:
                print(f"  Page {page}...")

            strains = await fetch_leafly_page(page, client)

            if strains is None:
                print(f"  Reached end at page {page - 1}")
                break

            for s in strains:
                key = normalize(s["name"])
                if key not in leafly_map:  # First occurrence wins
                    leafly_map[key] = s
                total_strains += 1

            await asyncio.sleep(PAGE_DELAY)

        return leafly_map, total_strains


def match_to_db(leafly_map: dict) -> tuple[list, list, dict]:
    """Cross-reference Leafly data against DB strains.

    Returns (updates, stats)
    """
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id, name FROM strains")
    db_strains = cursor.fetchall()

    updates = []
    matched_count = 0
    gap_fills = {"terpenes": 0, "effects": 0, "flavors": 0, "thc": 0, "cbd": 0}

    for db_id, db_name in db_strains:
        key = normalize(db_name)
        if key in leafly_map:
            lf = leafly_map[key]
            matched_count += 1

            # Check what we can fill
            cursor.execute("""
                SELECT terpenes, effects, flavors, thc_min, cbd_min
                FROM strains WHERE id = ?
            """, (db_id,))
            row = cursor.fetchone()

            has_terps = row[0] and row[0] not in ("[]", "")
            has_effects = row[1] and row[1] not in ("[]", "")
            has_flavors = row[2] and row[2] not in ("[]", "")
            has_thc = row[3] is not None
            has_cbd = row[4] is not None

            # What we can fill
            fill_terps = lf["terpenes"] and not has_terps
            fill_effects = lf["effects"] and not has_effects
            fill_thc = lf["thc_min"] is not None and not has_thc
            fill_cbd = lf["cbd_min"] is not None and not has_cbd

            if fill_terps or fill_effects or fill_thc or fill_cbd:
                updates.append({
                    "db_id": db_id,
                    "db_name": db_name,
                    "terpenes": json.dumps(lf["terpenes"]) if fill_terps else None,
                    "effects": json.dumps(lf["effects"]) if fill_effects else None,
                    "thc_min": lf["thc_min"] if fill_thc else None,
                    "thc_max": lf["thc_max"] if fill_thc else None,
                    "cbd_min": lf["cbd_min"] if fill_cbd else None,
                    "cbd_max": lf["cbd_max"] if fill_cbd else None,
                    "rating": lf["rating"],
                    "review_count": lf["review_count"],
                    "image_url": lf["image_url"],
                })
                if fill_terps: gap_fills["terpenes"] += 1
                if fill_effects: gap_fills["effects"] += 1
                if fill_thc: gap_fills["thc"] += 1
                if fill_cbd: gap_fills["cbd"] += 1

    conn.close()
    return updates, matched_count, gap_fills


def apply_updates(updates: list, dry_run: bool = False) -> int:
    """Apply updates to the database."""
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    applied = 0
    for u in updates:
        set_parts = []
        params = {}

        if u["terpenes"] is not None:
            set_parts.append("terpenes = :terpenes")
            params["terpenes"] = u["terpenes"]
        if u["effects"] is not None:
            set_parts.append("effects = :effects")
            params["effects"] = u["effects"]
        if u["thc_min"] is not None:
            set_parts.append("thc_min = :thc_min")
            params["thc_min"] = u["thc_min"]
            set_parts.append("thc_max = :thc_max")
            params["thc_max"] = u["thc_max"]
        if u["cbd_min"] is not None:
            set_parts.append("cbd_min = :cbd_min")
            params["cbd_min"] = u["cbd_min"]
            set_parts.append("cbd_max = :cbd_max")
            params["cbd_max"] = u["cbd_max"]
        set_parts.append("updated_at = CURRENT_TIMESTAMP")
        params["id"] = u["db_id"]

        if not dry_run:
            sql = f"UPDATE strains SET {', '.join(set_parts)} WHERE id = :id"
            cursor.execute(sql, params)
            applied += cursor.rowcount

    if not dry_run:
        conn.commit()
    conn.close()
    return applied if not dry_run else len(updates)


async def main():
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("Leafly Terpene/Effect Cross-Reference Enrichment")
    print("=" * 60)

    # 1. Scrape all Leafly pages
    print("\n1. Scraping Leafly listing pages (looking for all ~514 pages)...")
    leafly_map, total = await scrape_all_leafly()
    print(f"   Scraped {len(leafly_map)} unique strains from {total} total entries")
    print(f"   Found {sum(1 for s in leafly_map.values() if s['terpenes'])} strains with terpene data")

    # 2. Match against DB
    print("\n2. Cross-referencing against DB strains (4,800)...")
    updates, matched, gaps = match_to_db(leafly_map)
    print(f"   Matched: {matched} strains found on both Leafly and DB")
    print(f"   With new data to fill: {len(updates)}")

    # 3. Gap analysis
    print(f"\n3. Gaps that will be filled:")
    print(f"   Terpenes: {gaps['terpenes']} strains")
    print(f"   Effects:  {gaps['effects']} strains")
    print(f"   THC:      {gaps['thc']} strains")
    print(f"   CBD:      {gaps['cbd']} strains")

    # 4. Apply
    if updates:
        print(f"\n4. {'[DRY RUN] Would update' if dry_run else 'Updating'} {len(updates)} strains in DB...")
        applied = apply_updates(updates, dry_run=dry_run)
        print(f"   {'[DRY RUN] Would update' if dry_run else 'Updated'} {applied} strains")
    else:
        print("\n4. No updates needed — all DB strains already have Leafly data")

    # 5. Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"  Leafly strains scraped:       {len(leafly_map)}")
    print(f"  DB strains matched:           {matched}")
    print(f"  Strains enriched:             {len(updates)}")
    print(f"  New terpene profiles:         {gaps['terpenes']}")
    print(f"  New effect profiles:          {gaps['effects']}")
    print(f"  New THC data:                 {gaps['thc']}")
    print(f"  New CBD data:                 {gaps['cbd']}")

    if not updates:
        print("\n  ✅ DB already well-populated from existing sources")


if __name__ == "__main__":
    asyncio.run(main())