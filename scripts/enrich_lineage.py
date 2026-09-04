"""Enrich strains with genetic lineage data from descriptions and Leafly.

Phase 1: Extract lineage from descriptions (regex + fuzzy matching)
Phase 2: Bulk scrape Leafly for THC/CBD/terpenes/genetics/images
Phase 3: Create StrainLink records
"""
import asyncio
import json
import re
import sys
from pathlib import Path
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session, init_db, engine
from backend.models.strain import Strain
from backend.models.lineage import StrainLink

# ── Phase 1: Extract lineage from descriptions ──

# Cleaner patterns — only match known strain-like names (capitalized, 2+ chars, no stopwords)
STOPWORDS = {"the", "a", "an", "and", "for", "with", "from", "its", "their", "this", "that",
             "some", "very", "much", "more", "most", "many", "such", "like", "just", "also",
             "both", "each", "few", "other", "over", "than", "into", "about", "after", "before",
             "between", "through", "during", "because", "effects", "flavors", "aroma", "taste",
             "flavor", "smell", "scent", "buds", "bud", "plant", "plants", "strain", "strains",
             "high", "body", "mind", "cerebral", "uplifting", "relaxing", "euphoric", "creative",
             "energetic", "sleepy", "hungry", "focused", "happy"}

# Known strain-like words (common strain tokens) — helps filter
COMMON_STRAIN_TOKENS = {"kush", "og", "diesel", "haze", "blueberry", "northern", "lights",
                        "white", "widow", "skunk", "cheese", "purple", "green", "red", "gold",
                        "silver", "lemon", "orange", "cherry", "apple", "grape", "berry",
                        "pineapple", "mango", "banana", "strawberry", "blue", "dream",
                        "girl", "scout", "cookies", "fire", "alien", "gorilla", "glue",
                        "candy", "cake", "pie", "sherbet", "gelato", "zskittlez"}

CROSS_PATTERNS = [
    # "cross between X and Y"
    (r'cross\s+(?:between|of)\s+([A-Z][a-zA-Z0-9\-\']+(?:\s+[A-Z][a-zA-Z0-9\-\']+){0,4})\s+(?:and|&|/)\s+([A-Z][a-zA-Z0-9\-\']+(?:\s+[A-Z][a-zA-Z0-9\-\']+){0,4})', "cross"),
    # "blend of X and Y" or "mix of X and Y"
    (r'(?:blend|mix|combination)\s+of\s+([A-Z][a-zA-Z0-9\-\']+(?:\s+[A-Z][a-zA-Z0-9\-\']+){0,4})\s+(?:and|&|/)\s+([A-Z][a-zA-Z0-9\-\']+(?:\s+[A-Z][a-zA-Z0-9\-\']+){0,4})', "cross"),
    # "X x Y" inline in descriptions (not at start, not a date)
    (r'(?<!\d)([A-Z][a-zA-Z0-9\-\']+(?:\s+[A-Z][a-zA-Z0-9\-\']+){0,3})\s*(?:x|×)\s*([A-Z][a-zA-Z0-9\-\']+(?:\s+[A-Z][a-zA-Z0-9\-\']+){0,3})', "cross"),
    # "X genetics" — single parent mention
    (r'([A-Z][a-zA-Z0-9\-\']+(?:\s+[A-Z][a-zA-Z0-9\-\']+){0,4})\s+genetics', "genetics_source"),
    # "phenotype of X" or "cut of X"
    (r'(?:phenotype|cut|version|selection)\s+of\s+([A-Z][a-zA-Z0-9\-\']+(?:\s+[A-Z][a-zA-Z0-9\-\']+){0,4})', "phenotype"),
    # "descendant of X"
    (r'descendant\s+of\s+([A-Z][a-zA-Z0-9\-\']+(?:\s+[A-Z][a-zA-Z0-9\-\']+){0,4})', "descendant"),
    # "bred by X"
    (r'(?:bred|created|developed)\s+by\s+([A-Z][a-zA-Z0-9\-\']+(?:\s+[A-Z][a-zA-Z0-9\-\']+){0,4})', "bred_by"),
]


def is_valid_strain_name(name: str) -> bool:
    """Check if a name looks like a real strain (not a description word)."""
    name_lower = name.lower().strip()
    if len(name_lower) < 3:
        return False
    if name_lower in STOPWORDS:
        return False
    if name_lower.startswith("the "):
        return False
    # Must have at least one uppercase letter (proper noun)
    if not any(c.isupper() for c in name.strip()):
        return False
    return True


def extract_parent_names(description: str, strain_name: str) -> list[tuple[str, str, str, float]]:
    """
    Extract (parent_name, relationship, source_text, confidence) from description.
    Returns deduplicated list.
    """
    results = []
    seen = set()
    
    for pattern, rel_type in CROSS_PATTERNS:
        for match in re.finditer(pattern, description, re.IGNORECASE):
            groups = match.groups()
            source_text = match.group(0)
            
            if len(groups) == 2:
                name1, name2 = groups[0].strip(), groups[1].strip()
                for name in [name1, name2]:
                    if is_valid_strain_name(name) and name.lower() != strain_name.lower():
                        key = (name.lower(), rel_type)
                        if key not in seen:
                            seen.add(key)
                            results.append((name, rel_type, source_text, 0.7))
            elif len(groups) == 1:
                name = groups[0].strip()
                if is_valid_strain_name(name) and name.lower() != strain_name.lower():
                    key = (name.lower(), rel_type)
                    if key not in seen:
                        seen.add(key)
                        results.append((name, rel_type, source_text, 0.5))
    
    return results


