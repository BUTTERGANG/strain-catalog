"""Leafly scraper — enrich strains with terpenes, THC/CBD, photos; scrape dispensary data.

Uses browser-use (Playwright) to extract __NEXT_DATA__ from Leafly pages.
No API key needed — Leafly server-renders data.
"""
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LEAFLY_BASE = "https://www.leafly.com"


@dataclass
class LeaflyStrain:
    name: str
    slug: str
    strain_type: str  # indica, sativa, hybrid
    rating: float = 0.0
    review_count: int = 0
    thc_min: Optional[float] = None
    thc_max: Optional[float] = None
    cbd_min: Optional[float] = None
    cbd_max: Optional[float] = None
    effects: list = field(default_factory=list)
    flavors: list = field(default_factory=list)
    terpenes: list = field(default_factory=list)  # [{"name":"myrcene","percentage":0.5}]
    description: str = ""
    image_url: str = ""
    genetics: str = ""
    top_effect: str = ""
    top_terpene: str = ""
    source_url: str = ""


@dataclass
class LeaflyDispensary:
    name: str
    slug: str
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    phone: str = ""
    website: str = ""
    rating: Optional[float] = None
    review_count: int = 0
    license_type: str = "recreational"
    delivery_available: bool = False
    hours: dict = field(default_factory=dict)
    source_url: str = ""


async def fetch_strain_list(page: int = 1) -> dict:
    """Fetch strain listing page from Leafly — returns __NEXT_DATA__."""
    url = f"{LEAFLY_BASE}/strains?page={page}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        if resp.status_code != 200:
            print(f"  [ERROR] page {page}: HTTP {resp.status_code}")
            return {}
        html = resp.text

    # Extract __NEXT_DATA__
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        print(f"  [WARN] No __NEXT_DATA__ on page {page}")
        return {}
    return json.loads(match.group(1))


def parse_strains_from_next_data(data: dict) -> list[LeaflyStrain]:
    """Extract strain list from __NEXT_DATA__ structure."""
    strains = []
    try:
        # Leafly's __NEXT_DATA__ structure varies — probe common paths
        props = data.get("props", {})
        page_props = props.get("pageProps", {})
        
        # Path: data > strains (current Leafly structure)
        data_section = page_props.get("data", {})
        if isinstance(data_section, dict):
            raw_strains = data_section.get("strains", [])
        
        # Fallback: browsePage > strains (older structure)
        if not raw_strains:
            browse = page_props.get("browsePage", {})
            raw_strains = browse.get("strains", [])
        
        for s in raw_strains:
            name = s.get("name", "")
            slug = s.get("slug", "")
            if not name or not slug:
                continue
            
            # New Leafly structure uses "category"/"phenotype" for type
            strain_type = (s.get("category") or s.get("phenotype", "hybrid") or "hybrid").lower().strip()
            if strain_type not in ("indica", "sativa", "hybrid"):
                strain_type = "hybrid"
            
            # Rating uses averageRating (float) not rating
            rating = float(s.get("averageRating", 0) or 0)
            review_count = int(s.get("reviewCount", 0) or 0)
            
            # THC is a single average number (e.g. 21), not a range
            thc_val = s.get("thc")
            thc_min = thc_max = None
            if thc_val is not None:
                try:
                    thc_val = float(thc_val)
                    thc_min = thc_val - 3
                    thc_max = thc_val + 3
                except (ValueError, TypeError):
                    pass
            
            # Cannabinoids (dict with cbd, cbc, thcv, etc.)
            cann = s.get("cannabinoids", {})
            if isinstance(cann, dict):
                cbd_data = cann.get("cbd", {})
                if isinstance(cbd_data, dict):
                    try:
                        cbd_min = float(cbd_data.get("percentile25") or 0)
                        cbd_max = float(cbd_data.get("percentile75") or cbd_data.get("percentile50") or 0)
                    except (ValueError, TypeError):
                        cbd_min = cbd_max = None
                else:
                    cbd_min = cbd_max = None
            else:
                cbd_min = cbd_max = None
            
            # Effects: dict like {"creative": {"name":"Creative","score":1.98,...}, "euphoric": {...}}
            effects_raw = s.get("effects", {})
            effects = []
            if isinstance(effects_raw, dict):
                for e_slug, e in effects_raw.items():
                    if isinstance(e, dict):
                        effects.append(e.get("name", e_slug))
                    else:
                        effects.append(e_slug)
            elif isinstance(effects_raw, list):
                for e in effects_raw:
                    if isinstance(e, dict):
                        effects.append(e.get("name", ""))
                    elif isinstance(e, str):
                        effects.append(e)
            
            # Flavors — not directly available in listing data
            flavors = []
            
            # Terpenes: dict like {"myrcene": {"name":"myrcene","score":0.7,...}, "limonene": {...}}
            terpenes = []
            terps_raw = s.get("terps", {})
            if isinstance(terps_raw, dict):
                total_score = sum(float(t.get("score", 0) or 0) for t in terps_raw.values() if isinstance(t, dict))
                for t_slug, t in terps_raw.items():
                    if isinstance(t, dict):
                        score = float(t.get("score", 0) or 0)
                        percentage = round(score / total_score * 100, 1) if total_score > 0 else 0
                        terpenes.append({
                            "name": t.get("name", t_slug).lower(),
                            "percentage": percentage,
                        })
            elif isinstance(terps_raw, list):
                for t in terps_raw:
                    if isinstance(t, dict):
                        terpenes.append({
                            "name": t.get("name", "").lower(),
                            "percentage": float(t.get("percentage", 0) or 0),
                        })
            
            # Image
            image_url = s.get("nugImage", "") or s.get("flowerImageSvg", "")
            
            # Top terpene/effect
            top_terpene = s.get("strainTopTerp", "")
            top_effect = s.get("topEffect", "")
            
            strains.append(LeaflyStrain(
                name=name,
                slug=slug,
                strain_type=strain_type,
                rating=rating,
                review_count=review_count,
                thc_min=thc_min,
                thc_max=thc_max,
                cbd_min=cbd_min,
                cbd_max=cbd_max,
                effects=effects,
                flavors=flavors,
                terpenes=terpenes,
                image_url=image_url,
                top_effect=top_effect,
                top_terpene=top_terpene,
                source_url=f"{LEAFLY_BASE}/strains/{slug}",
            ))
    except Exception as e:
        print(f"  [ERROR] Parsing strains: {e}")
    
    return strains


