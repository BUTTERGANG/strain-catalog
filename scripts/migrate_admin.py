"""Add is_admin to users + is_featured to strains (idempotent)."""
import sqlite3

conn = sqlite3.connect("/home/alex/code/BUTTERGANG/WEED/data/weed.db")
c = conn.cursor()

# users.is_admin
if c.execute("SELECT COUNT(*) FROM pragma_table_info('users') WHERE name='is_admin'").fetchone()[0] == 0:
    c.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0")
    print("Added users.is_admin")
else:
    print("users.is_admin exists")

# strains.is_featured
if c.execute("SELECT COUNT(*) FROM pragma_table_info('strains') WHERE name='is_featured'").fetchone()[0] == 0:
    c.execute("ALTER TABLE strains ADD COLUMN is_featured BOOLEAN DEFAULT 0")
    c.execute("CREATE INDEX IF NOT EXISTS ix_strains_featured ON strains(is_featured) WHERE is_featured = 1")
    print("Added strains.is_featured")
else:
    print("is_featured exists")

# Promote the oldest user as first admin (bootstrap) — alex can promote others in panel
c.execute("SELECT id, username FROM users ORDER BY created_at LIMIT 1")
row = c.fetchone()
if row:
    c.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (row[0],))
    print(f"Admin: {row[1]} ({row[0]})")

conn.commit()
conn.close()
print("Migration done")