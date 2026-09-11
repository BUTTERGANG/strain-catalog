"""Cross-reference Leafly terpene/effect/image data against the live Postgres DB.

Same scrape/parse logic as leafly_enrich.py (which targets a local sqlite file this
environment doesn't use), adapted to write through backend.database.async_session.
Only fills gaps — never overwrites a field that already has data. Also fills
image_url (leafly_enrich.py scraped it but never persisted it).

Usage:
  python scripts/leafly_enrich_pg.py               — scrape + cross-reference + write
  python scripts/leafly_enrich_pg.py --dry-run      — show what would be updated, no writes
  python scripts/leafly_enrich_pg.py --max-pages N  — limit pages scraped (for a sample run)
"""
import asyncio
import json
import re
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.database import async_session
from backend.models.strain import Strain

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
LEAFLY_BASE = "https://www.leafly.com"
PAGE_DELAY = 0.3


def normalize(name: str) -> str:
    n = name.lower().strip()
    n = n.replace('-', ' ').replace('_', ' ')
    n = re.sub(r'[^a-z0-9\s]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def parse_leafly_strain(s: dict) -> dict:
    name = s.get("name", "")

    category = (s.get("category") or s.get("phenotype") or "hybrid").lower().strip()
    if category not in ("indica", "sativa", "hybrid"):
        category = "hybrid"

    thc_val = s.get("thc")
    thc_min = thc_max = None
    if thc_val is not None:
        try:
            v = float(thc_val)
            thc_min, thc_max = max(0, v - 4), v + 4
        except (ValueError, TypeError):
            pass

    cann = s.get("cannabinoids", {}) or {}
    cbd_min = cbd_max = None
    cbd_data = cann.get("cbd", {}) if isinstance(cann, dict) else {}
    if isinstance(cbd_data, dict):
        try:
            cbd_min = float(cbd_data.get("percentile25", 0) or 0)
            cbd_max = float(cbd_data.get("percentile75", cbd_data.get("percentile50", 0)) or 0)
        except (ValueError, TypeError):
            pass

    effects_raw = s.get("effects", {}) or {}
    effects = []
    if isinstance(effects_raw, dict):
        total = sum(float(e.get("score", 0) or 0) for e in effects_raw.values() if isinstance(e, dict))
        for slug_name, e in effects_raw.items():
            if isinstance(e, dict):
                score = float(e.get("score", 0) or 0)
                pct = round(score / total * 100, 0) if total > 0 else 0
                if pct >= 5:
                    effects.append(e.get("name", slug_name).title())

    terps_raw = s.get("terps", {}) or {}
    terpenes = []
    if isinstance(terps_raw, dict):
        total = sum(float(t.get("score", 0) or 0) for t in terps_raw.values() if isinstance(t, dict))
        for slug_name, t in terps_raw.items():
            if isinstance(t, dict):
                score = float(t.get("score", 0) or 0)
                pct = round(score / total * 100, 1) if total > 0 else 0
                if pct > 0:
                    terpenes.append({"name": t.get("name", slug_name).lower(), "percentage": pct})
        terpenes.sort(key=lambda x: x["percentage"], reverse=True)

    image_url = s.get("nugImage", "") or s.get("flowerImageSvg", "") or ""

    return {
        "name": name, "strain_type": category,
        "thc_min": thc_min, "thc_max": thc_max,
        "cbd_min": cbd_min, "cbd_max": cbd_max,
        "effects": effects, "terpenes": terpenes,
        "image_url": image_url,
    }


async def fetch_leafly_page(page: int, client: httpx.AsyncClient) -> list[dict] | None:
    url = f"{LEAFLY_BASE}/strains?page={page}"
    for attempt in range(3):
        try:
            resp = await client.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
                if not match:
                    return []
                data = json.loads(match.group(1))
                strains_raw = data.get("props", {}).get("pageProps", {}).get("data", {}).get("strains", [])
                return [parse_leafly_strain(s) for s in strains_raw]
            elif resp.status_code == 429:
                await asyncio.sleep(5 * (attempt + 1))
            elif resp.status_code == 404:
                return None
            else:
                if attempt < 2:
                    await asyncio.sleep(2)
        except Exception:
            if attempt < 2:
                await asyncio.sleep(3)
    return []


async def scrape_all_leafly(max_pages: int) -> dict[str, dict]:
    leafly_map = {}
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for page in range(1, max_pages + 1):
            if page % 50 == 0 or page == 1:
                print(f"  Page {page}...", flush=True)
            strains = await fetch_leafly_page(page, client)
            if strains is None:
                print(f"  Reached end at page {page - 1}")
                break
            for s in strains:
                key = normalize(s["name"])
                if key not in leafly_map:
                    leafly_map[key] = s
            await asyncio.sleep(PAGE_DELAY)
    return leafly_map


async def apply_enrichment(leafly_map: dict, dry_run: bool) -> dict:
    gaps = {"terpenes": 0, "effects": 0, "thc": 0, "cbd": 0, "image": 0}
    matched = 0
    async with async_session() as db:
        strains = (await db.execute(select(Strain))).scalars().all()
        for strain in strains:
            key = normalize(strain.name)
            lf = leafly_map.get(key)
            if not lf:
                continue
            matched += 1

            has_terps = strain.terpenes not in (None, "", "[]")
            has_effects = strain.effects not in (None, "", "[]")
            has_thc = strain.thc_min is not None
            has_cbd = strain.cbd_min is not None
            has_image = bool(strain.image_url) and "wikileaf.com" not in strain.image_url

            if lf["terpenes"] and not has_terps:
                gaps["terpenes"] += 1
                if not dry_run:
                    strain.terpenes = json.dumps(lf["terpenes"])
            if lf["effects"] and not has_effects:
                gaps["effects"] += 1
                if not dry_run:
                    strain.effects = json.dumps(lf["effects"])
            if lf["thc_min"] is not None and not has_thc:
                gaps["thc"] += 1
                if not dry_run:
                    strain.thc_min, strain.thc_max = lf["thc_min"], lf["thc_max"]
            if lf["cbd_min"] is not None and not has_cbd:
                gaps["cbd"] += 1
                if not dry_run:
                    strain.cbd_min, strain.cbd_max = lf["cbd_min"], lf["cbd_max"]
            if lf["image_url"] and not has_image:
                gaps["image"] += 1
                if not dry_run:
                    strain.image_url = lf["image_url"]

        if not dry_run:
            await db.commit()
    return {"matched": matched, **gaps}


async def main():
    dry_run = "--dry-run" in sys.argv
    max_pages = 600
    if "--max-pages" in sys.argv:
        max_pages = int(sys.argv[sys.argv.index("--max-pages") + 1])

    print("=" * 60)
    print("Leafly Enrichment (Postgres)")
    print("=" * 60)
    print(f"\n1. Scraping up to {max_pages} Leafly listing pages...")
    leafly_map = await scrape_all_leafly(max_pages)
    print(f"   Scraped {len(leafly_map)} unique strains")

    print("\n2. Cross-referencing against DB + applying gap-fills...")
    stats = await apply_enrichment(leafly_map, dry_run)
    print(f"   Matched: {stats['matched']}")
    print(f"   {'[DRY RUN] Would fill' if dry_run else 'Filled'} terpenes: {stats['terpenes']}")
    print(f"   {'[DRY RUN] Would fill' if dry_run else 'Filled'} effects:  {stats['effects']}")
    print(f"   {'[DRY RUN] Would fill' if dry_run else 'Filled'} THC:      {stats['thc']}")
    print(f"   {'[DRY RUN] Would fill' if dry_run else 'Filled'} CBD:      {stats['cbd']}")
    print(f"   {'[DRY RUN] Would fill' if dry_run else 'Filled'} images:   {stats['image']}")


if __name__ == "__main__":
    asyncio.run(main())