async def scrape_strain_detail(slug: str) -> Optional[LeaflyStrain]:
    """Scrape individual strain detail page for full data."""
    url = f"{LEAFLY_BASE}/strains/{slug}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        if resp.status_code != 200:
            return None
        html = resp.text

    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        return None
    
    data = json.loads(match.group(1))
    try:
        props = data.get("props", {}).get("pageProps", {})
        
        # Path 1: strainDetail
        sd = props.get("strainDetail", {}) or props.get("strain", {})
        if not sd:
            # Try props directly
            sd = props
        
        name = sd.get("name", slug)
        strain_type = sd.get("category", "hybrid") or "hybrid"
        strain_type = strain_type.lower().strip()
        if strain_type not in ("indica", "sativa", "hybrid"):
            strain_type = "hybrid"
        
        # THC/CBD
        thc = sd.get("thc", sd.get("thcRange", ""))
        cbd = sd.get("cbd", sd.get("cbdRange", ""))
        
        thc_min = thc_max = None
        if isinstance(thc, str):
            nums = re.findall(r"[\d.]+", thc.replace("%", ""))
            if len(nums) >= 2:
                thc_min, thc_max = float(nums[0]), float(nums[1])
            elif len(nums) == 1:
                thc_min = float(nums[0])
        elif isinstance(thc, dict):
            thc_min = thc.get("min") or thc.get("low")
            thc_max = thc.get("max") or thc.get("high")
        
        cbd_min = cbd_max = None
        if isinstance(cbd, str):
            nums = re.findall(r"[\d.]+", cbd.replace("%", ""))
            if len(nums) >= 2:
                cbd_min, cbd_max = float(nums[0]), float(nums[1])
        elif isinstance(cbd, dict):
            cbd_min = cbd.get("min") or cbd.get("low")
            cbd_max = cbd.get("max") or cbd.get("high")
        
        # Effects with percentages
        effects_raw = sd.get("effects", [])
        effects = []
        for e in effects_raw:
            if isinstance(e, dict):
                effects.append(e.get("name", ""))
            elif isinstance(e, str):
                effects.append(e)
        
        # Flavors
        flavors_raw = sd.get("flavors", [])
        flavors = []
        for f in flavors_raw:
            if isinstance(f, dict):
                flavors.append(f.get("name", ""))
            elif isinstance(f, str):
                flavors.append(f)
        
        # Terpenes (from detail page — full profile)
        terpenes_raw = sd.get("terpenes", [])
        terpenes = []
        for t in terpenes_raw:
            if isinstance(t, dict):
                terpenes.append({
                    "name": t.get("name", t.get("slug", "")),
                    "percentage": float(t.get("percentage", t.get("value", 0))),
                })
        
        return LeaflyStrain(
            name=name,
            slug=slug,
            strain_type=strain_type,
            rating=float(sd.get("rating", 0) or 0),
            review_count=int(sd.get("reviewCount", 0) or 0),
            thc_min=float(thc_min) if thc_min else None,
            thc_max=float(thc_max) if thc_max else None,
            cbd_min=float(cbd_min) if cbd_min else None,
            cbd_max=float(cbd_max) if cbd_max else None,
            effects=effects,
            flavors=flavors,
            terpenes=terpenes,
            description=sd.get("description", ""),
            image_url=sd.get("imageUrl", ""),
            genetics=sd.get("genetics", sd.get("lineage", "")),
            top_effect=sd.get("topEffect", ""),
            top_terpene=sd.get("topTerpene", ""),
            source_url=url,
        )
    except Exception as e:
        print(f"  [ERROR] Parsing detail for {slug}: {e}")
        return None


