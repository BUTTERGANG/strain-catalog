"""Pages router — home, map, and static pages with modern image-first design."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.models.strain import Strain
from backend.models.review import Review
from backend.models.user import User
from backend.models.dispensary import Dispensary
from backend.config import settings
from backend.templates import render_page

router = APIRouter(tags=["pages"])


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    is_logged_in = request.state.user_id is not None

    # Stats
    strain_count = (await db.execute(select(func.count()).select_from(Strain))).scalar() or 0
    dispo_count = (await db.execute(select(func.count()).select_from(Dispensary))).scalar() or 0
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar() or 0

    # Featured strains (top rated)
    featured = await db.execute(
        select(Strain).order_by(Strain.rating.desc()).limit(6)
    )
    featured_strains = featured.scalars().all()

    # Recent reviews
    recent_result = await db.execute(
        select(Review).order_by(Review.created_at.desc()).limit(8)
    )
    recent_reviews = recent_result.scalars().all()

    # Strain type counts
    indica_c = (await db.execute(select(func.count()).select_from(Strain).where(Strain.strain_type == "indica"))).scalar() or 0
    sativa_c = (await db.execute(select(func.count()).select_from(Strain).where(Strain.strain_type == "sativa"))).scalar() or 0
    hybrid_c = (await db.execute(select(func.count()).select_from(Strain).where(Strain.strain_type == "hybrid"))).scalar() or 0

    # Featured cards — image-first
    featured_cards = ""
    for s in featured_strains:
        img = s.image_url
        if img:
            image_html = f'<img src="{img}" alt="{s.name}" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" loading="lazy">'
        else:
            image_html = f'<div class="w-full h-full flex items-center justify-center text-4xl">{s.type_emoji}</div>'
        featured_cards += f"""<a href="/strains/{s.id}" class="strain-card strain-card-{s.strain_type if s.strain_type in ('indica','sativa','hybrid') else 'hybrid'}">
            <div class="aspect-4/3 overflow-hidden">{image_html}</div>
            <div class="p-3">
                <h3 class="font-semibold text-sm group-hover:text-weed-400 transition line-clamp-1">{s.name}</h3>
                <div class="text-xs text-neutral-500">{s.strain_type.title()} · {s.thc_display}</div>
                <span class="text-yellow-500 text-xs">{'★' * round(s.rating)}{'☆' * (5 - round(s.rating))}</span>
            </div>
        </a>"""

    # Reviews HTML
    reviews_html = ""
    for r in recent_reviews:
        reviews_html += f"""<div class="bg-elevated border rounded-xl p-4">
            <div class="flex items-center justify-between mb-1">
                <a href="/strains/{r.strain.id}" class="font-medium text-sm hover:text-weed-400 transition">{r.strain.name}</a>
                <span class="text-yellow-500 text-xs">{'★' * r.rating}</span>
            </div>
            <p class="text-xs text-neutral-400">by {r.user.display_name if r.user else 'someone'} · {r.consumption_method}</p>
            {f'<p class="text-sm text-neutral-300 mt-1 line-clamp-2">{r.notes[:120]}{"…" if len(r.notes)>120 else ""}</p>' if r.notes else ''}
        </div>"""
    if not reviews_html:
        reviews_html = '<p class="text-sm text-neutral-500 italic text-center py-8">No reviews yet.</p>'

    # Homepage keeps its own DOCTYPE wrapper (extra head assets: leaflet),
    # but pulls the shared nav from templates.
    from backend.templates import build_nav
    nav = build_nav(request)
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>WEED — Strain Catalog &amp; Dispensary Finder</title>
    <link rel="stylesheet" href="/static/css/app.css">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>.line-clamp-2{{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}</style>
    </head><body class="min-h-screen">

    {nav}

    <main>
    <!-- Hero -->
    <div class="bg-gradient-hero border-b border-glass">
        <div class="max-w-6xl mx-auto px-4 py-16 md:py-24 text-center">
            <div class="text-8xl mb-4">🌿</div>
            <h1 class="text-5xl md:text-7xl font-display text-weed-400 mb-4">WEED</h1>
            <p class="text-lg md:text-xl text-neutral-400 mb-8 max-w-2xl mx-auto">Strain Catalog · Dispensary Finder · Community Reviews</p>
            <div class="flex justify-center gap-3">
                <a href="/strains" class="btn btn-primary text-base px-8 py-3">Browse Strains</a>
                <a href="/dispensaries" class="btn btn-secondary text-base px-8 py-3">Find Dispensaries</a>
            </div>
        </div>
    </div>

    <!-- Live Stats -->
    <div class="max-w-6xl mx-auto px-4 -mt-8">
        <div id="live-stats" class="skeleton h-20 rounded-xl"></div>
        <script>fetch('/api/stats').then(r=>r.text()).then(h=>document.getElementById('live-stats').outerHTML=h)</script>
    </div>

    <!-- Type Breakdown -->
    <div class="max-w-6xl mx-auto px-4 py-8">
        <div class="grid grid-cols-3 gap-4">
            <div class="stat-card bg-indica border-0">
                <div class="text-2xl font-bold text-indigo-400">{indica_c}</div>
                <div class="text-xs text-indigo-300 uppercase tracking-[0.15em]">Indica</div>
            </div>
            <div class="stat-card bg-sativa border-0">
                <div class="text-2xl font-bold text-orange-400">{sativa_c}</div>
                <div class="text-xs text-orange-300 uppercase tracking-[0.15em]">Sativa</div>
            </div>
            <div class="stat-card bg-hybrid border-0">
                <div class="text-2xl font-bold text-purple-400">{hybrid_c}</div>
                <div class="text-xs text-purple-300 uppercase tracking-[0.15em]">Hybrid</div>
            </div>
        </div>
    </div>

    <!-- Top Rated -->
    <div class="max-w-6xl mx-auto px-4 py-8">
        <h2 class="section-title">🏆 Top Rated Strains</h2>
        <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">{featured_cards}</div>
    </div>

    <!-- Reviews + Map -->
    <div class="max-w-6xl mx-auto px-4 py-8">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div>
                <h2 class="section-title">💬 Recent Reviews</h2>
                <div class="space-y-3">{reviews_html}</div>
            </div>
            <div>
                <h2 class="section-title">🗺️ Dispensary Map</h2>
                <div id="home-map" class="h-64 bg-elevated rounded-xl border border-glass"></div>
            </div>
        </div>
    </div>
    </main>

    <script>
    fetch('/api/dispensaries/map-data').then(r=>r.json()).then(function(data) {{
        if (data.length === 0) {{
            document.getElementById('home-map').innerHTML = '<div class="flex items-center justify-center h-full text-neutral-500 text-sm">No dispensaries on the map yet</div>';
            return;
        }}
        var map = L.map('home-map', {{ zoomControl: false, attributionControl: false }}).setView([39.5, -98.0], 4);
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);
        data.forEach(function(d) {{
            if (d.lat && d.lon) {{
                L.marker([d.lat, d.lon]).addTo(map).bindPopup('<b>' + d.name + '</b><br>' + d.city + ', ' + d.state);
            }}
        }});
    }});
    </script>
    </body></html>"""
    return html


