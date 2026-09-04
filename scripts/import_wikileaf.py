"""Import Wikileaf strain data into WEED database.

Usage: PYTHONPATH=$PWD .venv/bin/python scripts/import_wikileaf.py
"""
import asyncio
import csv
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

# --- Ensure we can import from backend ---
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import async_session, engine, Base
from backend.models.strain import Strain
from backend.models.lineage import StrainLink

# === TEXT-TO-NUMERIC MAPPINGS ===
THC_CBD_MAP = {
    "very high": (20.0, 25.0),
    "high": (15.0, 20.0),
    "normal": (10.0, 15.0),
    "low": (5.0, 10.0),
    "very low": (0.0, 5.0),
}

SATIVA_INDICA_MAP = {
    "very high": (80.0, 100.0),
    "high": (60.0, 80.0),
    "normal": (40.0, 60.0),
    "low": (20.0, 40.0),
    "very low": (0.0, 20.0),
}

# === HTML CLEANING ===
def clean_html(html_text: str) -> str:
    """Strip HTML tags and return clean text."""
    if not html_text or not html_text.strip():
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def parse_numeric_range(value_text: str, mapping: dict) -> tuple:
    """Parse a text value like 'Normal' or '<p>Normal</p>' into (min, max) or (None, None)."""
    if not value_text or not value_text.strip():
        return (None, None)
    clean = clean_html(value_text).lower().strip()
    if clean in mapping:
        return mapping[clean]
    return (None, None)


# === LINEAGE PARSING ===
def extract_lineage(info_text: str, strain_name: str, all_strain_names: set) -> list:
    """Parse info HTML for genetic lineage clues.

    Returns list of (parent_name, child_name, rel_type, confidence, notes) tuples.
    """
    if not info_text or not info_text.strip():
        return []

    clean_text = clean_html(info_text)
    results = []

    # Patterns that indicate parent-child relationships
    patterns = [
        # "cross between X and Y" / "cross of X and Y"
        (r"(?:cross|crossbreed|hybrid)\s+(?:between|of)?\s*([A-Z][A-Za-z0-9\s'-]+?)\s+(?:and|/|×)\s+([A-Z][A-Za-z0-9\s'-]+?)", 0.9, "parent"),
        # "X crossed with Y"
        (r"([A-Z][A-Za-z0-9\s'-]+?)\s+crossed\s+with\s+([A-Z][A-Za-z0-9\s'-]+?)", 0.8, "parent"),
        # "combination of X and Y"
        (r"(?:combination|blend|mix)\s+of\s+([A-Z][A-Za-z0-9\s'-]+?)\s+(?:and|/|×)\s+([A-Z][A-Za-z0-9\s'-]+?)", 0.7, "parent"),
        # "descended from X" / "descendant of X"
        (r"(?:descended|descendant|derived)\s+(?:from|of)\s+([A-Z][A-Za-z0-9\s'-]+?)", 0.6, "descendant"),
        # "bred by [Breeder Name]" — we keep as note, link to the strain itself
    ]

    for pattern, confidence, rel_type in patterns:
        for match in re.finditer(pattern, clean_text, re.IGNORECASE):
            groups = match.groups()
            if len(groups) == 2:
                p1, p2 = groups[0].strip(), groups[1].strip()
                # Check if these look like strain names (not generic words)
                # Filter out common words that match uppercase
                skip_words = {"the", "a", "an", "its", "this", "that", "with", "from", "both", "each", "many", "some", "most", "these", "those", "other", "different", "several", "various", "numerous", "multiple", "countless"}
                valid_parents = []
                for p in [p1, p2]:
                    p_clean = p.strip().lower()
                    if p_clean not in skip_words and len(p_clean) > 2:
                        valid_parents.append(p.strip())
                if len(valid_parents) >= 1:
                    # Try to match parent names against known strain names
                    for parent_name in valid_parents:
                        # Check if parent_name is in our known strains set (fuzzy)
                        parent_lower = parent_name.lower().strip()
                        matched = None
                        # Exact or prefix match against known names
                        for known_name in all_strain_names:
                            kn_lower = known_name.lower().strip()
                            if parent_lower == kn_lower:
                                matched = known_name
                                break
                        if matched:
                            results.append((matched, strain_name, rel_type, confidence, f"Extracted from description: '{match.group(0)}'"))
                        else:
                            # Try substring
                            for known_name in all_strain_names:
                                kn_lower = known_name.lower().strip()
                                if parent_lower in kn_lower or kn_lower in parent_lower:
                                    results.append((known_name, strain_name, rel_type, confidence * 0.8, f"Fuzzy match from description: '{match.group(0)}'"))
                                    break

    return results


