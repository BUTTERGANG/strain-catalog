"""Import Cannabis Intelligence Database CSV into WEED database.

Usage: python scripts/cannabis_intelligence_import.py
"""

import csv
import json
import os
import re
import sqlite3
import uuid
from pathlib import Path


def normalize_name(name: str) -> str:
    """Normalize strain name: lowercase, strip punctuation, replace -/_ with spaces."""
    name = name.lower().strip()
    # Replace hyphens and underscores with spaces
    name = name.replace("-", " ").replace("_", " ")
    # Strip remaining punctuation (keep letters, numbers, spaces, apostrophes)
    name = re.sub(r"[^\w\s']", "", name)
    # Collapse multiple spaces
    name = re.sub(r"\s+", " ", name).strip()
    return name


def parse_csv_list_string(s: str) -> str:
    """Parse a CSV string like "['euphoric','creative']" into a JSON array string.
    Returns '[]' if the string is empty or unparseable."""
    if not s or not s.strip():
        return "[]"
    s = s.strip()
    # It looks like a Python list literal: "['euphoric', 'creative']"
    # Replace single quotes with double quotes for JSON
    try:
        # Try to parse as JSON first (in case it's already valid JSON)
        items = json.loads(s)
        if isinstance(items, list):
            return json.dumps(items)
    except (json.JSONDecodeError, TypeError):
        pass
    # Try to parse as Python list literal with single quotes
    try:
        # Remove brackets and split
        inner = s.strip("[]").strip()
        if not inner:
            return "[]"
        # Split by comma, strip whitespace and quotes
        items = []
        for part in inner.split(","):
            part = part.strip().strip("'\"").strip()
            if part:
                items.append(part)
        return json.dumps(items)
    except Exception:
        return "[]"


def parse_float(val: str) -> float | None:
    """Parse a string to float, returning None if empty or invalid."""
    if not val or not val.strip():
        return None
    try:
        return float(val.strip())
    except (ValueError, TypeError):
        return None


def determine_strain_type(sativa_pct: str, indica_pct: str) -> str:
    """Determine strain type from indica/sativa percentages."""
    sat = parse_float(sativa_pct)
    ind = parse_float(indica_pct)

    if ind is not None and ind > 60:
        return "indica"
    if sat is not None and sat > 60:
        return "sativa"
    return "hybrid"


def main():
    base_dir = Path(__file__).resolve().parent.parent
    csv_path = base_dir / "data" / "cannabis_intelligence_database.csv"
    db_path = base_dir / "data" / "weed.db"

    # Check files exist
    if not csv_path.exists():
        print(f"ERROR: CSV not found at {csv_path}")
        return
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}")
        return

    print(f"CSV: {csv_path}")
    print(f"DB:  {db_path}")
    print()

    # Connect to DB
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Pre-load existing strains with normalized names
    print("Loading existing strains from DB...")
    c.execute("SELECT id, name, thc_min, thc_max, cbd_min, cbd_max, effects, flavors, description FROM strains")
    existing_rows = c.fetchall()
    existing = {}  # normalized_name -> {id, name, thc_min, thc_max, ...}
    for row in existing_rows:
        norm = normalize_name(row["name"])
        existing[norm] = dict(row)

    print(f"Existing strains in DB: {len(existing)}")
    print()

    # Load CSV
    print("Loading CSV...")
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        csv_rows = list(reader)

    total_rows = len(csv_rows)
    print(f"CSV rows: {total_rows}")
    print()

    # Stats
    inserted = 0
    updated = 0
    skipped = 0

    # Process
    for i, row in enumerate(csv_rows):
        strain_name = (row.get("strain_name") or "").strip()
        if not strain_name:
            skipped += 1
            continue

        norm = normalize_name(strain_name)

        # Parse values
        thc_min = parse_float(row.get("thc_min"))
        thc_max = parse_float(row.get("thc_max"))
        cbd_min = parse_float(row.get("cbd_min"))
        cbd_max = parse_float(row.get("cbd_max"))
        sativa_pct = (row.get("sativa_percentage") or "").strip()
        indica_pct = (row.get("indica_percentage") or "").strip()
        strain_type = determine_strain_type(sativa_pct, indica_pct)
        breeder = (row.get("breeder_name") or "").strip()
        effects = parse_csv_list_string(row.get("effects") or "")
        flavors = parse_csv_list_string(row.get("flavors") or "")
        about_info = (row.get("about_info") or "").strip()

        if norm in existing:
            # EXISTING — update only where existing values are NULL or empty
            ex = existing[norm]
            updates = []
            params = []

            if ex["thc_min"] is None and thc_min is not None:
                updates.append("thc_min = ?")
                params.append(thc_min)
            if ex["thc_max"] is None and thc_max is not None:
                updates.append("thc_max = ?")
                params.append(thc_max)
            if ex["cbd_min"] is None and cbd_min is not None:
                updates.append("cbd_min = ?")
                params.append(cbd_min)
            if ex["cbd_max"] is None and cbd_max is not None:
                updates.append("cbd_max = ?")
                params.append(cbd_max)
            if (not ex["effects"] or ex["effects"] == "[]") and effects != "[]":
                updates.append("effects = ?")
                params.append(effects)
            if (not ex["flavors"] or ex["flavors"] == "[]") and flavors != "[]":
                updates.append("flavors = ?")
                params.append(flavors)
            if not ex["description"] and about_info:
                updates.append("description = ?")
                params.append(about_info)

            if updates:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(ex["id"])
                c.execute(
                    f"UPDATE strains SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
                updated += 1
        else:
            # NEW — insert
            strain_id = uuid.uuid4().hex[:12]
            c.execute(
                """INSERT INTO strains
                   (id, name, strain_type, breeder, genetics, source, rating, review_count,
                    thc_min, thc_max, cbd_min, cbd_max, terpenes, effects, flavors,
                    description, image_url, is_landrace, landrace_origin,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (
                    strain_id,           # id
                    strain_name,         # name (original case)
                    strain_type,         # strain_type
                    breeder,             # breeder
                    "",                  # genetics
                    "cannabis_intelligence",  # source
                    0.0,                 # rating
                    0,                   # review_count
                    thc_min,             # thc_min
                    thc_max,             # thc_max
                    cbd_min,             # cbd_min
                    cbd_max,             # cbd_max
                    "[]",                # terpenes
                    effects,             # effects (JSON array string)
                    flavors,             # flavors (JSON array string)
                    about_info,          # description
                    "",                  # image_url
                    0,                   # is_landrace
                    "",                  # landrace_origin
                ),
            )
            inserted += 1
            # Track new strain for dedup within this batch
            existing[norm] = {
                "id": strain_id,
                "name": strain_name,
                "thc_min": thc_min,
                "thc_max": thc_max,
                "cbd_min": cbd_min,
                "cbd_max": cbd_max,
                "effects": effects,
                "flavors": flavors,
                "description": about_info,
            }

        if (i + 1) % 1000 == 0:
            print(f"  Progress: {i + 1}/{total_rows} — inserted={inserted}, updated={updated}")

    # Commit
    conn.commit()
    conn.close()

    # Final summary
    print()
    print("=" * 60)
    print("IMPORT COMPLETE")
    print("=" * 60)
    print(f"  Total CSV rows processed: {total_rows}")
    print(f"  New strains inserted:      {inserted}")
    print(f"  Existing strains updated:   {updated}")
    print(f"  Skipped (no name):         {skipped}")
    print()


if __name__ == "__main__":
    main()