# ── Phase 1b: Fuzzy match parent names to existing strains ──

async def build_strain_name_index(db: AsyncSession) -> dict[str, str]:
    """Build a name → id index with normalized names."""
    result = await db.execute(select(Strain.id, Strain.name))
    index = {}
    for row in result:
        norm = row.name.lower().strip().replace("-", "").replace(" ", "")
        index[norm] = row.id
    return index


def fuzzy_match(name: str, index: dict[str, str], threshold: float = 0.75) -> Optional[str]:
    """Fuzzy match a parent name to the strain index."""
    norm = name.lower().strip().replace("-", "").replace(" ", "")
    
    # Exact match first
    if norm in index:
        return index[norm]
    
    # Try progressively looser matching
    best_score = 0
    best_id = None
    
    for key, sid in index.items():
        score = SequenceMatcher(None, norm, key).ratio()
        if score > best_score:
            best_score = score
            best_id = sid
    
    if best_score >= threshold:
        return best_id
    
    # Try substring match
    for key, sid in index.items():
        if norm in key or key in norm:
            return sid
    
    return None


# ── Phase 1c: Check Leafly listing for known good parent names ──

# Well-known parent strains that appear frequently
KNOWN_PARENT_STRAINS = {
    "OG Kush": "og-kush", "Blue Dream": "blue-dream", "Girl Scout Cookies": "girl-scout-cookies",
    "Northern Lights": "northern-lights", "White Widow": "white-widow", "AK-47": "ak-47",
    "Sour Diesel": "sour-diesel", "Granddaddy Purple": "granddaddy-purple", "Green Crack": "green-crack",
    "Pineapple Express": "pineapple-express", "Bubba Kush": "bubba-kush", "Blueberry": "blueberry",
    "Haze": "haze", "Kush": "kush", "Diesel": "diesel", "Skunk": "skunk", "Chemdawg": "chemdawg",
    "Durban Poison": "durban-poison", "Jack Herer": "jack-herer", "Super Silver Haze": "super-silver-haze",
    "Amnesia Haze": "amnesia-haze", "Lemon Haze": "lemon-haze", "Bruce Banner": "bruce-banner",
    "Gelato": "gelato", "Zkittlez": "zkittlez", "Dosidos": "dosidos", "Gorilla Glue": "gorilla-glue",
    "Wedding Cake": "wedding-cake", "Runtz": "runtz", "Ice Cream Cake": "ice-cream-cake",
    "MAC": "mac", "Chemdog": "chemdog", "GDP": "granddaddy-purple",
    "Tangie": "tangie", "Cinderella 99": "cinderella-99", "Blue Cheese": "blue-cheese",
}


async def extract_lineage():
    """Phase 1: Extract lineage from descriptions, create StrainLink records."""
    await init_db()
    async with async_session() as db:
        # Build index
        index = await build_strain_name_index(db)
        print(f"Strain name index built: {len(index)} entries")
        
        # Get all strains with descriptions
        result = await db.execute(select(Strain).where(Strain.description != ''))
        strains = result.scalars().all()
        print(f"Processing {len(strains)} strains with descriptions...")
        
        links_created = 0
        links_skipped = 0
        
        for s in strains:
            parents = extract_parent_names(s.description, s.name)
            
            for parent_name, rel_type, source_text, conf in parents:
                # Try fuzzy match to existing strain
                parent_id = fuzzy_match(parent_name, index)
                
                if not parent_id:
                    # Try known parent strains
                    for known_name, known_slug in KNOWN_PARENT_STRAINS.items():
                        if parent_name.lower() in known_name.lower() or known_name.lower() in parent_name.lower():
                            # Try to find in DB by slug-like name
                            result2 = await db.execute(
                                select(Strain).where(Strain.name.ilike(f"%{known_name}%")).limit(1)
                            )
                            s2 = result2.scalar_one_or_none()
                            if s2:
                                parent_id = s2.id
                                break
                
                if not parent_id:
                    links_skipped += 1
                    continue
                
                if parent_id == s.id:
                    continue  # Skip self-references
                
                # Check if link already exists
                existing = await db.execute(
                    select(StrainLink).where(
                        StrainLink.parent_id == parent_id,
                        StrainLink.child_id == s.id,
                        StrainLink.rel_type == rel_type,
                    )
                )
                if existing.scalar_one_or_none():
                    links_skipped += 1
                    continue
                
                link = StrainLink(
                    parent_id=parent_id,
                    child_id=s.id,
                    rel_type=rel_type,
                    confidence=conf,
                    source="description_extract",
                    notes=source_text[:200],
                )
                db.add(link)
                links_created += 1
                
                # Flush in batches
                if links_created % 100 == 0:
                    await db.flush()
                    print(f"  {links_created} links created...")
        
        await db.commit()
        print(f"\nPhase 1 complete: {links_created} links created, {links_skipped} skipped (unmatched parents)")


if __name__ == "__main__":
    asyncio.run(extract_lineage())