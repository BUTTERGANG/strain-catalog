"""Scrape lineage pages for the 913 seedfinder-matchable missing-genetics strains.
Extracts parents from #lineage section + updates genetics + StrainLinks. Resumable."""
import asyncio
import json
import re
import sqlite3
import uuid
from pathlib import Path

import httpx

BASE = Path("/home/alex/code/BUTTERGANG/WEED")
DB = BASE / "data" / "weed.db"
CHECKPOINT = BASE / "data" / "lineage_backfill_checkpoint.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_lineage(html: str) -> list[str]:
    """Extract parent names from a seedfinder strain page's lineage section."""
    parents = []
    # Lineage section links: /en/strain-info/{parent-slug}/{breeder-slug}
    # only take links in the lineage div — seedfinder marks the section
    m = re.search(r'id="lineage"(.*?)<div id="breeder|id="lineage"(.*?)$', html, re.S)
    section = m.group(0) if m else html
    seen = set()
    for pm in re.finditer(r'href="/en/strain-info/([a-z0-9-]+)/([a-z0-9-]+)"[^>]*>((?:(?!</a>).)*?)</a>', section, re.S):
        slug, label = pm.group(1), pm.group(3)
        name = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", label)).strip()
        name = name.replace("&#039;", "'").replace("&amp;", "&")
        k = slug.strip("-")
        if k and k not in seen and name:
            seen.add(k)
            parents.append(name)
        if len(parents) >= 4:
            break
    return parents


async def main():
    targets = json.loads((BASE / "data" / "sf_lineage_targets.json").read_text())
    done = set()
    if CHECKPOINT.exists():
        done = set(json.loads(CHECKPOINT.read_text()))
    print(f"Targets: {len(targets)}, already done: {len(done)}")

    conn = sqlite3.connect(DB, timeout=60)
    c = conn.cursor()

    def norm(name):
        return re.sub(r"[^a-z0-9]", "", (name or "").lower())

    name_to_id = {}
    for nid, name in c.execute("SELECT id, name FROM strains").fetchall():
        name_to_id.setdefault(norm(name), nid)

    updated = links = 0
    async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        for i, (sid, name, sf_meta) in enumerate(targets):
            if sid in done:
                continue
            url = sf_meta["source_url"].rstrip("/") + "/genealogy"
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    parents = parse_lineage(resp.text)
                    parents = [p for p in parents if norm(p) != norm(name)][:2]
                    if parents:
                        genetics = " x ".join(parents)
                        c.execute("UPDATE strains SET genetics = ? WHERE id = ?", (genetics[:490], sid))
                        updated += 1
                        for p in parents:
                            pid = name_to_id.get(norm(p))
                            if pid and pid != sid:
                                try:
                                    c.execute(
                                        "INSERT OR IGNORE INTO strain_links (id,parent_id,child_id,rel_type,confidence,source,notes) VALUES (?,?,?,?,?,?,?)",
                                        (uuid.uuid4().hex[:12], pid, sid, "parent", 0.8, "seedfinder_backfill", ""),
                                    )
                                    links += 1
                                except sqlite3.IntegrityError:
                                    pass
                done.add(sid)
            except Exception as e:
                print(f"  [warn] {name}: {e}")
                done.add(sid)

            if (i + 1) % 100 == 0:
                conn.commit()
                CHECKPOINT.write_text(json.dumps(list(done)))
                print(f"  {i+1}/{len(targets)} — updated: {updated}, links: {links}")
            await asyncio.sleep(0.5)

    conn.commit()
    total_links = c.execute("SELECT COUNT(*) FROM strain_links").fetchone()[0]
    no_gen = c.execute("SELECT COUNT(*) FROM strains WHERE genetics IS NULL OR genetics = ''").fetchone()[0]
    total = c.execute("SELECT COUNT(*) FROM strains").fetchone()[0]
    conn.close()
    CHECKPOINT.write_text(json.dumps(list(done)))
    print(f"\nDONE: {updated} strains updated, {links} links (total {total_links:,})")
    print(f"Missing genetics now: {no_gen:,}/{total:,} ({100*no_gen/total:.1f}%)")


asyncio.run(main())