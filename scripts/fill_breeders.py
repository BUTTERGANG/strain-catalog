"""Fill remaining missing breeders from seedfinder JSON."""
import sqlite3, json, re

conn = sqlite3.connect("/home/alex/code/BUTTERGANG/WEED/data/weed.db")
c = conn.cursor()

# Sources of missing breeders
c.execute("SELECT source, COUNT(*) FROM strains WHERE breeder IS NULL OR breeder = '' GROUP BY source")
print("Missing breeders by source:")
for src, count in c.fetchall():
    print(f"  {src}: {count}")

# Load seedfinder JSON
with open("/home/alex/code/BUTTERGANG/WEED/data/seedfinder_strains.json") as f:
    sf = json.load(f)

sf_map = {}
for s in sf:
    n = s["name"].lower().strip().replace("-", " ").replace("_", " ")
    n = re.sub(r"[^a-z0-9\s]", "", n).strip()
    if n and s.get("breeder"):
        sf_map[n] = s["breeder"]

# Try to fill seedfinder-sourced strains
c.execute("SELECT id, name FROM strains WHERE source = 'seedfinder' AND (breeder IS NULL OR breeder = '')")
still_missing = c.fetchall()
filled = 0
for db_id, name in still_missing:
    n = name.lower().strip().replace("-", " ").replace("_", " ")
    n = re.sub(r"[^a-z0-9\s]", "", n).strip()
    if n in sf_map:
        c.execute("UPDATE strains SET breeder = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                  (sf_map[n], db_id))
        filled += 1
conn.commit()
print(f"\nFilled {filled} seedfinder breeders")

# Also try cannabis_intelligence
c.execute("SELECT id, name FROM strains WHERE source = 'cannabis_intelligence' AND (breeder IS NULL OR breeder = '')")
ci_missing = c.fetchall()
import csv
ci_map = {}
with open("/home/alex/code/BUTTERGANG/WEED/data/cannabis_intelligence_database.csv", newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        n = row["strain_name"].lower().strip().replace("-", " ").replace("_", " ")
        n = re.sub(r"[^a-z0-9\s]", "", n).strip()
        if n and row.get("breeder_name", "").strip():
            ci_map[n] = row["breeder_name"].strip()
ci_filled = 0
for db_id, name in ci_missing:
    n = name.lower().strip().replace("-", " ").replace("_", " ")
    n = re.sub(r"[^a-z0-9\s]", "", n).strip()
    if n in ci_map:
        c.execute("UPDATE strains SET breeder = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                  (ci_map[n], db_id))
        ci_filled += 1
conn.commit()
print(f"Filled {ci_filled} cannabis_intelligence breeders")

c.execute("SELECT COUNT(*) FROM strains WHERE breeder IS NULL OR breeder = ''")
print(f"Still missing: {c.fetchone()[0]}")
conn.close()