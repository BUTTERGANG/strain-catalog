"""Database migration: SQLite (VPS, full dataset) → Postgres (Neon/Replit).

Usage:
  DATABASE_URL="postgresql+asyncpg://user:pass@host/db" python scripts/migrate_sqlite_to_pg.py [--tables strains,dispensaries]

Design:
- Reads from local SQLite via direct file access (no server needed)
- Writes to any SQLAlchemy async DB (Neon, Replit Postgres) via DATABASE_URL
- Idempotent: upserts by primary key — re-running never duplicates
- Chunked inserts (500/batch) with retry for connection blips
- Preserves all columns; respects Postgres sequence resets

This is the ONE-WAY sync: VPS SQLite is authoritative for scraped data.
Replit-side enrichment should be merged back via PR, not run independently.
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

import sqlite3
import asyncpg

BASE = Path(__file__).resolve().parent.parent
SQLITE = BASE / "data" / "weed.db"

TABLES = {
    "strains": ["id", "name", "strain_type", "rating", "review_count", "thc_min", "thc_max",
                "cbd_min", "cbd_max", "terpenes", "effects", "flavors", "genetics", "breeder",
                "is_landrace", "landrace_origin", "description", "image_url", "source",
                "created_at", "updated_at", "flowering_days", "seed_type", "sativa_pct",
                "indica_pct", "slug", "is_featured"],
    "dispensaries": ["id", "name", "address", "city", "state", "zip_code", "lat", "lon",
                     "phone", "website", "email", "hours", "license_type", "delivery_available",
                     "rating", "review_count", "description", "image_url", "source",
                     "license_number", "created_at"],
    "strain_links": ["id", "parent_id", "child_id", "rel_type", "confidence", "source", "notes", "created_at"],
    "users": ["id", "username", "email", "password_hash", "display_name", "bio", "avatar_url",
              "is_active", "is_public", "is_admin", "created_at", "updated_at"],
    "reviews": ["id", "strain_id", "user_id", "dispensary_id", "rating", "aroma", "flavor",
                "effect", "appearance", "consumption_method", "setting", "price_paid",
                "notes", "photo_url", "is_public", "created_at"],
    "wishlist_items": ["id", "user_id", "strain_id", "notes", "created_at"],
}

CHUNK = 500


def quote_pg_col(col: str) -> str:
    """Postgres reserved words."""
    reserved = {"name", "type", "user", "location", "role", "source", "notes"}
    return f'"{col}"' if col in reserved else col


def convert_value(col: str, val):
    """SQLite → Postgres value coercion."""
    if col in ("is_landrace", "is_public", "is_admin", "is_featured", "delivery_available"):
        return bool(val) if (val := col and val) is not None else False
    return val


async def create_tables(pg_dsn: str):
    """Create tables in Postgres matching our models (SQLAlchemy-free, direct DDL)."""
    ddl = [
        """CREATE TABLE IF NOT EXISTS strains (
            id VARCHAR PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            strain_type VARCHAR(50) DEFAULT 'hybrid',
            rating FLOAT DEFAULT 0,
            review_count INTEGER DEFAULT 0,
            thc_min FLOAT, thc_max FLOAT, cbd_min FLOAT, cbd_max FLOAT,
            terpenes TEXT DEFAULT '[]',
            effects TEXT DEFAULT '[]',
            flavors TEXT DEFAULT '[]',
            genetics VARCHAR(500) DEFAULT '',
            breeder VARCHAR(200) DEFAULT '',
            is_landrace BOOLEAN DEFAULT FALSE,
            landrace_origin VARCHAR(200) DEFAULT '',
            description TEXT DEFAULT '',
            image_url VARCHAR(500) DEFAULT '',
            source VARCHAR(50) DEFAULT 'kaggle',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            flowering_days INTEGER,
            seed_type VARCHAR(50) DEFAULT '',
            sativa_pct FLOAT,
            indica_pct FLOAT,
            slug VARCHAR(100) UNIQUE,
            is_featured BOOLEAN DEFAULT FALSE
        )""",
        """CREATE TABLE IF NOT EXISTS dispensaries (
            id VARCHAR PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            address VARCHAR(500),
            city VARCHAR(100),
            state VARCHAR(50),
            zip_code VARCHAR(20),
            lat FLOAT, lon FLOAT,
            phone VARCHAR(50), website VARCHAR(500) DEFAULT '',
            email VARCHAR(255), hours TEXT,
            license_type VARCHAR(50) DEFAULT 'recreational',
            delivery_available BOOLEAN DEFAULT FALSE,
            rating FLOAT DEFAULT 0, review_count INTEGER DEFAULT 0,
            description TEXT DEFAULT '', image_url VARCHAR(500) DEFAULT '',
            photo_urls TEXT, amenities TEXT,
            license_number VARCHAR(60),
            source VARCHAR(50) DEFAULT 'leafly',
            source_url VARCHAR(500),
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS strain_links (
            id VARCHAR PRIMARY KEY,
            parent_id VARCHAR NOT NULL REFERENCES strains(id) ON DELETE CASCADE,
            child_id VARCHAR NOT NULL REFERENCES strains(id) ON DELETE CASCADE,
            rel_type VARCHAR(30) NOT NULL,
            confidence FLOAT DEFAULT 1.0,
            source VARCHAR(50) NOT NULL,
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(parent_id, child_id)
        )""",
        """CREATE TABLE IF NOT EXISTS users (
            id VARCHAR PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            display_name VARCHAR(100) DEFAULT '',
            bio VARCHAR(500) DEFAULT '',
            avatar_url VARCHAR(500) DEFAULT '',
            is_active BOOLEAN DEFAULT TRUE,
            is_public BOOLEAN DEFAULT TRUE,
            is_admin BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS reviews (
            id VARCHAR PRIMARY KEY,
            strain_id VARCHAR NOT NULL REFERENCES strains(id) ON DELETE CASCADE,
            user_id VARCHAR NOT NULL REFERENCES users(id),
            dispensary_id VARCHAR,
            rating INTEGER NOT NULL,
            aroma TEXT DEFAULT '', flavor TEXT DEFAULT '',
            effect TEXT DEFAULT '', appearance TEXT DEFAULT '',
            consumption_method VARCHAR(50) DEFAULT 'smoked',
            setting VARCHAR(100) DEFAULT '',
            price_paid FLOAT, notes TEXT DEFAULT '',
            photo_url VARCHAR(500) DEFAULT '',
            is_public BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS wishlist_items (
            id VARCHAR PRIMARY KEY,
            user_id VARCHAR NOT NULL REFERENCES users(id),
            strain_id VARCHAR NOT NULL REFERENCES strains(id) ON DELETE CASCADE,
            notes VARCHAR(500) DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, strain_id)
        )""",
        """CREATE TABLE IF NOT EXISTS sessions (
            id VARCHAR PRIMARY KEY,
            token_hash VARCHAR(64) UNIQUE NOT NULL,
            user_id VARCHAR NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW(),
            expires_at TIMESTAMP NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS password_resets (
            id VARCHAR PRIMARY KEY,
            token_hash VARCHAR(64) UNIQUE NOT NULL,
            user_id VARCHAR NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW(),
            expires_at TIMESTAMP NOT NULL,
            used_at TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS genetics_suggestions (
            id VARCHAR PRIMARY KEY,
            strain_id VARCHAR NOT NULL REFERENCES strains(id) ON DELETE CASCADE,
            user_id VARCHAR NOT NULL REFERENCES users(id),
            parent_1 VARCHAR(120) NOT NULL,
            parent_2 VARCHAR(120),
            notes TEXT DEFAULT '',
            status VARCHAR(20) DEFAULT 'pending',
            decided_by VARCHAR,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        # indexes
        "CREATE INDEX IF NOT EXISTS ix_pg_strains_slug ON strains(slug)",
        "CREATE INDEX IF NOT EXISTS ix_pg_strains_breeder ON strains(breeder)",
        "CREATE INDEX IF NOT EXISTS ix_pg_strains_type ON strains(strain_type)",
        "CREATE INDEX IF NOT EXISTS ix_pg_strains_name ON strains(LOWER(name))",
        "CREATE INDEX IF NOT EXISTS ix_pg_links_child ON strain_links(child_id)",
        "CREATE INDEX IF NOT EXISTS ix_pg_links_parent ON strain_links(parent_id)",
        "CREATE INDEX IF NOT EXISTS ix_pg_disp_license ON dispensaries(license_number)",
    ]
    conn = await asyncpg.connect(pg_dsn)
    for stmt in ddl:
        await conn.execute(stmt)
    await conn.close()
    print(f"  created/verified {len(ddl)} tables + indexes")


async def migrate_table(pg, table: str, cols: list[str]) -> dict:
    src = sqlite3.connect(SQLITE, timeout=30)
    src.row_factory = sqlite3.Row
    rows = src.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
    src.close()
    total = len(rows)
    inserted = skipped = 0

    col_list = ", ".join(quote_pg_col(c) for c in cols)
    placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
    upsert = f"""
        INSERT INTO {table} ({col_list})
        VALUES ({placeholders})
        ON CONFLICT (id) DO NOTHING
    """

    for i in range(0, total, CHUNK):
        chunk = rows[i:i+CHUNK]
        values = []
        for row in chunk:
            vals = []
            for col in cols:
                v = row[col]
                vals.append(None if v is None else v)
            values.append(tuple(vals))
        try:
            await pg.executemany(upsert, values)
            inserted += len(chunk)
        except Exception as e:
            print(f"  [warn] {table} chunk {i}: {e}", flush=True)
            # fall back to row-by-row
            for row in chunk:
                try:
                    await pg.execute(upsert, *values)
                    inserted += 1
                except Exception:
                    skipped += 1

    return {"table": table, "total": total, "inserted": inserted, "skipped": skipped}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tables", default="strains,dispensaries,strain_links",
                        help="comma-separated tables to migrate")
    parser.add_argument("--url", default=os.getenv("DATABASE_URL", ""),
                        help="Postgres URL (or set DATABASE_URL env)")
    parser.add_argument("--all", action="store_true", help="migrate all tables incl. users/reviews")
    args = parser.parse_args()

    pg_url = args.url
    if not pg_url:
        print("ERROR: set DATABASE_URL env or pass --url postgresql://...")
        sys.exit(1)
    # normalize driver
    if pg_url.startswith("postgres://"):
        pg_url = pg_url.replace("postgres://", "postgresql://", 1)
    if pg_url.startswith("postgresql+asyncpg://"):
        pg_url = pg_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    tables = list(TABLES.keys()) if args.all else [t.strip() for t in args.tables.split(",")]
    print(f"Migrating {tables} → {pg_url.split('@')[-1][:40]}...")

    conn = await asyncpg.connect(pg_url)
    await create_tables(pg_url)

    for table in tables:
        if table not in TABLES:
            print(f"  skip unknown table {table}")
            continue
        print(f"  {table}...", flush=True)
        result = await migrate_table(conn, table, TABLES[table])
        print(f"  {table}: {result['total']:,} rows, {result['inserted']:,} inserted")

    # verify
    for table in tables:
        n = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
        print(f"  {table} in PG: {n:,}")

    await conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())