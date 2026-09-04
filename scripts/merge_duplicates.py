"""Merge duplicate strains: keep the richest record, update StrainLinks, delete the rest."""
import sqlite3, re, uuid
from collections import defaultdict

DB_PATH = "/home/alex/code/BUTTERGANG/WEED/data/weed.db"

def normalize(name):
    n = name.lower().strip().replace('-', ' ').replace('_', ' ')
    return re.sub(r'[^a-z0-9\s]', '', n).strip()

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# 1. Group strains by normalized name
c.execute("SELECT id, name, source FROM strains ORDER BY name")
all_strains = c.fetchall()

groups = defaultdict(list)
for row in all_strains:
    groups[normalize(row["name"])].append(row)

dupe_groups = {k: v for k, v in groups.items() if len(v) > 1}
print(f"Found {len(dupe_groups)} duplicate groups")

# Source priority: more data = better
SOURCE_PRIORITY = {"wikileaf": 0, "kaggle": 1, "seedfinder": 2, "cannabis_intelligence": 3}

def score_strain(db_id):
    """Score how much data a strain has — higher = richer."""
    c2 = conn.cursor()
    c2.execute("""
        SELECT 
            CASE WHEN thc_min IS NOT NULL THEN 1 ELSE 0 END +
            CASE WHEN thc_max IS NOT NULL THEN 1 ELSE 0 END +
            CASE WHEN cbd_min IS NOT NULL THEN 1 ELSE 0 END +
            CASE WHEN effects != '[]' THEN 1 ELSE 0 END +
            CASE WHEN terpenes != '[]' THEN 1 ELSE 0 END +
            CASE WHEN genetics != '' THEN 1 ELSE 0 END +
            CASE WHEN image_url != '' THEN 1 ELSE 0 END +
            CASE WHEN description != '' THEN 1 ELSE 0 END +
            CASE WHEN flowering_days IS NOT NULL THEN 1 ELSE 0 END +
            CASE WHEN sativa_pct IS NOT NULL THEN 1 ELSE 0 END
        FROM strains WHERE id = ?
    """, (db_id,))
    return c2.fetchone()[0]

total_removed = 0
removed_ids = []

for norm, entries in dupe_groups.items():
    if len(entries) < 2:
        continue
    
    # Pick the best: highest data score, then best source priority
    def entry_key(e):
        src_priority = SOURCE_PRIORITY.get(e["source"], 99)
        data_score = score_strain(e["id"])
        return (-data_score, src_priority)
    
    entries.sort(key=entry_key)
    primary_id = entries[0]["id"]
    secondary_ids = [e["id"] for e in entries[1:]]
    
    for sec_id in secondary_ids:
        # Update StrainLinks to point to primary
        try:
            c.execute("UPDATE strain_links SET parent_id = ? WHERE parent_id = ?", (primary_id, sec_id))
        except Exception:
            pass
        try:
            c.execute("UPDATE strain_links SET child_id = ? WHERE child_id = ?", (primary_id, sec_id))
        except Exception:
            pass
        # Remove self-references
        try:
            c.execute("DELETE FROM strain_links WHERE parent_id = child_id")
        except Exception:
            pass
        removed_ids.append(sec_id)
        total_removed += 1

# Delete duplicate strains
for rid in removed_ids:
    c.execute("DELETE FROM strains WHERE id = ?", (rid,))

# Remove any remaining duplicate StrainLinks
c.execute("""
    DELETE FROM strain_links WHERE rowid NOT IN (
        SELECT MIN(rowid) FROM strain_links GROUP BY parent_id, child_id, rel_type
    )
""")

conn.commit()

# Final counts
c.execute("SELECT COUNT(*) FROM strains")
print(f"Strains after merge: {c.fetchone()[0]:,}")
c.execute("SELECT COUNT(*) FROM strain_links")
print(f"StrainLinks after merge: {c.fetchone()[0]:,}")
print(f"Duplicates removed: {total_removed}")

conn.close()