@router.get("/seeds", response_class=HTMLResponse)
async def landrace_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Landrace strains — the original foundational genetics."""
    is_logged_in = request.state.user_id is not None

    total = (await db.execute(select(func.count()).select_from(Strain))).scalar() or 0

    # Get all strains marked as landrace in DB
    result = await db.execute(
        select(Strain).where(Strain.is_landrace == True).order_by(Strain.name)
    )
    landraces = list(result.scalars().all())
    landrace_count = len(landraces)

    cards_html = ""
    for s in landraces:
        img = s.image_url
        if img:
            img_html = f'<img src="{img}" alt="{s.name}" class="w-full h-full object-cover" loading="lazy">'
        else:
            img_html = f'<div class="w-full h-full flex items-center justify-center text-4xl">{s.type_emoji}</div>'
        origin_tag = f'<span class="text-xs text-amber-400">🌍 {s.landrace_origin}</span>' if s.landrace_origin else '<span class="text-xs text-amber-400">🌍 Landrace</span>'
        cards_html += f"""<a href="/strains/{s.id}" class="strain-card bg-gradient-landrace">
            <div class="aspect-4/3 overflow-hidden">{img_html}</div>
            <div class="p-4">
                <h3 class="font-semibold group-hover:text-weed-400 transition">{s.name}</h3>
                <div class="text-xs text-neutral-500">{s.strain_type.title()} · {s.thc_display}</div>
                <div class="mt-2">{origin_tag}</div>
            </div>
        </a>"""

    if not cards_html:
        cards_html = '<div class="col-span-full text-center py-12"><p class="text-5xl mb-4 opacity-40">🌱</p><p class="text-xl text-amber-400">Landrace Strains</p><p class="text-sm text-neutral-500 mt-2">The original, native cannabis varieties from specific regions around the world.</p><p class="text-xs mt-4 text-neutral-600">Building our landrace catalog — checking back as we enrich more strains.</p></div>'

    # Homepage keeps its own DOCTYPE wrapper (extra head assets: leaflet),
    # but pulls the shared nav from templates.
    from backend.templates import build_nav
    nav = build_nav(request)
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Landrace Strains — WEED Seeds</title><link rel="stylesheet" href="/static/css/app.css">
    </head><body class="min-h-screen">
    {nav}
    <main class="max-w-6xl mx-auto px-4 py-8">
    <div class="max-w-4xl mx-auto mb-8">
        <div class="flex items-center gap-4 mb-4">
            <span class="text-5xl">🌱</span>
            <div>
                <h1 class="text-3xl font-display text-amber-400">Landrace Strains</h1>
                <p class="text-neutral-400">The original genetics — foundational cannabis varieties from around the world</p>
            </div>
        </div>
        <div class="bg-elevated border border-amber-800 rounded-xl p-4 text-sm text-neutral-300 leading-relaxed">
            <p><strong class="text-amber-400">What are landrace strains?</strong> Landrace cannabis strains are native, wild-grown varieties that developed in specific geographic regions over centuries. Unlike modern hybrids, they evolved naturally in places like the Hindu Kush mountains, Thai jungles, and Mexican valleys — adapting to local climates and developing unique cannabinoid and terpene profiles.</p>
            <p class="mt-2">These <strong class="text-amber-400">foundational genetics</strong> are the building blocks of virtually every modern strain. When you see "OG Kush x Blue Dream", you are looking at a chain that traces back to landraces like <strong class="text-neutral-200">Afghani</strong>, <strong class="text-neutral-200">Thai</strong>, and <strong class="text-neutral-200">Durban Poison</strong>.</p>
        </div>
    </div>
    <p class="text-sm text-neutral-400 mb-4">Showing {len(landraces)} landrace strains · {total} strains in catalog</p>
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">{cards_html}</div>
    </main></body></html>"""
    return html


