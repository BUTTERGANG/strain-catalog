"""SeedsHereNow lineage backfill: WP REST API + ACF parent_1/parent_2. 3,600 products.
Waits for DB lock (leafly backfill) to clear, then runs. Resumable via checkpoint."""
import json, re, sqlite3, time, uuid
from pathlib import Path
import httpx

BASE = Path("/home/alex/code/BUTTERGANG/WEED")
CHECKPOINT = BASE / "data" / "shn_backfill.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def wait_for_db(max_wait=1800):
    """Wait until no other writer holds the DB (poll write access)."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            conn = sqlite3.connect(BASE / "data" / "weed.db", timeout=5)
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
            conn.close()
            return True
        except sqlite3.OperationalError:
            time.sleep(30)
    return False


def main():
    # fetch ALL products from SHN
    products = []
    page = 1
    while True:
        r = httpx.get(f"https://seedsherenow.com/wp-json/wp/v2/product?per_page=100&page={page}", headers=HEADERS, timeout=20)
        if r.status_code != 200:
            break
        batch = r.json()
        if not batch:
            break
        products += batch
        print(f"fetched page {page} ({len(products):,} total)", flush=True)
        page += 1
        time.sleep(0.4)

    done = set(json.loads(CHECKPOINT.read_text())) if CHECKPOINT.exists() else set()
    print(f"products: {len(products):,}, already applied: {len(done):,}", flush=True)

    if not wait_for_db():
        print("DB still locked after max wait — aborting")
        return

    conn = sqlite3.connect(BASE / "data" / "weed.db", timeout=60)
    c = conn.cursor()
    name_to_id = {}
    for nid, name in c.execute("SELECT id, name FROM strains").fetchall():
        name_to_id.setdefault(norm(name), nid)

    updated = links = skipped_existing = 0
    for p in products:
        pid = str(p["id"])
        if pid in done:
            continue
        acf = p.get("acf") or {}
        p1 = (acf.get("parent_1") or "").strip()
        p2 = (acf.get("parent_2") or "").strip()
        if not p1 or p1 in ("-", "Unknown"):
            done.add(pid)
            continue
        title = re.sub(r"<[^>]+>", "", p["title"]["rendered"]).strip()
        strain_name = title.split("–")[0].split("(")[0].strip()
        k = norm(strain_name)
        sid = name_to_id.get(k)
        if not sid:
            done.add(pid)
            continue
        existing = c.execute("SELECT COALESCE(genetics, '') FROM strains WHERE id = ?", (sid,)).fetchone()[0]
        if existing.strip():
            skipped_existing += 1
            done.add(pid)
            continue
        parents = [p for p in [p1, p2] if p and norm(p) != k]
        genetics = " x ".join(parents)[:490]
        c.execute("UPDATE strains SET genetics = ? WHERE id = ?", (genetics, sid))
        updated += 1
        for par in parents:
            par_id = name_to_id.get(norm(par))
            if par_id and par_id != sid:
                c.execute(
                    "INSERT OR IGNORE INTO strain_links (id,parent_id,child_id,rel_type,confidence,source,notes) VALUES (?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex[:12], par_id, sid, "parent", 0.85, "seedsherenow", ""),
                )
                links += 1
        done.add(pid)
        if updated % 25 == 0 and updated:
            conn.commit()
            CHECKPOINT.write_text(json.dumps(list(done)))
            print(f"  updated={updated} links={links} skipped={skipped_existing}", flush=True)
        time.sleep(0.1)

    conn.commit()
    CHECKPOINT.write_text(json.dumps(list(done)))
    no_gen = c.execute("SELECT COUNT(*) FROM strains WHERE genetics IS NULL OR genetics = ''").fetchone()[0]
    total = c.execute("SELECT COUNT(*) FROM strains").fetchone()[0]
    tl = c.execute("SELECT COUNT(*) FROM strain_links").fetchone()[0]
    conn.close()
    print(f"DONE: +{updated} genetics, +{links} links, total {tl:,}")
    print(f"missing genetics: {no_gen:,}/{total:,} ({100*no_gen/total:.1f}%)")


main()
