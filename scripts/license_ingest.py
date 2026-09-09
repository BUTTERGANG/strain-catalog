"""State cannabis license registry ingestion: MA + NY + CO public records.

Adds verified license data to the dispensaries table:
- license_number column (new)
- source='state_registry' + license_number for dedupe
- Only ingest ACTIVE licenses; map state license types → our license_type
- Geocode via address when lat/lon missing (skipped for now — geocoder needed)

Usage: python scripts/license_ingest.py [--dry-run]
"""
import csv
import io
import json
import re
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import httpx

BASE = Path("/home/alex/code/BUTTERGANG/WEED")
DB = BASE / "data" / "weed.db"

HEADERS = {"User-Agent": "Mozilla/5.0"}

SOURCES = {
    "MA": {
        "url": "https://masscannabiscontrol.com/resource/l_licenses_all_details_public.csv",
        "fmt": "csv",
    },
    "NY": {
        "url": "https://data.ny.gov/resource/jskf-tt3q.json?$limit=5000",
        "fmt": "json",
    },
    "CO": {
        "url": "https://docs.google.com/spreadsheets/d/170ZEhmBncg8SSIu-uB50wS5-tylgG7p0fRTB1mZhaTU/export?format=csv",
        "fmt": "csv",
        "kind": "cultivation",  # this sheet is cultivations only
    },
}


def norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def map_license_type(raw: str, state: str) -> str:
    raw_l = (raw or "").lower()
    if "cultiv" in raw_l or "grower" in raw_l:
        return "cultivator"
    if "retail" in raw_l or "dispensary" in raw_l or "store" in raw_l:
        return "recreational"
    if "micro" in raw_l:
        return "microbusiness"
    if "processor" in raw_l or "manufact" in raw_l:
        return "processor"
    if "deliver" in raw_l:
        return "delivery"
    if "medical" in raw_l or "mtc" in raw_l:
        return "medical"
    return "recreational"


def fetch_ma() -> list[dict]:
    out = []
    r = httpx.get(SOURCES["MA"]["url"], headers=HEADERS, timeout=30, follow_redirects=True)
    reader = csv.DictReader(io.StringIO(r.text))
    for row in reader:
        status = (row.get("APP_STATUS") or row.get("LICENSE_STATUS") or "").upper()
        if "FINAL" not in status and "ACTIVE" not in status:
            continue
        out.append({
            "state": "MA",
            "name": (row.get("DBA_NAME") or row.get("BUSINESS_NAME") or "").strip(),
            "license_number": (row.get("LICENSE_NUMBER") or "").strip(),
            "license_type": map_license_type(row.get("LICENSE_TYPE"), "MA"),
            "address": (row.get("BUSINESS_ADDRESS_1") or "").strip(),
            "city": (row.get("BUSINESS_CITY") or "").strip(),
            "zip": (row.get("BUSINESS_ZIP_CODE") or "").strip(),
            "phone": (row.get("BUSINESS_PHONE") or "").strip(),
            "email": (row.get("BUSINESS_EMAIL") or "").strip(),
        })
    return out


def fetch_ny() -> list[dict]:
    r = httpx.get(SOURCES["NY"]["url"], headers=HEADERS, timeout=30)
    out = []
    for row in r.json():
        if row.get("license_status_code") != "LICACT":
            continue
        out.append({
            "state": "NY",
            "name": (row.get("dba") or row.get("entity_name") or "").strip(),
            "license_number": (row.get("license_number") or "").strip(),
            "license_type": map_license_type(row.get("license_type"), "NY"),
            "address": (row.get("address_line_1") or "").strip(),
            "city": (row.get("city") or "").strip(),
            "zip": (row.get("zip_code") or "").strip(),
            "phone": "",
            "email": "",
        })
    return out


def fetch_co() -> list[dict]:
    r = httpx.get(SOURCES["CO"]["url"], headers=HEADERS, timeout=30, follow_redirects=True)
    out = []
    reader = csv.DictReader(io.StringIO(r.text))
    for row in reader:
        out.append({
            "state": "CO",
            "name": (row.get("DBA") or row.get("Facility Name") or "").strip(),
            "license_number": (row.get("License Number") or "").strip(),
            "license_type": "cultivator",
            "address": (row.get("Street") or "").strip(),
            "city": (row.get("City") or "").strip(),
            "zip": (row.get("ZIP Code") or "").strip(),
            "phone": "",
            "email": "",
        })
    return out


