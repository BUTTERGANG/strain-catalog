# Running on Replit

This project is a FastAPI web application using Replit PostgreSQL when
`DATABASE_URL` is available and SQLite otherwise.

## Database Architecture (Hub-and-Spoke)

The VPS local SQLite (`data/weed.db`) is the **authoritative dataset** —
all scraping, enrichment, and ingestion run there. The Neon Postgres that
Replit connects to is an **additive consumer**: it receives pushes via
`scripts/migrate_sqlite_to_pg.py` and never makes unilateral schema/data changes.

To sync:

```sh
DATABASE_URL="postgresql://..." python scripts/migrate_sqlite_to_pg.py --all
```

Idempotent by primary key — safe to re-run. See the skill reference
(`replit-setup` → `references/database-sync-pattern.md`) for the full pattern
and when NOT to use it.

## Development

The `Start application` workflow runs:

```sh
uvicorn backend.main:app --host 0.0.0.0 --port 5000
```

Dependencies are pinned in `requirements.txt`. On first startup, the app creates
its tables and seeds them from the data files included in the repository.

Session signing uses `SECRET_KEY` when provided, then Replit's existing
`SESSION_SECRET`, with an insecure development-only fallback as a last resort.
