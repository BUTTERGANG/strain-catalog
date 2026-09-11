"""Backfill breeder / flowering_days / seed_type from Seedfinder's alphabetical
listing pages (~27 lightweight requests total, no per-strain page fetches) against
the live Postgres DB. Only fills gaps — never overwrites existing data.

Usage:
  python scripts/seedfinder_backfill.py             — scrape + cross-reference + write
  python scripts/seedfinder_backfill.py --dry-run    — show what would be updated, no writes
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.scrape_seedfinder import scrape_strain_list
from backend.database import async_session
from backend.models.strain import Strain
from sqlalchemy import select


def normalize(name: str) -> str:
    n = name.lower().strip()
    n = n.replace('-', ' ').replace('_', ' ')
    n = re.sub(r'[^a-z0-9\s]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def normalize_aggressive(name: str) -> list[str]:
    base = normalize(name)
    candidates = [base]
    stripped = re.sub(r'^[0-9\$#@]+\s*', '', base).strip()
    if stripped != base:
        candidates.append(stripped)
    for prefix in ['original ', 'og ', 'the ', 'auto ']:
        if base.startswith(prefix):
            candidates.append(base[len(prefix):])
    return candidates


def normalize_strain_type(raw: str) -> str:
    """'mostly indica' / 'indica / sativa' / 'ruderalis' -> indica/sativa/hybrid."""
    raw = (raw or "").lower()
    has_indica = "indica" in raw
    has_sativa = "sativa" in raw
    if has_indica and has_sativa:
        return "hybrid"
    if has_indica:
        return "indica"
    if has_sativa:
        return "sativa"
    return ""


async def apply_backfill(sf_strains: list[dict], dry_run: bool) -> dict:
    index: dict[str, dict] = {}
    for s in sf_strains:
        if not s.get("name"):
            continue
        for key in normalize_aggressive(s["name"]):
            index.setdefault(key, s)  # first occurrence wins

    stats = {"matched": 0, "breeder": 0, "flowering_days": 0, "seed_type": 0, "strain_type": 0}
    async with async_session() as db:
        strains = (await db.execute(select(Strain))).scalars().all()
        for strain in strains:
            sf = None
            for key in normalize_aggressive(strain.name):
                if key in index:
                    sf = index[key]
                    break
            if not sf:
                continue
            stats["matched"] += 1

            if sf.get("breeder") and not strain.breeder:
                stats["breeder"] += 1
                if not dry_run:
                    strain.breeder = sf["breeder"]
            if sf.get("flowering_days") and strain.flowering_days is None:
                stats["flowering_days"] += 1
                if not dry_run:
                    strain.flowering_days = sf["flowering_days"]
            if sf.get("seed_type") and not strain.seed_type:
                stats["seed_type"] += 1
                if not dry_run:
                    strain.seed_type = sf["seed_type"]

            clean_type = normalize_strain_type(sf.get("strain_type", ""))
            if clean_type and strain.strain_type == "hybrid" and clean_type != "hybrid":
                # Our default is "hybrid" — only refine it if Seedfinder is more specific.
                stats["strain_type"] += 1
                if not dry_run:
                    strain.strain_type = clean_type

        if not dry_run:
            await db.commit()
    return stats


async def main():
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("Seedfinder Backfill (Postgres) — breeder / flowering / seed type")
    print("=" * 60)
    print("\n1. Scraping Seedfinder alphabetical listing pages...")
    sf_strains = await scrape_strain_list()
    print(f"   Scraped {len(sf_strains)} Seedfinder strain entries")

    print("\n2. Cross-referencing against DB + applying gap-fills...")
    stats = await apply_backfill(sf_strains, dry_run)
    verb = "Would fill" if dry_run else "Filled"
    print(f"   Matched: {stats['matched']}")
    print(f"   {verb} breeder:        {stats['breeder']}")
    print(f"   {verb} flowering_days: {stats['flowering_days']}")
    print(f"   {verb} seed_type:      {stats['seed_type']}")
    print(f"   {verb} strain_type:    {stats['strain_type']}")


if __name__ == "__main__":
    asyncio.run(main())
