"""Add performance indexes + slug column to strains (idempotent)."""
import sqlite3
import re

conn = sqlite3.connect("/home/alex/code/BUTTERGANG/WEED/data/weed.db")
c = conn.cursor()

# Indexes for common filters (CREATE INDEX IF NOT EXISTS is idempotent)
indexes = [
    "CREATE INDEX IF NOT EXISTS ix_strains_breeder ON strains(breeder)",
    "CREATE INDEX IF NOT EXISTS ix_strains_strain_type ON strains(strain_type)",
    "CREATE INDEX IF NOT EXISTS ix_strains_name_lower ON strains(LOWER(name))",
    "CREATE INDEX IF NOT EXISTS ix_strains_genetics ON strains(genetics)",
    "CREATE INDEX IF NOT EXISTS ix_strains_effects ON strains(effects)",
    "CREATE INDEX IF NOT EXISTS ix_strains_rating_desc ON strains(rating DESC)",
    "CREATE INDEX IF NOT EXISTS ix_strains_review_count ON strains(review_count)",
    "CREATE INDEX IF NOT EXISTS ix_links_child ON strain_links(child_id)",
    "CREATE INDEX IF NOT EXISTS ix_links_parent ON strain_links(parent_id)",
]
for ix in indexes:
    c.execute(ix)
print(f"Created/verified {len(indexes)} indexes")

# Slug column for SEO-friendly URLs
c.execute("SELECT COUNT(*) FROM pragma_table_info('strains') WHERE name = 'slug'")
if c.fetchone()[0] == 0:
    c.execute("ALTER TABLE strains ADD COLUMN slug TEXT")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_strains_slug ON strains(slug) WHERE slug IS NOT NULL")
    # Populate: lowercase, strip non-alnum to dashes, dedupe with suffix
    c.execute("SELECT id, name FROM strains")
    seen = {}
    rows = c.fetchall()
    updates = []
    for sid, name in rows:
        base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:80] or "strain"
        slug = base
        n = seen.get(base, 0)
        if slug in seen and seen[slug] != sid:
            n = seen.get(base + "_count", 0) + 1
            slug = f"{base}-{n}"
        seen[base] = sid
        seen[slug] = sid
        seen[base + "_count"] = n
        updates.append((slug, sid))
    c.executemany("UPDATE strains SET slug = ? WHERE id = ?", updates)
    print(f"Populated {len(updates):,} slugs")
else:
    print("slug column already exists")

conn.commit()
conn.close()
print("Done")