async def scrape_strains(max_strains: int = 100, include_details: bool = False) -> list[LeaflyStrain]:
    """Scrape strains from Leafly listing pages."""
    all_strains = []
    page = 1
    while len(all_strains) < max_strains:
        print(f"Scraping page {page}...")
        data = await fetch_strain_list(page)
        if not data:
            break
        
        strains = parse_strains_from_next_data(data)
        if not strains:
            print(f"  No strains found on page {page}, stopping")
            break
        
        all_strains.extend(strains)
        print(f"  Got {len(strains)} strains (total: {len(all_strains)})")
        page += 1
        
        # Rate limiting
        await asyncio.sleep(0.5)
    
    # Detail enrichment
    if include_details and all_strains:
        print(f"\nEnriching {len(all_strains)} strains with detail data...")
        enriched = []
        for i, s in enumerate(all_strains[:max_strains]):
            if i % 10 == 0:
                print(f"  Detail {i}/{min(len(all_strains), max_strains)}")
            detail = await scrape_strain_detail(s.slug)
            enriched.append(detail or s)
            await asyncio.sleep(0.3)
        all_strains = enriched
    
    return all_strains[:max_strains]


async def scrape_dispensary_state(state: str, max_stores: int = 5) -> list[LeaflyDispensary]:
    """Scrape dispensary listings for a given US state."""
    url = f"{LEAFLY_BASE}/dispensaries/state/{state.lower()}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        })
        if resp.status_code != 200:
            print(f"  State {state}: HTTP {resp.status_code}")
            return []
        html = resp.text
    
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        print(f"  State {state}: No __NEXT_DATA__")
        return []
    
    data = json.loads(match.group(1))
    dispensaries = []
    
    try:
        props = data.get("props", {}).get("pageProps", {})
        
        # New Leafly structure: stores in storeLocatorResults.data.organicStores + sponsoredStores
        slr = props.get("storeLocatorResults", {})
        slr_data = slr.get("data", {}) if isinstance(slr, dict) else {}
        organic = slr_data.get("organicStores", []) if isinstance(slr_data, dict) else []
        sponsored = slr_data.get("sponsoredStores", []) if isinstance(slr_data, dict) else []
        stores = organic + sponsored
        
        # Fallback: old structure
        if not stores:
            stores = props.get("dispensaries", []) or props.get("stores", [])
        
        for s in stores[:max_stores]:
            name = s.get("name", "")
            slug = s.get("slug", "")
            if not name:
                continue
            
            # Address is nested under "address" dict in new structure
            addr = s.get("address", {})
            if isinstance(addr, dict):
                address = addr.get("address1", "") or addr.get("streetAddress", "")
                city = addr.get("city", "") or s.get("city", "")
                state_code = addr.get("state", state.upper()) or state.upper()
                zip_code = addr.get("zip", "") or s.get("zip", s.get("postalCode", ""))
                lat = float(addr.get("lat", 0)) if addr.get("lat") else None
                lon = float(addr.get("lon", addr.get("lng", 0))) if addr.get("lon") or addr.get("lng") else None
            else:
                address = s.get("address", s.get("streetAddress", ""))
                city = s.get("city", "")
                state_code = state.upper()
                zip_code = s.get("zip", s.get("postalCode", ""))
                lat = float(s["lat"]) if s.get("lat") else None
                lon = float(s["lon"] or s.get("lng")) if s.get("lon") or s.get("lng") else None
            
            hours_raw = s.get("hours", {})
            if isinstance(hours_raw, dict):
                hours = {k.lower(): v for k, v in hours_raw.items()}
            else:
                hours = {}
            
            # Map license_type from mainTag (e.g. "MED & REC", "REC", "MED")
            main_tag = s.get("mainTag") or ""
            if "REC" in main_tag.upper() or "recreational" in main_tag.lower():
                license_type = "recreational"
            elif "MED" in main_tag.upper():
                license_type = "medical"
            else:
                license_type = "recreational"
            
            # Path may be "/dispensary-info/<slug>" or "https://..."
            path = s.get("path", f"/dispensary-info/{slug}")
            source_url = f"{LEAFLY_BASE}{path}" if path.startswith("/") else path
            
            dispensaries.append(LeaflyDispensary(
                name=name,
                slug=slug,
                address=address,
                city=city,
                state=state_code,
                zip_code=zip_code,
                lat=lat,
                lon=lon,
                phone=s.get("phone") or "",
                website=s.get("website") or "",
                rating=float(s.get("reviewRating", 0) or 0) if s.get("reviewRating") else None,
                review_count=int(s.get("reviewCount", 0) or 0),
                license_type=license_type,
                delivery_available=bool(s.get("configurations", {}).get("deliveryEnabled", False)) if isinstance(s.get("configurations"), dict) else False,
                hours=hours,
                source_url=source_url,
            ))
    except Exception as e:
        print(f"  [ERROR] Parsing dispensaries: {e}")
    
    print(f"  Found {len(dispensaries)} dispensaries in {state}")
    return dispensaries


