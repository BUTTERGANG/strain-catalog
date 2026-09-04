"""Audit genetics data in existing strains and extract from descriptions."""
import asyncio
import re
import json
from pathlib import Path
from sqlalchemy import select, func
from backend.database import async_session, init_db
from backend.models.strain import Strain

GENETIC_PATTERNS = [
    # "cross of X and Y", "cross between X and Y", "blend of X and Y"
    (r'(?:cross|blend|mix|hybrid|combination)\s+(?:between|of|ing)\s+([A-Z][^\s,;.()]+(?:\s+[A-Z][^\s,;.()]+)*)\s+(?:and|x|&|/)\s+([A-Z][^\s,;.()]+(?:\s+[A-Z][^\s,;.()]+)*)', "cross_of"),
    # "X genetics crossed with Y", "X x Y genetics"
    (r'([A-Z][^\s,;.()]+(?:\s+[A-Z][^\s,;.()]+)*)\s+(?:genetics\s+(?:crossed\s+with|x\s*/\s*))\s+([A-Z][^\s,;.()]+(?:\s+[A-Z][^\s,;.()]+)*)', "genetics_of"),
    # "bred by X", "bred from X"
    (r'(?:bred\s+(?:by|from))\s+([A-Z][^\s,;.()]+(?:\s+[A-Z][^\s,;.()]+)*)', "bred_by"),
    # "descendant of X", "derived from X", "selected from X"
    (r'(?:descendant|derived|selected)\s+(?:of|from)\s+([A-Z][^\s,;.()]+(?:\s+[A-Z][^\s,;.()]+)*)', "descendant_of"),
    # "X cut of Y"
    (r'([A-Z][^\s,;.()]+(?:\s+[A-Z][^\s,;.()]+)*)\s+cut\s+of\s+([A-Z][^\s,;.()]+(?:\s+[A-Z][^\s,;.()]+)*)', "cut_of"),
    # "X aka Y", "X also known as Y"
    (r'([A-Z][^\s,;.()]+(?:\s+[A-Z][^\s,;.()]+)*)\s+(?:aka|also\s+known\s+as)\s+([A-Z][^\s,;.()]+(?:\s+[A-Z][^\s,;.()]+)*)', "aka"),
    # "X phenotype of Y"
    (r'(?:phenotype|cut|version)\s+of\s+([A-Z][^\s,;.()]+(?:\s+[A-Z][^\s,;.()]+)*)', "phenotype_of"),
    # "X from Y genetics"
    (r'([A-Z][^\s,;.()]+(?:\s+[A-Z][^\s,;.()]+)*)\s+from\s+([A-Z][^\s,;.()]+(?:\s+[A-Z][^\s,;.()]+)*)\s+genetics', "from_genetics"),
]

NAME_CROSS_PATTERN = re.compile(r'^([A-Za-z0-9\-\'\s\.]+?)\s*(?:x|X|\/)\s*([A-Za-z0-9\-\'\s\.]+)$')


async def audit():
    await init_db()
    async with async_session() as db:
        # 1. Full catalog stats
        total = (await db.execute(select(func.count()).select_from(Strain))).scalar() or 0
        print(f"Total strains: {total}")
        
        # 2. Extract genetics from descriptions
        results = await db.execute(select(Strain))
        strains = results.scalars().all()
        
        found_in_desc = 0
        found_in_name = 0
        all_parents = set()
        lineage_edges = []  # (child_name, parent_name, relationship_type)
        
        for s in strains:
            desc = s.description or ""
            name = s.name or ""
            
            # Check name-based crosses
            nm = NAME_CROSS_PATTERN.match(name)
            if nm:
                found_in_name += 1
                p1, p2 = nm.group(1).strip(), nm.group(2).strip()
                all_parents.add(p1)
                all_parents.add(p2)
                lineage_edges.append((name, p1, "parent"))
                lineage_edges.append((name, p2, "parent"))
            
            # Check description-based genetics
            for pattern, ptype in GENETIC_PATTERNS:
                matches = re.findall(pattern, desc, re.IGNORECASE)
                if not matches:
                    continue
                found_in_desc += 1
                for m in matches:
                    if isinstance(m, tuple):
                        for p in m:
                            p_stripped = p.strip()
                            if p_stripped:
                                all_parents.add(p_stripped)
                        if len(m) >= 2:
                            lineage_edges.append((name, m[0].strip(), ptype))
                            lineage_edges.append((name, m[1].strip(), ptype))
                    else:
                        p_stripped = m.strip()
                        if p_stripped:
                            all_parents.add(p_stripped)
                            lineage_edges.append((name, p_stripped, ptype))
                break  # first match only
            
            # Also look for "Name x Name" patterns inside descriptions
            inline_cross = re.findall(r'([A-Z][^\s,;.()]+(?:\s+[A-Z][^\s,;.()]+)*)\s+(?:crossed\s+with|\bx\b)\s+([A-Z][^\s,;.()]+(?:\s+[A-Z][^\s,;.()]+)*)', desc, re.IGNORECASE)
            for p1, p2 in inline_cross:
                all_parents.add(p1.strip())
                all_parents.add(p2.strip())
        
        # 3. Find strains that ARE the parents (for linking)
        parent_strains = set()
        for p_name in all_parents:
            # Normalize: lowercase match
            norm = p_name.lower().strip()
            result = await db.execute(
                select(Strain).where(Strain.name.ilike(f"%{norm}%")).limit(1)
            )
            if result.scalar_one_or_none():
                parent_strains.add(p_name)
        
        print(f"\n=== Genetics Extraction Results ===")
        print(f"Strains with genetic info in descriptions: {found_in_desc}")
        print(f"Strains with cross naming patterns: {found_in_name}")
        print(f"Unique parent strain names referenced: {len(all_parents)}")
        print(f"Parents that exist in our catalog: {len(parent_strains)}")
        print(f"Total lineage edges discovered: {len(lineage_edges)}")
        
        print(f"\n=== Sample lineage edges ===")
        for child, parent, rel_type in lineage_edges[:30]:
            in_catalog = "✓" if parent.lower() in [p.lower() for p in parent_strains] else "✗"
            print(f"  {child} ← {parent} [{rel_type}] {in_catalog}")
        
        if parent_strains:
            print(f"\n=== Sample parent strains in catalog ===")
            for p in sorted(list(parent_strains))[:20]:
                print(f"  {p}")
        
        # 4. Strains missing key data
        missing_effects = (await db.execute(select(func.count()).select_from(Strain).where(Strain.effects == '[]'))).scalar() or 0
        missing_flavors = (await db.execute(select(func.count()).select_from(Strain).where(Strain.flavors == '[]'))).scalar() or 0
        missing_desc = (await db.execute(select(func.count()).select_from(Strain).where(Strain.description == ''))).scalar() or 0
        print(f"\n=== Data gaps ===")
        print(f"Missing effects: {missing_effects}")
        print(f"Missing flavors: {missing_flavors}")
        print(f"Missing descriptions: {missing_desc}")


if __name__ == "__main__":
    asyncio.run(audit())