def ensure_columns(c):
    has_ln = c.execute("SELECT COUNT(*) FROM pragma_table_info('dispensaries') WHERE name='license_number'").fetchone()[0]
    if not has_ln:
        c.execute("ALTER TABLE dispensaries ADD COLUMN license_number VARCHAR(60)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_disp_license ON dispensaries(license_number)")
        print("  added license_number column")


def ingest(state: str, records: list[dict], dry: bool) -> dict:
    conn = sqlite3.connect(DB, timeout=60)
    c = conn.cursor()
    ensure_columns(c)

    # existing license numbers + name/city keys for dedupe
    existing_licenses = {r[0] for r in c.execute(
        "SELECT license_number FROM dispensaries WHERE license_number IS NOT NULL AND license_number != ''")}
    existing_keys = set()
    for name, city in c.execute("SELECT name, city FROM dispensaries"):
        existing_keys.add(norm_name(name))
        if city:
            existing_keys.add(norm_name(name) + "|" + norm_name(city))

    inserted = updated = skipped = 0
    for rec in records:
        if not rec["name"] or not rec["license_number"]:
            skipped += 1
            continue
        ln = rec["license_number"]
        key = norm_name(rec["name"])
        if ln in existing_licenses:
            skipped += 1
            continue
        if key in existing_keys and state != "CO":
            # existing dispensary — attach license number + type if missing
            row = c.execute(
                "SELECT id, license_number FROM dispensaries WHERE LOWER(name) = ? LIMIT 1",
                (rec["name"].lower(),),
            ).fetchone()
            if row and not row[1]:
                if not dry:
                    c.execute("UPDATE dispensaries SET license_number=?, license_type=COALESCE(NULLIF(license_type,''),?) WHERE id=?",
                              (ln, rec["license_type"], row[0]))
                updated += 1
            else:
                skipped += 1
            existing_licenses.add(ln)
            continue

        if not dry:
            c.execute(
                """INSERT INTO dispensaries
                   (id, name, state, city, address, zip_code, phone, email, website,
                    hours, license_type, license_number, delivery_available, rating, review_count,
                    description, image_url, photo_urls, amenities, source, source_url, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                (
                    uuid.uuid4().hex[:12],
                    rec["name"],
                    rec["state"],
                    rec["city"],
                    rec["address"],
                    rec["zip"],
                    rec["phone"],
                    rec["email"],
                    "",
                    "",
                    rec["license_type"],
                    ln,
                    0,
                    0.0,
                    0,
                    "",
                    "",
                    "",
                    "",
                    f"state_registry:{state}",
                    "",
                ),
            )
        inserted += 1
        existing_licenses.add(ln)
        existing_keys.add(key)

    if not dry:
        conn.commit()

    counts = {
        "total_records": c.execute("SELECT COUNT(*) FROM dispensaries").fetchone()[0],
        "with_license": c.execute("SELECT COUNT(*) FROM dispensaries WHERE license_number IS NOT NULL AND license_number != ''").fetchone()[0],
    }
    conn.close()
    return {"state": state, "in": len(records), "inserted": inserted, "updated": updated,
            "skipped": skipped, **counts}


def main():
    dry = "--dry-run" in sys.argv
    only = None
    for a in sys.argv[1:]:
        if a.upper() in SOURCES:
            only = a.upper()

    print(f"Ingesting state license registries (dry={dry})\n")
    all_records = {}
    for state, cfg in SOURCES.items():
        if only and state != only:
            continue
        try:
            fetcher = {"MA": fetch_ma, "NY": fetch_ny, "CO": fetch_co}[state]
            records = fetcher()
            all_records[state] = records
            print(f"{state}: fetched {len(records):,} active licenses")
        except Exception as e:
            print(f"{state}: fetch error {type(e).__name__}: {e}")

    results = {}
    for state, records in all_records.items():
        res = ingest(state, records, dry)
        results[state] = res
        print(f"  {state}: {res['inserted']:,} inserted, {res['updated']:,} updated, {res['skipped']:,} skipped")
        print(f"  dispensaries now: {res['total_records']:,} total, {res['with_license']:,} with license numbers")

    # save research + results
    out = BASE / "data" / "license_ingest_results.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nsaved {out.name}")


if __name__ == "__main__":
    main()