"""Fix 'their' breeder rows: extract real breeder from about_info prefix, plus parse lineage prose.

1. UPDATE strains SET breeder = <about_info prefix before ' - '> WHERE breeder = 'their'
2. Parse 'Lineage: X x Y' from about_info where genetics is empty (ALL rows, not just 'their')
3. Create StrainLinks where both parents exist in DB
"""
import re
import sqlite3
import uuid

DB = "/home/alex/code/BUTTERGANG/WEED/data/weed.db"
conn = sqlite3.connect(DB, timeout=60)
c = conn.cursor()


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


# ── 1. Fix breeder from description prefix (about_info was imported as description) ──
rows = c.execute("""
    SELECT id, description FROM strains
    WHERE breeder = 'their' AND description IS NOT NULL AND description != ''
""").fetchall()
fixed_breeder = 0
for sid, about in rows:
    m = re.match(r"^\s*([^-]{3,60}?)\s+-\s+", about)
    if m:
        breeder = m.group(1).strip()
        if breeder and breeder.lower() not in ("lineage", "genetics"):
            c.execute("UPDATE strains SET breeder = ? WHERE id = ?", (breeder, sid))
            fixed_breeder += 1
print(f"1. Breeder fixed from about_info prefix: {fixed_breeder} / {len(rows)}")

# Leftover 'their' rows without prefix → use bank/store naming or blank them
left = c.execute("SELECT COUNT(*) FROM strains WHERE breeder = 'their'").fetchone()[0]
print(f"   Remaining 'their' rows: {left}")

# ── 2. Parse 'Lineage: X x Y' prose from description where genetics empty ──
LINEAGE_RE = re.compile(
    r"[Ll]ineage:\s*([A-Za-z0-9'&./()\[\] ]+?)(?:\.|$|\n)",
)
rows = c.execute("""
    SELECT id, description FROM strains
    WHERE (genetics IS NULL OR genetics = '')
      AND description IS NOT NULL AND description != ''
""").fetchall()
gen_filled = 0
fills = []
for sid, about in rows:
    m = LINEAGE_RE.search(about)
    if not m:
        continue
    lineage = m.group(1).strip().rstrip(".")
    # sanity: must contain ' x ' or ' X ' or ' X ' cross marker, or be a single known parent (S1/IBL)
    if " x " in lineage.lower() or " x " in lineage:
        lineage = re.sub(r"\s+x\s+", " x ", lineage, flags=re.I)
        fills.append((lineage[:490], sid))
        gen_filled += 1

for genetics, sid in fills:
    c.execute("UPDATE strains SET genetics = ? WHERE id = ?", (genetics, sid))
print(f"2. Genetics parsed from about_info prose: {gen_filled}")

# ── 3. Create StrainLinks where parents exist ──
name_to_id = {}
for nid, name in c.execute("SELECT id, name FROM strains"):
    name_to_id[norm(name)] = nid

links_created = 0
for sid, genetics in c.execute("SELECT id, genetics FROM strains WHERE genetics != ''"):
    if not genetics:
        continue
    parts = [p.strip() for p in re.split(r"\s+[xX]\s+", genetics) if p.strip()]
    for parent in parts[:2]:
        pid = name_to_id.get(norm(parent))
        if pid and pid != sid:
            try:
                c.execute(
                    "INSERT INTO strain_links (id, parent_id, child_id, rel_type, confidence, source) VALUES (?,?,?,?,?,?)",
                    (uuid.uuid4().hex[:12], pid, sid, "parent", 0.7, "description_parse"),
                )
                links_created += 1
            except sqlite3.IntegrityError:
                pass

conn.commit()
total_links = c.execute("SELECT COUNT(*) FROM strain_links").fetchone()[0]
total = c.execute("SELECT COUNT(*) FROM strains").fetchone()[0]
no_gen = c.execute("SELECT COUNT(*) FROM strains WHERE genetics IS NULL OR genetics = ''").fetchone()[0]
conn.close()
print(f"3. New StrainLinks: {links_created} (total {total_links:,})")
print(f"\nRESULT: {total:,} strains, {no_gen:,} still missing genetics ({100*no_gen/total:.0f}%)")