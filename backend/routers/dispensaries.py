"""Dispensaries router — search, map, detail views."""
import json
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.models.dispensary import Dispensary, MenuItem
from backend.models.strain import Strain
from backend.templates import render_page

router = APIRouter(prefix="/dispensaries", tags=["dispensaries"])


@router.get("/search", response_class=JSONResponse)
async def search_dispensaries(q: str = Query("", min_length=1), db: AsyncSession = Depends(get_db)):
    """Search dispensaries by name/location — JSON for autocomplete."""
    result = await db.execute(
        select(Dispensary).where(
            or_(
                Dispensary.name.ilike(f"%{q}%"),
                Dispensary.city.ilike(f"%{q}%"),
                Dispensary.state.ilike(f"%{q}%"),
            )
        ).limit(10)
    )
    dispos = result.scalars().all()
    return [
        {"id": d.id, "name": d.name, "city": d.city, "state": d.state, "rating": d.rating}
        for d in dispos
    ]


@router.get("", response_class=HTMLResponse)
async def dispensary_list(
    request: Request,
    page: int = Query(1, ge=1),
    state: str = Query(""),
    city: str = Query(""),
    search: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    per_page = 24
    query = select(Dispensary)

    if state:
        query = query.where(Dispensary.state.ilike(f"%{state}%"))
    if city:
        query = query.where(Dispensary.city.ilike(f"%{city}%"))
    if search:
        query = query.where(Dispensary.name.ilike(f"%{search}%"))

    query = query.order_by(Dispensary.name.asc())

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    dispos = result.scalars().all()

    is_logged_in = request.state.user_id is not None

    cards_html = ""
    for d in dispos:
        delivery_tag = '<span class="text-xs text-green-400">🚚 Delivery</span>' if d.delivery_available else ''
        cards_html += f"""<a href="/dispensaries/{d.id}" class="strain-card">
            <div class="p-4 flex items-start gap-3">
                <div class="w-12 h-12 bg-elevated rounded-lg flex items-center justify-center text-xl shrink-0">🏪</div>
                <div class="min-w-0">
                    <h3 class="font-semibold group-hover:text-weed-400 transition truncate">{d.name}</h3>
                    <p class="text-xs text-neutral-500">{d.city}, {d.state}{f' · ★ {d.rating}' if d.rating else ''}</p>
                    <div class="flex gap-2 mt-1">{delivery_tag}<span class="text-xs text-neutral-500 capitalize">{d.license_type or "recreational"}</span></div>
                </div>
            </div>
        </a>"""

    if not cards_html:
        cards_html = '<div class="col-span-full text-center py-12 text-neutral-500"><p class="text-4xl mb-2">🏪</p><p>No dispensaries found yet.</p><p class="text-sm mt-2">We have 100 dispensaries in the database — check your filters.</p></div>'

    html = render_page(f"""<div class="mb-6">
        <h1 class="text-3xl font-display text-weed-400">🏪 Dispensaries</h1>
        <p class="text-neutral-400">{total} locations</p>
    </div>
    <form method="get" action="/dispensaries" class="mb-6 bg-elevated border border-glass rounded-xl p-4">
        <div class="flex flex-wrap gap-3 items-end">
            <div>
                <label class="text-xs text-neutral-500 block mb-1">Search</label>
                <input type="text" name="search" value="{search}" placeholder="Dispensary name..." class="w-40 md:w-48">
            </div>
            <div>
                <label class="text-xs text-neutral-500 block mb-1">State</label>
                <input type="text" name="state" value="{state}" placeholder="CA, CO, ..." class="w-28">
            </div>
            <div>
                <label class="text-xs text-neutral-500 block mb-1">City</label>
                <input type="text" name="city" value="{city}" placeholder="City" class="w-32">
            </div>
            <div class="flex gap-2">
                <button type="submit" class="btn btn-primary">Filter</button>
                <a href="/dispensaries" class="btn btn-ghost text-sm">Clear</a>
            </div>
        </div>
    </form>
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">{cards_html}</div>""", "Dispensaries — WEED", request=request)
    return html


@router.get("/{dispensary_id}", response_class=HTMLResponse)
async def dispensary_detail(dispensary_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Dispensary).where(Dispensary.id == dispensary_id))
    dispo = result.scalar_one_or_none()
    if not dispo:
        return HTMLResponse("Dispensary not found", status_code=404)

    # Get menu items
    menu_result = await db.execute(
        select(MenuItem).where(MenuItem.dispensary_id == dispensary_id).order_by(MenuItem.category)
    )
    items = menu_result.scalars().all()

    # Group by category
    categories = {}
    for item in items:
        cat = item.category or "other"
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(item)

    is_logged_in = request.state.user_id is not None
    hours_html = ""
    if dispo.hours_dict:
        for day, hrs in dispo.hours_dict.items():
            hours_html += f'<div class="flex justify-between text-sm"><span class="text-neutral-400 capitalize">{day}</span><span>{hrs}</span></div>'

    menu_html = ""
    if categories:
        cat_labels = {"flower": "🌿 Flower", "edible": "🍪 Edibles", "concentrate": "💎 Concentrates", "vape": "💨 Vapes", "tincture": "💧 Tinctures", "topical": "🧴 Topicals", "preroll": "🚬 Pre-Rolls", "other": "📦 Other"}
        for cat, cat_items in categories.items():
            menu_html += f"""<div class="mb-6"><h3 class="text-sm font-semibold text-neutral-400 uppercase tracking-wider mb-3">{cat_labels.get(cat, cat)} ({len(cat_items)})</h3>
            <div class="space-y-2">"""
            for item in cat_items:
                price_str = f"${item.price:.0f}/{item.price_unit}" if item.price else "—"
                og_str = f'<span class="line-through text-neutral-600 text-xs">${item.price_original:.0f}</span> ' if item.price_original else ''
                thc_str = f' · <span class="text-weed-400">{item.thc_content}</span>' if item.thc_content else ''
                menu_html += f"""<div class="bg-neutral-900 border border-neutral-800 rounded-lg px-4 py-3 flex items-center justify-between">
                    <div><div class="font-medium text-sm">{item.name}</div>
                    <div class="text-xs text-neutral-500">{item.brand}{thc_str}</div></div>
                    <div class="text-right"><div class="text-sm font-semibold text-weed-400">{og_str}{price_str}</div></div>
                </div>"""
            menu_html += "</div></div>"
    else:
        menu_html = '<p class="text-neutral-500 text-sm italic">No menu items yet.</p>'

    html = render_page(f"""<div class="flex flex-col md:flex-row gap-8 mb-8">
        <div class="md:w-1/3">
            <div class="bg-elevated border border-glass rounded-xl p-4 space-y-3">
                <h1 class="text-2xl font-display text-weed-400">{dispo.name}</h1>
                {f'<p class="text-sm text-neutral-300">{dispo.address}</p>' if dispo.address else ''}
                <p class="text-sm text-neutral-400">{dispo.city}, {dispo.state} {dispo.zip_code}</p>
                {f'<div class="flex items-center gap-1"><span class="text-yellow-500 text-sm">{chr(9733) * round(dispo.rating) if dispo.rating else ""}</span><span class="text-sm text-neutral-400">{dispo.rating}</span></div>' if dispo.rating else ''}
                {f'<a href="{dispo.website}" target="_blank" class="block text-sm text-weed-400 hover:underline">{dispo.website}</a>' if dispo.website else ''}
                {f'<p class="text-sm text-neutral-300">📞 {dispo.phone}</p>' if dispo.phone else ''}
                <div class="flex gap-2 mt-2">
                    <span class="pill capitalize">{dispo.license_type}</span>
                    {'<span class="pill bg-green-900 text-green-200">🚚 Delivery</span>' if dispo.delivery_available else ''}
                </div>
                {f'<div class="text-xs text-neutral-500 space-y-1 pt-2 border-t border-glass">{hours_html}</div>' if hours_html else ''}
                {f'<p class="text-sm text-neutral-300 mt-3">{dispo.description}</p>' if dispo.description else ''}
            </div>
            {f'<div id="map" class="h-48 rounded-xl mt-4" data-lat="{dispo.lat}" data-lon="{dispo.lon}"></div>' if dispo.lat and dispo.lon else ''}
        </div>
        <div class="md:w-2/3">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-lg font-semibold text-neutral-200 mb-0">📋 Menu</h2>
                {f'<a href="/visits/add/{dispo.id}" class="btn btn-primary text-sm">📍 Log Visit</a>' if is_logged_in else ''}
            </div>
            {menu_html}
        </div>
    </div>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script>
    (function(){{
        var mapDiv = document.getElementById('map');
        if (!mapDiv) return;
        var lat = parseFloat(mapDiv.dataset.lat);
        var lon = parseFloat(mapDiv.dataset.lon);
        if (!lat || !lon) return;
        var map = L.map(mapDiv, {{ zoomControl: false, attributionControl: false }}).setView([lat, lon], 14);
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(map);
        L.marker([lat, lon]).addTo(map).bindPopup('{dispo.name}');
    }})();
    </script>""", f"{dispo.name} — WEED", request=request)
    return html