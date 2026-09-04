"""QC fixes: orphaned StrainLinks, S/I % normalization, self-mentioning genetics."""
import sqlite3

conn = sqlite3.connect("/home/alex/code/BUTTERGANG/WEED/data/weed.db")
c = conn.cursor()

# 1. Delete orphaned StrainLinks (child or parent strain no longer exists)
c.execute("""DELETE FROM strain_links WHERE child_id NOT IN (SELECT id FROM strains)""")
print(f"Orphaned child links deleted: {c.rowcount}")
c.execute("""DELETE FROM strain_links WHERE parent_id NOT IN (SELECT id FROM strains)""")
print(f"Orphaned parent links deleted: {c.rowcount}")

# 2. Fix S/I percentages that don't sum to 100:
#    - if both present and sum 90-110, scale to exactly 100 (preserve ratio)
#    - if way off (>10 from 100), clear both (bad data)
c.execute("SELECT id, sativa_pct, indica_pct FROM strains WHERE sativa_pct IS NOT NULL AND indica_pct IS NOT NULL AND (sativa_pct + indica_pct) != 100")
rows = c.fetchall()
scaled = cleared = 0
for sid, s_pct, i_pct in rows:
    total = s_pct + i_pct
    if 90 <= total <= 110:
        c.execute("UPDATE strains SET sativa_pct = ROUND(sativa_pct * 100.0 / ?), indica_pct = ROUND(indica_pct * 100.0 / ?) WHERE id = ?", (total, total, sid))
        scaled += 1
    else:
        c.execute("UPDATE strains SET sativa_pct = NULL, indica_pct = NULL WHERE id = ?", (sid,))
        cleared += 1
print(f"S/I scaled to 100: {scaled}, cleared (way off): {cleared}")

# 3. Fix genetics strings that mention the strain itself
c.execute("SELECT id, name, genetics FROM strains WHERE genetics != '' AND (UPPER(genetics) LIKE UPPER(name || ' x%') OR UPPER(genetics) LIKE UPPER('% x ' || name) OR UPPER(genetics) = UPPER(name))")
rows = c.fetchall()
fixed_self = 0
for sid, name, genetics in rows:
    # Remove self-mentions, keep the other parent(s)
    parts = [p.strip() for p in genetics.split(" x ") if p.strip().upper() != name.strip().upper()]
    if parts:
        c.execute("UPDATE strains SET genetics = ? WHERE id = ?", (" x ".join(parts), sid))
        fixed_self += 1
    else:
        c.execute("UPDATE strains SET genetics = '' WHERE id = ?", (sid,))
        fixed_self += 1
print(f"Self-mentioning genetics fixed: {fixed_self}")

# 4. Breeder equals strain name — clear the breeder
c.execute("SELECT COUNT(*) FROM strains WHERE breeder != '' AND UPPER(breeder) = UPPER(name)")
n = c.fetchone()[0]
if n:
    c.execute("UPDATE strains SET breeder = '' WHERE breeder != '' AND UPPER(breeder) = UPPER(name)")
print(f"Breeder=name cleared: {n}")

conn.commit()

# Verify
print("\nPOST-FIX VERIFY")
c.execute("SELECT COUNT(*) FROM strain_links WHERE child_id NOT IN (SELECT id FROM strains)")
print(f"  Orphaned child links: {c.fetchone()[0]}")
c.execute("SELECT COUNT(*) FROM strain_links WHERE parent_id NOT IN (SELECT id FROM strains)")
print(f"  Orphaned parent links: {c.fetchone()[0]}")
c.execute("SELECT COUNT(*) FROM strains WHERE sativa_pct IS NOT NULL AND indica_pct IS NOT NULL AND (sativa_pct + indica_pct) != 100")
print(f"  S/I not summing to 100: {c.fetchone()[0]}")
c.execute("SELECT COUNT(*) FROM strain_links")
print(f"  StrainLinks total: {c.fetchone()[0]:,}")
conn.close()