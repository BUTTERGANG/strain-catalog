"""Round 2: finish the 'their' rows + extract Lineage from ALL descriptions + create StrainLinks.

Fixes vs round 1:
- Breeder from NAME prefix too ('Bean Drop Genetics Better Made Cook...' → known-breeder match)
- Lineage regex handles nested parens + no trailing period
- StrainLinks insert includes source column (round 1 bug — 0 links created)
"""
import re
import sqlite3
import uuid

DB = "/home/alex/code/BUTTERGANG/WEED/data/weed.db"
conn = sqlite3.connect(DB, timeout=60)
c = conn.cursor()


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


name_to_id = {}
for nid, name in c.execute("SELECT id, name FROM strains"):
    name_to_id.setdefault(norm(name), nid)

# ── 1. Remaining 'their' breeder rows: match name prefix against known breeders ──
known_breeders = [b for (b,) in c.execute("""
    SELECT DISTINCT breeder FROM strains
    WHERE breeder != '' AND breeder != 'their'
      AND breeder NOT IN ('Unknown or Legendary', 'Clone Only Strains', 'Unknown')
""").fetchall() if len(b) > 3]
# sort longest-first for greedy match
known_sorted = sorted(known_breeders, key=len, reverse=True)

rows = c.execute("SELECT id, name, description FROM strains WHERE breeder = 'their'").fetchall()
fixed = 0
for sid, name, desc in rows:
    breeder = None
    for kb in known_sorted[:400]:  # top prefix candidates
        if name.lower().startswith(kb.lower() + " "):
            breeder = kb
            break
    if not breeder and desc:
        m = re.match(r"^\s*([^-]{3,60}?)\s+-\s+", desc)
        if m:
            breeder = m.group(1).strip()
    if breeder:
        c.execute("UPDATE strains SET breeder = ? WHERE id = ?", (breeder, sid))
        fixed += 1
print(f"1. 'their' breeder fixed from name/desc: {fixed} / {len(rows)}")

# ── 2. Lineage prose extraction (all strains, empty genetics, description has 'Lineage:') ──
LINEAGE_RE = re.compile(r"[Ll]ineage:\s*(.+?)(?=\s*(?:Indica|Sativa|Flowering|10\s|12\s|5\s|Yield|Height| flower|\.)|$)", re.S)
rows = c.execute("""
    SELECT id, description FROM strains
    WHERE (genetics IS NULL OR genetics = '')
      AND description LIKE '%ineage%'
""").fetchall()
gen_filled = 0
fills = []
for sid, desc in rows:
    m = LINEAGE_RE.search(desc)
    if not m:
        continue
    lineage = m.group(1).strip()
    # Balance parens
    depth = 0
    end = 0
    for i, ch in enumerate(lineage):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                end = i
                break
        elif depth == 0 and ch in ".":
            end = i
            break
        end = i + 1
    lineage = lineage[:end].strip().rstrip(".·,")
    if " x " not in lineage.lower() or len(lineage) > 300:
        continue
    lineage = re.sub(r"\s+[xX]\s+", " x ", lineage)
    fills.append((lineage, sid))
    gen_filled += 1

for genetics, sid in fills:
    c.execute("UPDATE strains SET genetics = ? WHERE id = ?", (genetics, sid))
print(f"2. Genetics from Lineage: prose: {gen_filled}")

# ── 3. StrainLinks for ALL strains with empty-link genetics (incl. round-1 fills) ──
already = {r[0] for r in c.execute("SELECT child_id FROM strain_links")}
links_created = 0
for sid, genetics in c.execute("SELECT id, genetics FROM strains WHERE genetics != ''"):
    if sid in already or not genetics:
        continue
    # split top-level ' x ' only (respect parens)
    parts = re.split(r"\s+[xX]\s+", genetics)
    # strip parenthesized fragments from parent names
    for parent in parts[:2]:
        parent = re.sub(r"\([^)]*\)", "", parent).strip(" ()")
        if not parent:
            continue
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
no_gen = c.execute("SELECT COUNT(*) FROM strains WHERE genetics IS NULL OR genetics = ''").fetchone()[0]
total = c.execute("SELECT COUNT(*) FROM strains").fetchone()[0]
their_left = c.execute("SELECT COUNT(*) FROM strains WHERE breeder = 'their'").fetchone()[0]
conn.close()
print(f"3. New StrainLinks: {links_created} (total {total_links:,})")
print(f"\nRESULT: breeder 'their' left: {their_left} | missing genetics: {no_gen:,}/{total:,} ({100*no_gen/total:.0f}%)")