"""Data freshness: incremental Seedfinder refresh + DB housekeeping.

Run modes:
  strains   — scrape alphabetical listing pages for new strains (A-Z, ~26 pages)
  purge     — delete expired sessions/resets, vacuum
  stats     — report DB coverage snapshot

Usage:
  python scripts/refresh_data.py strains [--full]
  python scripts/refresh_data.py purge
  python scripts/refresh_data.py all
"""
import asyncio
import re
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "weed.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
RATE = 0.5  # seconds between requests


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:80]


def parse_listing_page(html: str) -> list[dict]:
    """Extract strain entries from an alphabetical listing page.

    Links look like: /en/strain-info/{strain-slug}/{breeder-slug}
    """
    strains = []
    seen = set()
    for m in re.finditer(r'href="(https?://seedfinder\.eu)?(/en/strain-info/([a-z0-9\-]+)/([a-z0-9\-]+))"[^>]*>((?:(?!</a>).)*?)</a>', html, re.S):
        path, slug, breeder_slug, label = m.group(2), m.group(3), m.group(4), m.group(5)
        name = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", label)).strip()
        name = name.replace("&#039;", "'").replace("&amp;", "&").replace("&quot;", '"')
        key = norm(slug)
        if key and key not in seen:
            seen.add(key)
            strains.append({"name": name, "slug": slug, "breeder_slug": breeder_slug, "url": f"https://seedfinder.eu{path}"})
    return strains


async def refresh_strains(full: bool = False) -> dict:
    """Scrape alphabetical listing pages, insert newly-seen strains."""
    import httpx as hx

    letters = "abcdefghijklmnopqrstuvwxyz" if full else "abcdefghijklmnopqrstuvwxyz"
    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()
    existing = {r[0] for r in c.execute("SELECT slug FROM strains WHERE slug IS NOT NULL")}
    existing_norm = {norm(r[0]) for r in c.execute("SELECT name FROM strains")}

    found = inserted = 0
    async with __import__("httpx").AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        for letter in letters:
            page = 1
            while True:
                url = f"https://seedfinder.eu/en/database/strains/alphabetical/{letter}"
                if page > 1:
                    url += f"/page-{page}"
                try:
                    resp = await client.get(url)
                except Exception as exc:
                    print(f"  [warn] {url}: {exc}")
                    break
                if resp.status_code != 200:
                    break
                entries = parse_listing_page(resp.text)
                if not entries:
                    break
                found += len(entries)
                for e in entries:
                    if norm(e["name"]) in existing_norm:
                        continue
                    # Infer type from page text later; default hybrid
                    try:
                        c.execute(
                            "INSERT INTO strains (id, name, slug, strain_type, breeder, source, rating, review_count, terpenes, effects, flavors, genetics, image_url, description, is_landrace, landrace_origin, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                uuid.uuid4().hex[:12],
                                e["name"],
                                e["slug"],
                                "hybrid",
                                "",
                                "seedfinder",
                                0.0,
                                0,
                                "[]", "[]", "[]",
                                "",
                                "",
                                "",
                                0,
                                "",
                                datetime.now(timezone.utc).isoformat(),
                                datetime.now(timezone.utc).isoformat(),
                            ),
                        )
                        inserted += 1
                    except sqlite3.IntegrityError:
                        pass
                conn.commit()
                page += 1
                await asyncio.sleep(RATE)
    conn.close()
    return {"found": found, "inserted": inserted}


def purge_expired() -> dict:
    """Delete expired sessions + password resets, checkpoint WAL."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    n1 = c.execute("DELETE FROM sessions WHERE expires_at < ?", (now,)).rowcount
    n2 = c.execute("DELETE FROM password_resets WHERE expires_at < ? OR used_at IS NOT NULL", (now,)).rowcount
    conn.commit()
    counts = {"sessions_purged": n1, "resets_purged": n2}
    conn.close()
    return counts


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    full = "--full" in sys.argv

    if mode in ("strains", "all"):
        print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M}] Refreshing strains (full={full})...")
        result = asyncio.run(refresh_strains(full))
        print(f"  Found {result['found']:,} listing entries, inserted {result['inserted']} new strains")

    if mode in ("purge", "all"):
        counts = purge_expired()
        print(f"  Purged {counts['sessions_purged']} expired sessions, {counts['resets_purged']} used/expired resets")

    print("Done.")


if __name__ == "__main__":
    main()