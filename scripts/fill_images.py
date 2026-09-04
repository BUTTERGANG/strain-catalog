"""Scrape Leafly listing pages for nugImage URLs and fill missing strain images in weed.db.

Scrapes pages 1-514, extracts nugImage/flowerImageSvg from each strain,
and for any DB strain missing an image_url, updates it if matched by name.
"""

import asyncio
import json
import re
import sqlite3
import sys
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "weed.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
LEAFLY_BASE = "https://www.leafly.com"
PAGE_DELAY = 0.3
MAX_PAGES = 600


def normalize(name: str) -> str:
    """Aggressive name normalization for matching — mirrors leafly_enrich.py."""
    n = name.lower().strip()
    n = n.replace("-", " ").replace("_", " ")
    n = re.sub(r"[^a-z0-9\s]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def build_db_index() -> tuple[dict[str, int], dict[str, str]]:
    """Build {normalized_name: db_id} and {normalized_name: name} for strains missing images."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM strains WHERE image_url IS NULL OR image_url = ''")
    rows = cursor.fetchall()
    conn.close()

    name_to_id: dict[str, int] = {}
    name_to_raw: dict[str, str] = {}
    for db_id, db_name in rows:
        key = normalize(db_name)
        name_to_id[key] = db_id
        name_to_raw[key] = db_name

    return name_to_id, name_to_raw


async def fill_images() -> int:
    """Scrape Leafly pages and fill missing DB images. Returns count of rows updated."""
    name_to_id, name_to_raw = build_db_index()
    total_missing = len(name_to_id)
    print(f"DB strains with missing images: {total_missing}")

    if total_missing == 0:
        print("No missing images to fill. Nothing to do.")
        return 0

    filled = 0
    updated_ids: set[str] = set()  # Track which DB ids we've already filled

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for page in range(1, MAX_PAGES + 1):
            if page % 50 == 0 or page == 1:
                print(f"  Page {page}... (filled so far: {filled})")

            url = f"{LEAFLY_BASE}/strains?page={page}"
            try:
                resp = await client.get(url, headers=HEADERS, timeout=20)
            except Exception as e:
                print(f"  [ERROR] Page {page} request failed: {e}")
                await asyncio.sleep(3)
                continue

            if resp.status_code == 404:
                print(f"  Reached end at page {page - 1}")
                break
            if resp.status_code == 429:
                print(f"  [RATE LIMITED] Page {page}, sleeping 10s...")
                await asyncio.sleep(10)
                continue
            if resp.status_code != 200:
                print(f"  [WARN] Page {page} returned {resp.status_code}, skipping")
                continue

            match = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                resp.text, re.DOTALL
            )
            if not match:
                continue

            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

            strains_raw = (
                data.get("props", {})
                .get("pageProps", {})
                .get("data", {})
                .get("strains", [])
            )

            for s in strains_raw:
                name = s.get("name", "")
                if not name:
                    continue
                key = normalize(name)
                if key not in name_to_id:
                    continue
                db_id = name_to_id[key]
                if db_id in updated_ids:
                    continue  # Already filled this strain

                # Get image URL: prefer nugImage, fallback to flowerImageSvg
                img = s.get("nugImage", "") or s.get("flowerImageSvg", "") or ""
                if img:
                    # Update DB
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE strains SET image_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (img, db_id),
                    )
                    conn.commit()
                    conn.close()
                    updated_ids.add(db_id)
                    filled += 1

            await asyncio.sleep(PAGE_DELAY)

    print(f"\nDone. Filled {filled} / {total_missing} missing images.")
    return filled


async def main():
    print("=" * 60)
    print("Leafly Image Fill — Scrape nugImages for missing DB images")
    print("=" * 60)

    filled = await fill_images()

    print(f"\nFinal count: {filled} images filled")


if __name__ == "__main__":
    asyncio.run(main())