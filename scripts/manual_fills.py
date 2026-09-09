"""Post-leafly fills: verified manual finds + name-parse candidates."""
import re, sqlite3, uuid

MANUAL = {
    "Zendu Kush": "Zkittlez x Hindu Kush x OG",
    "Black Honey Butter": "Cap Junky x Black Cherry Honey",
    "King Mamba": "Mamba x Biker Kush",
    "Purple Sunset": "Purple Punch x Mandarin Sunset",
    "Mondo Smash": "Cookie Smasher x Creme de la Compton F3",
    "I Scream Cake": "Fantasmo Express x Iced 'n' Baked",
    "NYC Sour D": "NYC Diesel x Sour Diesel",
}

conn = sqlite3.connect("/home/alex/code/BUTTERGANG/WEED/data/weed.db", timeout=120)
c = conn.cursor()

def norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())

name_to_id = {}
for nid, name in c.execute("SELECT id, name FROM strains").fetchall():
    name_to_id.setdefault(norm(name), nid)

filled = links = 0

# 1. Manual verified fills
for name, genetics in MANUAL.items():
    sid = name_to_id.get(norm(name))
    if not sid:
        print(f"no match: {name}")
        continue
    cur = c.execute("SELECT COALESCE(genetics,'') FROM strains WHERE id=?", (sid,)).fetchone()[0]
    if cur.strip():
        continue
    c.execute("UPDATE strains SET genetics=? WHERE id=?", (genetics[:490], sid))
    filled += 1
    for par in re.split(r"\s+x\s+", genetics)[:2]:
        par = re.sub(r"\([^)]*\)", "", par).strip()
        pid = name_to_id.get(norm(par))
        if pid and pid != sid:
            try:
                c.execute("INSERT OR IGNORE INTO strain_links (id,parent_id,child_id,rel_type,confidence,source,notes) VALUES (?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex[:12], pid, sid, "parent", 0.8, "web_research", ""))
                links += 1
            except sqlite3.IntegrityError:
                pass
print(f"manual fills: {filled}")

# 2. Name-parse candidates
SUFFIX = re.compile(r"\s+(Strain|Seeds|Feminised|Feminized|Regular|Auto\s*\w*|Fem|Photoperiod|Photo|Reg|F\d+|S\d+|BX\d+|IX\d+|\d+\s*(?:Seeds|Pack|Reg|Fem)).*$", re.I)
rows = c.execute("""
    SELECT id, name FROM strains
    WHERE (genetics IS NULL OR genetics = '') AND (name LIKE '% x %' OR name LIKE '% X %' OR name LIKE '% × %')
""").fetchall()
np = 0
for sid, name in rows:
    parts = re.split(r"\s+[xX×]\s+", name.strip())
    if len(parts) < 2:
        continue
    cleaned = [SUFFIX.sub("", p).strip(" -") for p in parts[:3]]
    cleaned = [p for p in cleaned if p]
    if len(cleaned) < 2:
        continue
    genetics = " x ".join(cleaned)[:490]
    c.execute("UPDATE strains SET genetics=? WHERE id=?", (genetics, sid))
    filled += 1
    np += 1
    for par in cleaned[:2]:
        pid = name_to_id.get(norm(par))
        if pid and pid != sid:
            try:
                c.execute("INSERT OR IGNORE INTO strain_links (id,parent_id,child_id,rel_type,confidence,source,notes) VALUES (?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex[:12], pid, sid, "parent", 0.9, "name_parse", ""))
                links += 1
            except sqlite3.IntegrityError:
                pass
print(f"name-parse fills: {np}")

conn.commit()
no_gen = c.execute("SELECT COUNT(*) FROM strains WHERE genetics IS NULL OR genetics = ''").fetchone()[0]
total = c.execute("SELECT COUNT(*) FROM strains").fetchone()[0]
tl = c.execute("SELECT COUNT(*) FROM strain_links").fetchone()[0]
conn.close()
print(f"TOTAL: +{filled} genetics, +{links} links, total links {tl:,}")
print(f"missing genetics: {no_gen:,}/{total:,} ({100*no_gen/total:.1f}%)")
