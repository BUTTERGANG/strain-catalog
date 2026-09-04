# WEED — Project Overview

> Strain Catalog · Dispensary Finder · Community Reviews · Genetic Lineage
> Live at `localhost:8003` — Run: `cd ~/code/BUTTERGANG/WEED && PYTHONPATH=$PWD .venv/bin/uvicorn backend.main:app --port 8003`

---

## Architecture

```
WEED/
├── backend/
│   ├── main.py              # App entry, photo upload API, stats endpoint
│   ├── config.py             # Settings (DB URL, port, uploads dir)
│   ├── database.py           # Async SQLAlchemy setup (sqlite+aiosqlite)
│   ├── middleware.py          # Session middleware
│   ├── templates.py           # Shared render_page() for all routes (nav + boilerplate)
│   ├── models/
│   │   ├── strain.py         # Strain model (4800 entries) — THC, terpenes, effects, breeder, genetics
│   │   ├── lineage.py        # StrainLink model — parent/child relationships
│   │   ├── review.py         # User reviews (aroma, effect, price)
│   │   ├── dispensary.py     # Dispensary locations + menu items
│   │   └── user.py           # User accounts
│   ├── routers/
│   │   ├── strains.py        # /strains — listing (48/page), detail (terpene bars, lineage tree, photo gallery)
│   │   ├── pages.py          # / — hero, stats, featured; /seeds — landraces; /map — dispensary map
│   │   ├── dispensaries.py   # Dispensary listings + search
│   │   ├── reviews.py        # Review CRUD
│   │   └── auth.py           # Login/register
│   └── static/css/app.css    # Glassmorphism dark theme (580 lines)
├── scripts/
│   ├── scrape_seedfinder.py  # Scrapes 41,737 strains from seedfinder.eu
│   ├── seedfinder_enrich.py  # Cross-references DB vs Seedfinder — fills breeder, type, genetics, StrainLinks
│   ├── leafly_enrich.py      # Cross-references DB vs Leafly — fills terpenes, effects, THC, CBD
│   └── seed.py               # Initial data import (Kaggle + WikiLeaf)
├── data/
│   ├── weed.db               # SQLite database (4,800 strains, 5,193 StrainLinks)
│   ├── seedfinder_strains.json  # 41,737 raw strains from Seedfinder
│   └── cannabis.json         # Original Kaggle dataset (2,351 entries)
└── backend/uploads/          # User-uploaded strain photos
```

## Data Pipeline (Complete ✅)

| Source | What It Provides | Coverage |
|---|---|---|
| **Kaggle + WikiLeaf** (seed.py) | 4,800 base strains, names, types, basic THC | 100% |
| **Seedfinder** (seedfinder_enrich.py) | Breeder, strain_type, genetics string, StrainLinks | 64% (3,089) |
| **Leafly** (leafly_enrich.py) | Terpene profiles, effects, THC/CBD ranges | 85-97% |
| **User uploads** (main.py POST /api/strains/{id}/photos) | Strain photos → /uploads/ | Manual |

## Database State (Final)

| Field | Count | Coverage |
|-------|-------|----------|
| Strains | 4,800 | 100% |
| Breeder | 3,089 | 64% |
| Genetics (parentage) | 3,089 | 64% |
| Terpene profiles | 2,661 | 55% |
| Effects | 4,349 | 91% |
| THC data | 3,919 | 82% |
| CBD data | 4,644 | 97% |
| Images (Leafly/WikiLeaf) | 2,997 | 62% |
| StrainLinks (genetic relationships) | 5,193 | — |

## UI Features

- **Strain listing** — Image-first cards with breeder badge, THC, effects pills; filter by type, sort by name/rating/THC
- **Strain detail** — Hero image, type badge, THC meter bar, CBD stats, effects/flavor pills, color-coded terpene bars
- **Genetic lineage** — Parent cards + offspring cards from StrainLinks data; genetics string shown as badge
- **Photo gallery** — Upload zone → drag/drop multiple photos → lightbox viewer for fullscreen
- **Home page** — Gradient hero, live stats grid, type breakdown, top-rated strains, recent reviews + dispensary map
- **Landrace catalog** — `/seeds` — educational page about foundational genetics
- **Dispensary map** — Leaflet with marker clusters at `/map`

## Scripts Reference

### `scripts/scrape_seedfinder.py`
Scrapes 41,737 cannabis strains from seedfinder.eu.
```
python scripts/scrape_seedfinder.py strains [limit] [--lineage]
python scripts/scrape_seedfinder.py lineage <slug> <breeder>
python scripts/scrape_seedfinder.py detail <slug> <breeder>
```

### `scripts/seedfinder_enrich.py`
Cross-references Seedfinder data against the DB. Two modes:
```
python scripts/seedfinder_enrich.py                    # Match + update breeder/type (fast)
python scripts/seedfinder_enrich.py --fetch-links      # Also fetch lineage pages (~26 min)
```

### `scripts/leafly_enrich.py`
Scrapes all 514 Leafly listing pages (~9,000 entries), matches by name, fills gaps:
```
python scripts/leafly_enrich.py              # Full scrape + update
python scripts/leafly_enrich.py --dry-run   # Preview only
```

## Errors & Quirks
- Seedfinder types like `"mostly indica"` or `"indica / sativa"` normalize to `"indica"`/`"sativa"`/`"hybrid"` in the DB
- Leafly `__NEXT_DATA__` is the only reliable data source — detail pages have no terpene data outside the listing JSON
- Some kaggle strains (1,711 / 36%) have no Seedfinder match (e.g. `13-Dawgs`, `3D-Cbd`) — likely misnamed or legacy
- Terpene percentages from Leafly are relative scores, not absolute measurements

## To-dos
- [ ] Curate high-quality strain images (user upload + sourcing)
- [ ] Breeder filter in strain listing UI
- [ ] Strain comparison tool (side-by-side terpene/THC profiles)
- [ ] Data sync cron job to refresh Leafly/Seedfinder periodically