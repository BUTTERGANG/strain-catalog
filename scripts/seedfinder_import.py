"""
Bulk-import seedfinder strains into weed.db.

Loads data/seedfinder_strains.json and inserts strains that don't
already exist in the DB (matched by normalized name).
"""

import json
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "weed.db"
JSON_PATH = BASE_DIR / "data" / "seedfinder_strains.json"

# ── Strain-type mapping ────────────────────────────────────────────────────
STRAIN_TYPE_MAP = {
    "indica / sativa": "hybrid",
    "mostly indica": "indica",
    "mostly sativa": "sativa",
    "indica": "indica",
    "sativa": "sativa",
    "ruderalis / indica / sativa": "hybrid",
    "ruderalis / indica": "hybrid",
    "ruderalis / sativa": "hybrid",
    "ruderalis": "hybrid",
    "unknown": "hybrid",
    "": "hybrid",
}


def normalize_name(name: str) -> str:
    """Normalize a strain name for duplicate checking.

    Lowercases, strips punctuation, and replaces dashes/underscores with spaces.
    """
    name = name.lower().strip()
    name = name.replace("-", " ").replace("_", " ")
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def map_strain_type(raw_type: str) -> str:
    """Map a seedfinder strain_type to a canonical type."""
    return STRAIN_TYPE_MAP.get(raw_type, "hybrid")


def main():
    # ── Load JSON ──────────────────────────────────────────────────────────
    print(f"Loading {JSON_PATH} ...")
    with open(JSON_PATH) as f:
        strains = json.load(f)
    print(f"Loaded {len(strains):,} strains from JSON.")

    # ── Connect to DB ──────────────────────────────────────────────────────
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Ensure the strains table exists (schema from the task description)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS strains (
            id          TEXT PRIMARY KEY,
            name        VARCHAR(200) NOT NULL,
            strain_type VARCHAR(50) NOT NULL,
            rating      FLOAT NOT NULL,
            review_count INTEGER NOT NULL,
            thc_min     FLOAT,
            thc_max     FLOAT,
            cbd_min     FLOAT,
            cbd_max     FLOAT,
            terpenes    TEXT NOT NULL DEFAULT '[]',
            effects     TEXT NOT NULL DEFAULT '[]',
            flavors     TEXT NOT NULL DEFAULT '[]',
            genetics    VARCHAR(500) NOT NULL,
            breeder     VARCHAR(200) NOT NULL,
            is_landrace BOOLEAN NOT NULL DEFAULT 0,
            landrace_origin VARCHAR(200) NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            image_url   VARCHAR(500) NOT NULL DEFAULT '',
            source      VARCHAR(50) NOT NULL,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # ── Build set of existing normalized names ─────────────────────────────
    print("Building set of existing strain names in DB ...")
    cur.execute("SELECT name FROM strains")
    existing_raw = [row["name"] for row in cur.fetchall()]
    existing_normalized = {normalize_name(n) for n in existing_raw}
    print(f"DB has {len(existing_normalized):,} unique normalized strain names.")

    # ── Prepare insert statement ───────────────────────────────────────────
    insert_sql = """
        INSERT INTO strains (
            id, name, strain_type, rating, review_count,
            breeder, genetics, source, image_url,
            terpenes, effects, flavors, description,
            is_landrace, landrace_origin,
            created_at, updated_at
        ) VALUES (
            ?, ?, ?, 0, 0,
            ?, '', 'seedfinder', '',
            '[]', '[]', '[]', '',
            0, '',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
    """

    # ── Import loop ────────────────────────────────────────────────────────
    now = datetime.utcnow()
    new_count = 0
    skipped = 0
    total = len(strains)

    print(f"Importing {total:,} strains ...")

    for i, entry in enumerate(strains):
        raw_name = entry.get("name", "")
        if not raw_name:
            skipped += 1
            continue

        norm = normalize_name(raw_name)
        if norm in existing_normalized:
            skipped += 1
            continue

        # Map strain type
        raw_type = entry.get("strain_type", "unknown")
        strain_type = map_strain_type(raw_type)

        # Generate ID
        strain_id = uuid.uuid4().hex[:12]

        # Get breeder
        breeder = entry.get("breeder", "")

        cur.execute(insert_sql, (strain_id, raw_name, strain_type, breeder))
        existing_normalized.add(norm)  # avoid re-inserting duplicates in this batch
        new_count += 1

        if (i + 1) % 1000 == 0:
            print(f"  Progress: {i+1:,}/{total:,}  |  New inserted: {new_count:,}")

    conn.commit()
    conn.close()

    print(f"\n{'='*60}")
    print(f"Import complete.")
    print(f"  Total strains in JSON:  {total:,}")
    print(f"  New strains inserted:   {new_count:,}")
    print(f"  Skipped (already in DB): {skipped:,}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()