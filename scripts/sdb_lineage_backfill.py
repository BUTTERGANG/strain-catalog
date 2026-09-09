"""strain-database.com lineage backfill via Playwright (Cloudflare managed challenge).

The site's robots.txt explicitly allows AI/search bots and advertises 51.7K strains
with 35.8K lineage records as "free, open-access reference data".
Strategy per skill: standard CF challenge → Playwright stealth resolves in 2-3s.
Extract genetics from strain pages, match against our DB, fill empty genetics.

Rate: 8-12s/page (human-level), resumable checkpoint, stops on repeated CF failures.
"""
import asyncio
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path

from playwright.async_api import async_playwright

BASE = Path("/home/alex/code/BUTTERGANG/WEED")
CHECKPOINT = BASE / "data" / "sdb_backfill.json"
SITEMAP = BASE / "data" / "sdb_urls.json"
HEADERS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

STEALTH_JS = "Object.defineProperty(navigator, 'webdriver', { get: () => false });"


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


async def fetch_page(page, url: str, tries: int = 2) -> str | None:
    """Fetch a URL through the stealth browser, waiting out the CF challenge."""
    for attempt in range(tries):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)
            content = await page.content()
            if "Verifying you" in content or "Just a moment" in content:
                # challenge in progress — wait longer for resolution
                for _ in range(4):
                    await page.wait_for_timeout(3000)
                    content = await page.content()
                    if "Verifying you" not in content and "Just a moment" not in content:
                        return content
                continue  # retry navigation
            return content
        except Exception as e:
            print(f"  [warn] {url}: {type(e).__name__}", flush=True)
            await page.wait_for_timeout(5000)
    return None


def parse_genetics(html: str) -> str | None:
    """Extract lineage from an sdb strain page."""
    # Look for lineage/parents markers in text
    for pat in [
        r"[Ll]ineage:?\s*</[^>]+>\s*<[^>]*>([^<]{3,200})",
        r"[Ll]ineage</[^>]+>\s*<[^>]*>([^<]{3,200})",
        r"[Pp]arents?:?\s*</[^>]+>\s*<[^>]*>([^<]{3,200})",
        r"cross(?:ed)?\s+(?:of\s+)?([A-Z][\w'&./() ]{2,60}?\s+[xX×]\s+[A-Z][\w'&./() ]{2,60})",
    ]:
        m = re.search(pat, html)
        if m:
            val = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if " x " in val.lower() or "×" in val:
                return val[:490]
    return None


async def main(max_pages: int = 1500):
    # Load target URLs
    if SITEMAP.exists():
        all_urls = json.loads(SITEMAP.read_text())
    else:
        import httpx
        urls = []
        for i in [0, 1]:
            r = httpx.get(f"https://strain-database.com/sitemap/{i}.xml", timeout=15, follow_redirects=True)
            urls += re.findall(r"<loc>(.*?)</loc>", r.text)
        all_urls = [u for u in urls if "/strain/" in u and "/de/" not in u]
        SITEMAP.write_text(json.dumps(all_urls))
        print(f"saved {len(all_urls)} strain URLs", flush=True)

    done = set(json.loads(CHECKPOINT.read_text())) if CHECKPOINT.exists() else set()
    targets = [u for u in all_urls if u not in done][:max_pages]
    print(f"targets: {len(targets):,}, done: {len(done):,}", flush=True)

    conn = sqlite3.connect(BASE / "data" / "weed.db", timeout=60)
    c = conn.cursor()
    name_to_id = {}
    for nid, name in c.execute("SELECT id, name FROM strains").fetchall():
        name_to_id.setdefault(norm(name), nid)

    hits = updated = links = cf_blocked = 0
    consecutive_blocked = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            user_agent=HEADERS_UA,
            viewport={"width": 1440, "height": 900},
        )
        await ctx.add_init_script(STEALTH_JS)
        page = await ctx.new_page()

        for i, url in enumerate(targets):
            strain_slug = url.rstrip("/").split("/")[-1]
            content = await fetch_page(page, url)
            if content is None:
                cf_blocked += 1
                consecutive_blocked += 1
                if consecutive_blocked >= 10:
                    print("10 consecutive CF failures — stopping (IP warming needed)", flush=True)
                    break
                done.add(url)
                continue

            consecutive_blocked = 0
            genetics = parse_genetics(content)
            if genetics:
                hits += 1
                # match by slug: sdb slugs are 'breeder-strainname' — try last segment variants
                cands = {norm(strain_slug), norm(strain_slug.split("-", 1)[-1])}
                sid = None
                for cand in cands:
                    sid = name_to_id.get(cand)
                    if sid:
                        break
                if sid:
                    current = c.execute("SELECT COALESCE(genetics,'') FROM strains WHERE id=?", (sid,)).fetchone()[0]
                    if not current.strip():
                        c.execute("UPDATE strains SET genetics=? WHERE id=?", (genetics, sid))
                        updated += 1
                        # create links for matched parents
                        for par in re.split(r"\s*[xX×]\s+", genetics)[:2]:
                            par = re.sub(r"\([^)]*\)", "", par).strip(" .")
                            pid = name_to_id.get(norm(par))
                            if pid and pid != sid:
                                c.execute(
                                    "INSERT OR IGNORE INTO strain_links (id,parent_id,child_id,rel_type,confidence,source,notes) VALUES (?,?,?,?,?,?,?)",
                                    (uuid.uuid4().hex[:12], pid, sid, "parent", 0.7, "sdb_backfill", ""),
                                )
                                links += 1

            done.add(url)
            if (i + 1) % 25 == 0:
                conn.commit()
                CHECKPOINT.write_text(json.dumps(list(done)))
                print(f"  {i+1:,}/{len(targets):,} hits={hits} updated={updated} links={links} blocked={cf_blocked}", flush=True)
            await page.wait_for_timeout(8000 + (i % 4) * 1000)  # 8-11s human-level

        await browser.close()

    conn.commit()
    no_gen = c.execute("SELECT COUNT(*) FROM strains WHERE genetics IS NULL OR genetics = ''").fetchone()[0]
    total = c.execute("SELECT COUNT(*) FROM strains").fetchone()[0]
    conn.close()
    CHECKPOINT.write_text(json.dumps(list(done)))
    print(f"SESSION DONE: hits={hits} updated={updated} links={links} blocked={cf_blocked}")
    print(f"missing genetics: {no_gen:,}/{total:,} ({100*no_gen/total:.1f}%)")


asyncio.run(main())