async def main():
    """CLI entry point."""
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    
    if command == "strains":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 100
        details = "--details" in sys.argv
        strains = await scrape_strains(max_strains=count, include_details=details)
        output = DATA_DIR / f"leafly_strains_{len(strains)}.json"
        with open(output, "w") as f:
            json.dump([asdict(s) for s in strains], f, indent=2)
        print(f"\nSaved {len(strains)} strains to {output}")
    
    elif command == "dispensaries":
        state = sys.argv[2] if len(sys.argv) > 2 else "california"
        count = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        dispos = await scrape_dispensary_state(state, max_stores=count)
        output = DATA_DIR / f"leafly_dispos_{state}_{len(dispos)}.json"
        with open(output, "w") as f:
            json.dump([asdict(d) for d in dispos], f, indent=2)
        print(f"\nSaved {len(dispos)} dispensaries to {output}")
    
    elif command == "detail":
        slug = sys.argv[2] if len(sys.argv) > 2 else "blue-dream"
        strain = await scrape_strain_detail(slug)
        if strain:
            print(json.dumps(asdict(strain), indent=2))
        else:
            print(f"Failed to scrape {slug}")
    
    else:
        print("""Usage:
  python scripts/scrape_leafly.py strains [count] [--details]
  python scripts/scrape_leafly.py dispensaries <state> [count]
  python scripts/scrape_leafly.py detail <strain-slug>
  
Examples:
  python scripts/scrape_leafly.py strains 50 --details
  python scripts/scrape_leafly.py dispensaries california 10
  python scripts/scrape_leafly.py detail blue-dream
""")


if __name__ == "__main__":
    asyncio.run(main())