async def main():
    csv_path = Path(__file__).resolve().parent.parent / "data" / "wikileaf_strains.csv"
    print(f"Reading CSV: {csv_path}")
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Total rows in CSV: {len(rows)}")

    # Build a set of all strain names from CSV for lineage matching
    csv_strain_names = set()
    for row in rows:
        name = row.get("strain", "").strip()
        if name:
            csv_strain_names.add(name)

    # Track statistics
    imported = 0
    updated = 0
    lineage_links = 0
    skipped = 0

    # Use a single session for all operations
    async with async_session() as session:
        # Pre-load all existing strain names (lower) and their IDs
        result = await session.execute(
            select(Strain.name, Strain.id, Strain.description, Strain.image_url,
                   Strain.thc_min, Strain.thc_max, Strain.cbd_min, Strain.cbd_max,
                   Strain.source)
        )
        existing_strains = {}
        for row in result:
            existing_strains[row.name.lower()] = {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "image_url": row.image_url,
                "thc_min": row.thc_min,
                "thc_max": row.thc_max,
                "cbd_min": row.cbd_min,
                "cbd_max": row.cbd_max,
                "source": row.source,
            }

        print(f"Existing strains in DB: {len(existing_strains)}")

        # Also load existing lineage links to avoid duplicates
        existing_links_result = await session.execute(
            select(StrainLink.parent_id, StrainLink.child_id, StrainLink.rel_type)
        )
        existing_links = set()
        for row in existing_links_result:
            existing_links.add((row.parent_id, row.child_id, row.rel_type))

        print(f"Existing lineage links: {len(existing_links)}")

        name_to_id = {}
        for name_lower, info in existing_strains.items():
            name_to_id[name_lower] = info["id"]

        # Pre-load CSV names to ID mapping for new strains (will be filled as we go)
        # We'll build this incrementally

        # Process each strain
        for i, row in enumerate(rows):
            name = row.get("strain", "").strip()
            if not name:
                skipped += 1
                continue

            name_lower = name.lower()

            # Clean fields
            info_clean = clean_html(row.get("info", ""))
            more_info_clean = clean_html(row.get("more_info", ""))
            description = info_clean or more_info_clean or ""

            image_url = row.get("logo", "").strip() or ""
            if image_url.startswith("//"):
                image_url = "https:" + image_url

            # Parse numeric values
            thc_min, thc_max = parse_numeric_range(row.get("THC", ""), THC_CBD_MAP)
            cbd_min, cbd_max = parse_numeric_range(row.get("CBD", ""), THC_CBD_MAP)  # Same mapping for CBD
            sat_min, sat_max = parse_numeric_range(row.get("Sativa", ""), SATIVA_INDICA_MAP)
            ind_min, ind_max = parse_numeric_range(row.get("Indica", ""), SATIVA_INDICA_MAP)

            # Determine strain type
            if sat_min is not None and ind_min is not None:
                sat_val = (sat_min + sat_max) / 2 if sat_max else sat_min
                ind_val = (ind_min + ind_max) / 2 if ind_max else ind_min
                if sat_val >= 60:
                    strain_type = "sativa"
                elif ind_val >= 60:
                    strain_type = "indica"
                else:
                    strain_type = "hybrid"
            else:
                strain_type = "hybrid"

            # --- Check if strain exists ---
            if name_lower in existing_strains:
                # EXISTING — update empty fields
                existing = existing_strains[name_lower]
                strain_id = existing["id"]
                update_data = {}
                source = existing["source"]

                if not existing["description"] and description:
                    update_data["description"] = description
                if not existing["image_url"] and image_url:
                    update_data["image_url"] = image_url
                if existing["thc_min"] is None and thc_min is not None:
                    update_data["thc_min"] = thc_min
                if existing["thc_max"] is None and thc_max is not None:
                    update_data["thc_max"] = thc_max
                if existing["cbd_min"] is None and cbd_min is not None:
                    update_data["cbd_min"] = cbd_min
                if existing["cbd_max"] is None and cbd_max is not None:
                    update_data["cbd_max"] = cbd_max

                if update_data:
                    await session.execute(
                        Strain.__table__.update().where(Strain.id == strain_id).values(**update_data)
                    )
                    updated += 1

                # Add genetics from lineage parsing
                lineage_info = extract_lineage(row.get("info", ""), name, csv_strain_names)
                if lineage_info:
                    # We need to convert child name to ID
                    child_id = strain_id
                    for parent_name, child_name, rel_type, confidence, notes in lineage_info:
                        parent_lower = parent_name.lower().strip()
                        parent_id = name_to_id.get(parent_lower)
                        if parent_id and parent_id != child_id:
                            link_key = (parent_id, child_id, rel_type)
                            if link_key not in existing_links:
                                # Check if parent strain exists by name
                                session.add(StrainLink(
                                    parent_id=parent_id,
                                    child_id=child_id,
                                    rel_type=rel_type,
                                    confidence=confidence,
                                    source="wikileaf",
                                    notes=notes,
                                ))
                                existing_links.add(link_key)
                                lineage_links += 1
            else:
                # NEW — create strain record
                strain = Strain(
                    name=name,
                    strain_type=strain_type,
                    description=description,
                    image_url=image_url,
                    thc_min=thc_min,
                    thc_max=thc_max,
                    cbd_min=cbd_min,
                    cbd_max=cbd_max,
                    source="wikileaf",
                )
                session.add(strain)
                # Flush to get the ID
                await session.flush()
                strain_id = strain.id
                imported += 1

                # Track the new strain
                name_to_id[name_lower] = strain_id
                existing_strains[name_lower] = {
                    "id": strain_id,
                    "name": name,
                    "description": description,
                    "image_url": image_url,
                    "thc_min": thc_min,
                    "thc_max": thc_max,
                    "cbd_min": cbd_min,
                    "cbd_max": cbd_max,
                    "source": "wikileaf",
                }

                # Extract lineage from description
                lineage_info = extract_lineage(row.get("info", ""), name, csv_strain_names)
                if lineage_info:
                    child_id = strain_id
                    for parent_name, child_name, rel_type, confidence, notes in lineage_info:
                        parent_lower = parent_name.lower().strip()
                        parent_id = name_to_id.get(parent_lower)
                        if parent_id and parent_id != child_id:
                            link_key = (parent_id, child_id, rel_type)
                            if link_key not in existing_links:
                                check = await session.execute(
                                    select(StrainLink).where(
                                        StrainLink.parent_id == parent_id,
                                        StrainLink.child_id == child_id,
                                        StrainLink.rel_type == rel_type,
                                    )
                                )
                                if not check.scalar_one_or_none():
                                    session.add(StrainLink(
                                        parent_id=parent_id,
                                        child_id=child_id,
                                        rel_type=rel_type,
                                        confidence=confidence,
                                        source="wikileaf",
                                        notes=notes,
                                    ))
                                    existing_links.add(link_key)
                                    lineage_links += 1

            if (i + 1) % 500 == 0:
                print(f"  Progress: {i + 1}/{len(rows)} — imported={imported}, updated={updated}, links={lineage_links}")

        # Commit all changes
        await session.commit()
        print()

    # Final report
    total_after = imported + len(existing_strains)
    report = {
        "imported": imported,
        "updated": updated,
        "lineage_links": lineage_links,
        "total_strains": total_after,
    }
    print(json.dumps(report, indent=2))
    print(f"\nSummary: {imported} new strains imported, {updated} existing updated, {lineage_links} lineage links created.")
    print(f"Total strains in DB now: {total_after}")


if __name__ == "__main__":
    asyncio.run(main())