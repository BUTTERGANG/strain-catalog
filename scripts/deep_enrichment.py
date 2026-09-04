"""Deep enrichment: parse genetics → StrainLinks, import flowering/seed_type, landrace detection, sativa/indica %."""

import csv
import json
import re
import sqlite3
import uuid
from pathlib import Path
from collections import Counter

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "weed.db"


def normalize(name: str) -> str:
    n = name.lower().strip()
    n = n.replace('-', ' ').replace('_', ' ')
    n = re.sub(r'[^a-z0-9\s]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


# ── Known landrace names and patterns ──
LANDRACE_NAMES = {
    "afghani", "hindu kush", "kush", "thai", "durban poison", "maui wowie",
    "panama red", "acapulco gold", "colombian gold", "colombia", "mexico",
    "mexican", "jamaican", "jamaica", "thailand", "afghanistan", "vietnam",
    "vietnamese", "cambodian", "cambodia", "laos", "laotian", "nepal",
    "nepalese", "pakistan", "pakistani", "indian", "brazil", "brazilian",
    "malawi", "malawi gold", "kilimanjaro", "kenya", "kenyan", "ethiopia",
    "ethiopian", "ghana", "ghanian", "nigerian", "niger", "angola",
    "swaziland", "swazi", "lesotho", "roi", "red congo", "congo",
    "congolese", "lambs bread", "lamb's bread", "lamb bread",
    "kerala", "kerala gold", "kerala indica", "manali", "malana",
    "charas", "ganja", "temple", "punto rojo", "mango biche",
    "santa marta", "corinto", "parvati", "kashmir", "africana",
    "thai stick", "cherry bomb", "otto", "cannatonic", "bakerstreet",
    "hawaiian", "jamaican pearl", "kandahar", "mazar", "mazar i sharif",
}

LANDRACE_BREEDERS = {
    "the landrace team", "landrace bureau", "indian landrace exchange",
    "ace seeds", "kannabia seeds", "world of seeds bank",
    "the real seed company", "sativa seeds", "original strains",
    "unknown or legendary", "clone only strains",
}

# Edge cases: strains named like "Kush" that aren't landrace
NOT_LANDRACE = {"og kush", "purple kush", "bubba kush", "master kush",
                "pink kush", "platinum kush", "lemon kush", "blue kush",
                "green kush", "grape kush", "black kush", "golden kush",
                "hindu kush auto", "kush berry", "kush cake", "kush mints",
                "kush n cheese", "kushage", "kushberry", "kushy kush"}


def is_landrace_strain(name: str, breeder: str, strain_type: str) -> tuple[bool, str]:
    """Check if a strain is likely a landrace. Returns (is_landrace, origin)."""
    n = name.lower().strip()
    b = breeder.lower().strip() if breeder else ""
    original_name = name

    # Skip obviously modern hybrids
    if n in NOT_LANDRACE:
        return False, ""

    # Skip if it's a hybrid (cross-breed)
    if strain_type not in ("indica", "sativa"):
        return False, ""

    # Check if the name contains "x" — indicates a cross, not landrace
    if " x " in n:
        return False, ""

    # "Landrace" or "Pure" in name
    if "landrace" in n:
        origin = _extract_origin(n)
        return True, origin or "Unknown"

    # Check against known landrace name list
    for lr_name in LANDRACE_NAMES:
        if lr_name in n:
            # Skip if the breeder is clearly a modern hybridizer
            if b and b not in LANDRACE_BREEDERS and "unknown" not in b:
                return False, ""
            origin = _extract_origin(n)
            return True, origin or lr_name.title()

    # Check breeder: landrace specialists
    if b in LANDRACE_BREEDERS:
        return True, _extract_origin(n) or "Unknown"

    return False, ""


def _extract_origin(name: str) -> str:
    """Extract geographic origin from a strain name."""
    name_lower = name.lower()
    origins = {
        "afghan": "Afghanistan", "afghanistan": "Afghanistan", "hindu kush": "Hindu Kush",
        "thai": "Thailand", "thailand": "Thailand",
        "mexico": "Mexico", "mexican": "Mexico",
        "colombia": "Colombia", "colombian": "Colombia", "panama": "Panama",
        "jamaica": "Jamaica", "jamaican": "Jamaica",
        "hawaii": "Hawaii", "hawaiian": "Hawaii", "maui": "Hawaii",
        "durban": "South Africa", "malawi": "Malawi", "kilimanjaro": "Tanzania",
        "kenya": "Kenya", "ethiopia": "Ethiopia", "ghana": "Ghana",
        "niger": "Nigeria", "angola": "Angola", "swazi": "Eswatini",
        "congo": "Congo", "brazil": "Brazil", "nepal": "Nepal",
        "kashmir": "Kashmir", "kerala": "India", "manali": "India",
        "pakistan": "Pakistan", "vietnam": "Vietnam", "cambodia": "Cambodia",
        "laos": "Laos", "india": "India", "acapulco": "Mexico",
        "santa marta": "Colombia",
    }
    for keyword, origin in origins.items():
        if keyword in name_lower:
            return origin
    return ""


def main():
    print("=" * 60)
    print("Deep Strain Enrichment")
    print("=" * 60)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ── 1. Load seedfinder JSON for flowering_days and seed_type ──
    print("\n1. Loading seedfinder data...")
    with open(DATA_DIR / "seedfinder_strains.json") as f:
        sf_strains = json.load(f)
    sf_index = {}
    for s in sf_strains:
        sf_index[normalize(s["name"])] = s
    print(f"   Indexed {len(sf_index):,} seedfinder strains")

    # ── 2. Load cannabis intel CSV for sativa/indica % ──
    print("\n2. Loading cannabis intelligence data...")
    ci_data = {}
    with open(DATA_DIR / "cannabis_intelligence_database.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = normalize(row["strain_name"])
            if name:
                ci_data[name] = row
    print(f"   Indexed {len(ci_data):,} cannabis intelligence strains")

    # ── 3. Get all DB strains ──
    c.execute("SELECT id, name, breeder, strain_type, genetics, is_landrace FROM strains")
    db_strains = c.fetchall()
    db_map = {row[0]: {"name": row[1], "breeder": row[2], "type": row[3],
                        "genetics": row[4], "is_landrace": row[5]} for row in db_strains}
    print(f"\n3. Processing {len(db_strains):,} DB strains...")

    # ── 4. Parse genetics strings → create StrainLinks ──
    print("\n4. Parsing genetics strings for parent links...")
    link_count = 0
    new_links = 0
    parent_pairs = set()

    # Build reverse name lookup
    name_to_id = {normalize(v["name"]): k for k, v in db_map.items()}

    for db_id, info in db_map.items():
        genetics = info["genetics"]
        if not genetics or " x " not in genetics:
            continue

        # Split on " x " — get parent names
        parts = [p.strip() for p in genetics.split(" x ") if p.strip()]
        if len(parts) < 2:
            continue

        # First two parts are the parents
        parents = parts[:2]
        for parent_name in parents:
            # Try to match to a DB strain
            parent_key = normalize(parent_name)
            if parent_key in name_to_id:
                parent_id = name_to_id[parent_key]
                pair = (parent_id, db_id)
                if pair not in parent_pairs:
                    parent_pairs.add(pair)
                    link_count += 1

    # Batch insert StrainLinks
    if parent_pairs:
        conn2 = sqlite3.connect(DB_PATH)
        c2 = conn2.cursor()
        for parent_id, child_id in parent_pairs:
            try:
                link_id = f"{parent_id[:6]}_{child_id[:6]}"
                c2.execute("""
                    INSERT OR IGNORE INTO strain_links
                    (id, parent_id, child_id, rel_type, confidence, source, notes)
                    VALUES (?, ?, ?, 'parent', 0.7, 'genetics_parse', ?)
                """, (link_id, parent_id, child_id, json.dumps({"method": "parsed from genetics string"})))
                new_links += c2.rowcount
            except Exception:
                pass
        conn2.commit()
        conn2.close()
    print(f"   Found {link_count:,} parent pairs, created {new_links:,} new StrainLinks")

    # ── 5. Import flowering_days, seed_type, strain_type ──
    print("\n5. Importing flowering_days, seed_type...")
    flowering_filled = 0
    seed_type_filled = 0
    type_filled = 0

    for db_id, info in db_map.items():
        key = normalize(info["name"])
        if key in sf_index:
            sf = sf_index[key]

            updates = []
            params = {}

            if sf.get("flowering_days"):
                updates.append("flowering_days = :flowering")
                params["flowering"] = sf["flowering_days"]

            if sf.get("seed_type"):
                updates.append("seed_type = :seed_type")
                params["seed_type"] = sf["seed_type"]

            if updates:
                params["id"] = db_id
                c.execute(f"UPDATE strains SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = :id", params)
                if c.rowcount:
                    if "flowering" in params: flowering_filled += 1
                    if "seed_type" in params: seed_type_filled += 1

    conn.commit()
    print(f"   Flowering days: {flowering_filled:,} strains")
    print(f"   Seed type: {seed_type_filled:,} strains")

    # ── 6. Import sativa/indica % from cannabis intelligence ──
    print("\n6. Importing sativa/indica percentages...")
    pct_filled = 0
    for db_id, info in db_map.items():
        key = normalize(info["name"])
        if key in ci_data:
            row = ci_data[key]
            sativa = row.get("sativa_percentage", "").strip()
            indica = row.get("indica_percentage", "").strip()
            if sativa and indica:
                try:
                    sat_pct = float(sativa)
                    ind_pct = float(indica)
                    c.execute("UPDATE strains SET sativa_pct = ?, indica_pct = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                              (sat_pct, ind_pct, db_id))
                    pct_filled += 1
                except (ValueError, TypeError):
                    pass
    conn.commit()
    print(f"   Sativa/Indica %: {pct_filled:,} strains")

    # ── 7. Landrace detection ──
    print("\n7. Detecting landrace strains...")
    landrace_found = 0
    landrace_by_name = []

    # Hardcoded known landrace strains
    DEFINITE_LANDRACES = {
        "afghani": "Afghanistan", "hindu kush": "Hindu Kush",
        "durban poison": "South Africa", "thai": "Thailand",
        "panama red": "Panama", "acapulco gold": "Mexico",
        "colombian gold": "Colombia", "colombian": "Colombia",
        "maui wowie": "Hawaii", "mexican": "Mexico",
        "jamaican": "Jamaica", "malawi": "Malawi",
        "kilimanjaro": "Tanzania", "red congo": "Congo",
        "lambs bread": "Jamaica", "lamb's bread": "Jamaica",
        "cambodian": "Cambodia", "vietnamese": "Vietnam",
        "brazilian": "Brazil", "nepalese": "Nepal",
        "pakistani": "Pakistan", "nigerian": "Nigeria",
        "ghanian": "Ghana", "ethiopian": "Ethiopia",
        "kenyan": "Kenya", "swazi": "Eswatini",
        "angola": "Angola", "laotian": "Laos",
        "indian": "India", "kashmir": "Kashmir",
        "africa": "Africa", "african": "Africa",
    }

    for db_id, info in db_map.items():
        name = info["name"]
        breeder = info["breeder"]
        stype = info["type"]
        was_landrace = info["is_landrace"]

        # Skip if already marked
        if was_landrace:
            continue

        # Check by name
        name_lower = name.lower().strip()
        origin = ""
        is_lr = False

        # Check hardcoded landrace names
        if name_lower in DEFINITE_LANDRACES:
            origin = DEFINITE_LANDRACES[name_lower]
            is_lr = True
        else:
            # Use the detection function
            is_lr, origin = is_landrace_strain(name, breeder, stype)

        if is_lr and origin:
            c.execute("UPDATE strains SET is_landrace = 1, landrace_origin = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                      (origin, db_id))
            landrace_found += 1
            landrace_by_name.append((name, origin))

    conn.commit()
    print(f"   New landrace strains marked: {landrace_found:,}")
    print(f"   Examples:")
    for name, origin in landrace_by_name[:10]:
        print(f"     {name:<35s} → {origin}")

    # ── 8. Summary ──
    c.execute("SELECT COUNT(*) FROM strains WHERE is_landrace = 1")
    total_landrace = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM strain_links")
    total_links = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM strains WHERE flowering_days IS NOT NULL")
    total_flowering = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM strains WHERE seed_type != ''")
    total_seed = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM strains WHERE sativa_pct IS NOT NULL")
    total_pct = c.fetchone()[0]

    print(f"\n{'='*60}")
    print("FINAL SUMMARY")
    print(f"{'='*60}")
    print(f"  StrainLinks:        {total_links:>8,}")
    print(f"  Landrace strains:   {total_landrace:>8,}")
    print(f"  Flowering days:     {total_flowering:>8,}")
    print(f"  Seed type:          {total_seed:>8,}")
    print(f"  Sativa/Indica %:    {total_pct:>8,}")
    print(f"{'='*60}")

    conn.close()


if __name__ == "__main__":
    main()