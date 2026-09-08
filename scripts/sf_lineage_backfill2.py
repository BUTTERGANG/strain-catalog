"""Resumable seedfinder lineage backfill (fixed parser: absolute URLs + single quotes)."""
import asyncio, json, re, sqlite3, uuid
from pathlib import Path
import httpx

BASE = Path("/home/alex/code/BUTTERGANG/WEED")
CHECKPOINT = BASE / "data" / "sf_backfill_v2.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}


def parse_lineage(html: str, root_path: str):
    idx = html.find('id="lineage"')
    if idx < 0:
        return []
    section = html[idx:]
    links = re.findall(r"href=['\"](?:https?://seedfinder\.eu)?(/en/strain-info/[a-z0-9-]+/[a-z0-9-]+)['\"][^>]*>((?:(?!</a>).)*?)</a>", section, re.S | re.I)
    root_norm = root_path.strip("/").lower()
    parents, seen = [], set()
    for u, label in links:
        un = u.strip("/").lower()
        if un == root_norm:
            continue
        name = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", label)).strip()
        name = name.replace("»»»", "").strip()
        name = name.split("[probably")[0].strip()
        if u not in seen and name and len(parents) < 2:
            seen.add(u)
            parents.append(name)
    return parents


async def main():
    targets = json.loads((BASE / "data" / "sf_lineage_targets.json").read_text())
    done = set(json.loads(CHECKPOINT.read_text())) if CHECKPOINT.exists() else set()
    print(f"targets {len(targets)}, done {len(done)}", flush=True)

    conn = sqlite3.connect(BASE / "data" / "weed.db", timeout=60)
    c = conn.cursor()
    def norm(n): return re.sub(r"[^a-z0-9]", "", (n or "").lower())
    name_to_id = {}
    for nid, name in c.execute("SELECT id, name FROM strains").fetchall():
        name_to_id.setdefault(norm(name), nid)

    updated = links = 0
    async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        for i, (sid, name, meta) in enumerate(targets):
            if sid in done:
                continue
            main_url = meta["source_url"].rstrip("/")
            root_path = "/" + main_url.split("seedfinder.eu/")[-1]
            try:
                resp = await client.get(main_url)
                if resp.status_code == 200:
                    parents = [p for p in parse_lineage(resp.text, root_path) if norm(p) != norm(name)]
                    if parents:
                        c.execute("UPDATE strains SET genetics = ? WHERE id = ?", (" x ".join(parents[:2])[:490], sid))
                        updated += 1
                        for p in parents[:2]:
                            pid = name_to_id.get(norm(p))
                            if pid and pid != sid:
                                c.execute(
                                    "INSERT OR IGNORE INTO strain_links (id,parent_id,child_id,rel_type,confidence,source,notes) VALUES (?,?,?,?,?,?,?)",
                                    (uuid.uuid4().hex[:12], pid, sid, "parent", 0.8, "seedfinder_backfill", ""),
                                )
                                links += 1
            except Exception:
                pass
            done.add(sid)
            if (i + 1) % 150 == 0:
                conn.commit()
                CHECKPOINT.write_text(json.dumps(list(done)))
                print(f"  {i+1}/{len(targets)} updated={updated} links={links}", flush=True)
            await asyncio.sleep(0.5)
    conn.commit()
    no_gen = c.execute("SELECT COUNT(*) FROM strains WHERE genetics IS NULL OR genetics = ''").fetchone()[0]
    total = c.execute("SELECT COUNT(*) FROM strains").fetchone()[0]
    tl = c.execute("SELECT COUNT(*) FROM strain_links").fetchone()[0]
    conn.close()
    CHECKPOINT.write_text(json.dumps(list(done)))
    print(f"DONE: +{updated} genetics, +{links} links, total links {tl:,}")
    print(f"missing genetics: {no_gen:,}/{total:,} ({100*no_gen/total:.1f}%)")


asyncio.run(main())