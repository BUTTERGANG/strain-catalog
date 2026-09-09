"""Leafly lineage backfill: scrape __NEXT_DATA__ from Leafly strain pages,
extract parents[], fill genetics + StrainLinks for our missing-genetics strains.
Prioritized by review_count (most-visible strains first). Resumable, 0.6s rate."""
import asyncio, json, re, sqlite3, uuid
from pathlib import Path
import httpx

BASE = Path("/home/alex/code/BUTTERGANG/WEED")
CHECKPOINT = BASE / "data" / "leafly_backfill.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_leafly(html: str) -> list[str]:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(\{.*?\})</script>', html, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
        parents = data["props"]["pageProps"]["strain"].get("parents") or []
        return [p["name"] for p in parents if p.get("name")]
    except Exception:
        return []


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


async def main():
    targets = json.loads((BASE / "data" / "leafly_targets.json").read_text())
    done = set(json.loads((CHECKPOINT).read_text())) if CHECKPOINT.exists() else set()
    print(f"targets {len(targets):,}, done {len(done):,}", flush=True)

    conn = sqlite3.connect(BASE / "data" / "weed.db", timeout=60)
    c = conn.cursor()
    def norm(n): return re.sub(r"[^a-z0-9]", "", (n or "").lower())
    name_to_id = {}
    for nid, name in c.execute("SELECT id, name FROM strains").fetchall():
        name_to_id.setdefault(norm(name), nid)

    hits = updated = links = notfound = 0
    async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        for i, (sid, name, slug) in enumerate(targets):
            if sid in done:
                continue
            url = f"https://www.leafly.com/strains/{slug}"
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    parents = parse_leafly(resp.text)
                    if parents:
                        hits += 1
                        parents = [p for p in parents if norm(p) != norm(name)][:2]
                        c.execute("UPDATE strains SET genetics = ? WHERE id = ?",
                                  (" x ".join(parents)[:490] if parents else "", sid))
                        if parents:
                            updated += 1
                        for p in parents:
                            pid = name_to_id.get(norm(p))
                            if pid and pid != sid:
                                c.execute(
                                    "INSERT OR IGNORE INTO strain_links (id,parent_id,child_id,rel_type,confidence,source,notes) VALUES (?,?,?,?,?,?,?)",
                                    (uuid.uuid4().hex[:12], pid, sid, "parent", 0.75, "leafly_backfill", ""),
                                )
                                links += 1
                elif resp.status_code == 404:
                    notfound += 1
            except Exception:
                pass
            done.add(sid)
            if (i + 1) % 200 == 0:
                conn.commit()
                CHECKPOINT.write_text(json.dumps(list(done)))
                print(f"  {i+1:,}/{len(targets):,} hits={hits:,} updated={updated:,} links={links:,} 404s={notfound:,}", flush=True)
            await asyncio.sleep(0.6)

    conn.commit()
    no_gen = c.execute("SELECT COUNT(*) FROM strains WHERE genetics IS NULL OR genetics = ''").fetchone()[0]
    total = c.execute("SELECT COUNT(*) FROM strains").fetchone()[0]
    tl = c.execute("SELECT COUNT(*) FROM strain_links").fetchone()[0]
    conn.close()
    CHECKPOINT.write_text(json.dumps(list(done)))
    print(f"DONE: hits={hits:,} updated={updated:,} links={links:,} 404s={notfound:,}")
    print(f"missing genetics: {no_gen:,}/{total:,} ({100*no_gen/total:.1f}%)")


asyncio.run(main())