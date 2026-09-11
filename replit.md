# Running on Replit

This project is a FastAPI web application using Replit PostgreSQL when
`DATABASE_URL` is available and SQLite otherwise.

## Development

The `Start application` workflow runs:

```sh
uvicorn backend.main:app --host 0.0.0.0 --port 5000
```

Dependencies are pinned in `requirements.txt`. On first startup, the app creates
its tables and seeds them from the data files included in the repository.

Session signing uses `SECRET_KEY` when provided, then Replit's existing
`SESSION_SECRET`, with an insecure development-only fallback as a last resort.