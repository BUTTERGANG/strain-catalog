"""Fill genetics from strain names containing crosses (434 candidates)."""
import re, sqlite3, uuid

conn = sqlite3.connect("/home/alex/code/BUTTERGANG/WEED/data/weed.db", timeout=120)
c = conn.cursor()

def norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())

name_to_id = {}
for nid, name in c.execute("SELECT id, name FROM strains").fetchall():
    name_to_id.setdefault(norm(name), nid)

rows = c.execute("""
    SELECT id, name FROM strains
    WHERE (genetics IS NULL OR genetics = '') AND (name LIKE '% x %' OR name LIKE '% X %' OR name LIKE '% × %')
""").fetchall()

SUFFIX = re.compile(r"\s+(Strain|Seeds|Feminised|Feminized|Regular|Auto\s*\w*|Fem|Photoperiod|Photo|Reg|F\d+|S\d+|BX\d+|IX\d+|\d+\s*(?:Seeds|Pack|Reg|Fem)).*$", re.I)

filled = links = 0
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
    for par in cleaned[:2]:
        pid = name_to_id.get(norm(par))
        if pid and pid != sid:
            try:
                c.execute("INSERT OR IGNORE INTO strain_links (id,parent_id,child_id,rel_type,confidence,source,notes) VALUES (?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex[:12], pid, sid, "parent", 0.9, "name_parse", ""))
                links += 1
            except sqlite3.IntegrityError:
                pass

conn.commit()
no_gen = c.execute("SELECT COUNT(*) FROM strains WHERE genetics IS NULL OR genetics = ''").fetchone()[0]
print(f"filled {filled}, links {links}, missing now {no_gen}")