@router.get("/map", response_class=HTMLResponse)
async def map_page(request: Request):
    is_logged_in = request.state.user_id is not None
    # Homepage keeps its own DOCTYPE wrapper (extra head assets: leaflet),
    # but pulls the shared nav from templates.
    from backend.templates import build_nav
    nav = build_nav(request)
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Dispensary Map — WEED</title>
    <link rel="stylesheet" href="/static/css/app.css">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
    </head><body class="min-h-screen flex flex-col">
    {nav}
    <div id="map" class="flex-1"></div>
    <script>
    var map = L.map('map', {{ zoomControl: true, attributionControl: false }}).setView([39.5, -98.0], 4);
    L.tileLayer('{settings.map_tile_url}').addTo(map);
    var markers = L.markerClusterGroup({{ maxClusterRadius: 50 }});
    fetch('/api/dispensaries/map-data').then(r=>r.json()).then(function(data) {{
        data.forEach(function(d) {{
            if (d.lat && d.lon) {{
                var m = L.marker([d.lat, d.lon]).bindPopup('<b>' + d.name + '</b><br>' + d.city + ', ' + d.state + '<br><a href="/dispensaries/' + d.id + '" class="text-weed-400 text-sm">View →</a>');
                markers.addLayer(m);
            }}
        }});
        map.addLayer(markers);
    }});
    </script>
    </body></html>"""
    return html


@router.get("/api/dispensaries/map-data")
async def dispensary_map_data(db=Depends(get_db)):
    """Return dispensary GeoJSON data for the map."""
    result = await db.execute(
        select(Dispensary).where(Dispensary.lat.isnot(None), Dispensary.lon.isnot(None)).limit(500)
    )
    dispos = result.scalars().all()
    return [
        {"id": d.id, "name": d.name, "city": d.city, "state": d.state, "lat": d.lat, "lon": d.lon}
        for d in dispos
    ]