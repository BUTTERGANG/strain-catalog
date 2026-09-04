"""Dispensary importer — scrape Leafly + insert into weed.db.

Handles NOT NULL constraints by providing empty string defaults for
all fields that Leafly may not return.
"""
import asyncio
import sys
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# ── Leafly scraper (from scrape_leafly.py) ──
import httpx
import re
import json

LEAFLY_BASE = "https://www.leafly.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


async def fetch_dispensary_state(state: str, max_stores: int = 10) -> list[dict]:
    """Scrape Leafly dispensary listings for a state."""
    url = f"{LEAFLY_BASE}/dispensaries/state/{state.lower()}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code != 200:
            print(f"  {state}: HTTP {resp.status_code}")
            return []
        html = resp.text

    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        print(f"  {state}: no __NEXT_DATA__")
        return []

    data = json.loads(match.group(1))
    dispensaries = []
    try:
        props = data.get("props", {}).get("pageProps", {})
        slr = props.get("storeLocatorResults", {})
        stores_data = slr.get("data", {})
        # Leafly returns organicStores, sponsoredStores, spotlightStores
        all_stores = []
        for key in ("organicStores", "sponsoredStores", "spotlightStores"):
            all_stores.extend(stores_data.get(key, []))

        for s in all_stores[:max_stores]:
            name = s.get("name", "")
            slug = s.get("slug", "")
            addr = s.get("address", {}) or {}
            if not name:
                continue
            dispensaries.append({
                "name": name,
                "slug": slug,
                "address": (addr.get("address1", "") or "") + (" " + addr.get("address2", "") if addr.get("address2") else ""),
                "city": addr.get("city", "") or "",
                "state": addr.get("state", state.upper()).upper(),
                "zip_code": addr.get("zip", "") or "",
                "lat": addr.get("lat"),
                "lon": addr.get("lon"),
                "phone": s.get("phone", "") or "",
                "website": s.get("website", "") or "",
                "rating": float(s.get("rating", 0)) if s.get("rating") else None,
                "review_count": int(s.get("reviewCount", 0) or 0),
                "hours": json.dumps(s.get("hours", {}) if isinstance(s.get("hours"), dict) else {}),
                "license_type": "recreational",
                "delivery_available": bool(s.get("configurations", {}).get("deliveryEnabled", False)) if s.get("configurations") else False,
                "source_url": f"{LEAFLY_BASE}/dispensary-info/{slug}",
                "description": s.get("description", "") or "",
                "image_url": s.get("imageUrl", "") or s.get("logoUrl", "") or "",
                "email": s.get("email", "") or "",
                "photo_urls": "[]",
                "amenities": "[]",
            })
    except Exception as e:
        print(f"  [ERROR] Parsing {state}: {e}")

    print(f"  Found {len(dispensaries)} dispensaries in {state}")
    return dispensaries


# ── DB Insert ──
import sqlite3

DB_PATH = BASE_DIR / "data" / "weed.db"

STATES = ["california", "colorado", "washington", "oregon", "michigan",
          "nevada", "arizona", "illinois", "massachusetts", "florida"]

INSERT_SQL = """
INSERT INTO dispensaries (
    id, name, address, city, state, zip_code, lat, lon,
    phone, website, email, hours, license_type, delivery_available,
    rating, review_count, description, image_url, photo_urls, amenities,
    source, source_url, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
"""


async def main():
    print("=" * 60)
    print("Dispensary Import — Leafly")
    print("=" * 60)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Default empty strings for all NOT NULL text fields
    EMPTY = {"zip_code": "", "phone": "", "website": "", "email": "",
             "hours": "{}", "description": "", "image_url": "",
             "photo_urls": "[]", "amenities": "[]"}

    total_inserted = 0
    for state in STATES:
        print(f"\n--- {state} ---")
        stores = await fetch_dispensary_state(state, max_stores=10)
        if not stores:
            print(f"  No stores found for {state}")
            continue

        for d in stores:
            try:
                d_id = uuid.uuid4().hex[:12]
                cur.execute(INSERT_SQL, (
                    d_id, d["name"], d["address"], d["city"], d["state"],
                    d.get("zip_code", "") or "",
                    d["lat"], d["lon"],
                    d.get("phone", "") or "",
                    d.get("website", "") or "",
                    d.get("email", "") or "",
                    d.get("hours", "{}") or "{}",
                    d.get("license_type", "recreational") or "recreational",
                    1 if d.get("delivery_available") else 0,
                    d.get("rating"), d.get("review_count", 0) or 0,
                    d.get("description", "") or "",
                    d.get("image_url", "") or "",
                    "[]", "[]",
                    "leafly", d.get("source_url", "") or "",
                ))
                total_inserted += 1
            except Exception as e:
                print(f"    [ERROR] {d['name']}: {e}")

        conn.commit()
        print(f"  Inserted {sum(1 for _ in stores)} for {state}")

    conn.close()
    print(f"\n{'='*60}")
    print(f"Total dispensaries inserted: {total_inserted}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())