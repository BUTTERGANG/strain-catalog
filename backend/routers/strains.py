"""Strains router — catalog, search, detail views with modern image-first design."""

import html as html_mod
import json
import os
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db, async_session
from backend.models.strain import Strain
from backend.models.review import Review
from backend.templates import render_page, strain_image_html
from backend.models.wishlist import WishlistItem, DispensaryVisit
from backend.services.lineage_parse import parse_parents, genetics_string

router = APIRouter(prefix="/strains", tags=["strains"])


@router.get("/search", response_class=JSONResponse)
async def search_strains(q: str = Query("", min_length=1), db: AsyncSession = Depends(get_db)):
    """Search strains by name — returns JSON for autocomplete with image."""
    result = await db.execute(
        select(Strain).where(Strain.name.ilike(f"%{q}%")).limit(10)
    )
    strains = result.scalars().all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "type": s.strain_type,
            "type_emoji": s.type_emoji,
            "rating": s.rating,
            "image": s.image_url,
            "breeder": s.breeder,
            "thc": s.thc_display,
        }
        for s in strains
    ]


@router.get("", response_class=HTMLResponse)
async def strain_list(
    request: Request,
    page: int = Query(1, ge=1),
    type_filter: str = Query("", alias="type"),
    effect_filter: str = Query("", alias="effect"),
    terpene_filter: str = Query("", alias="terpene"),
    breeder_filter: str = Query("", alias="breeder"),
    parent_filter: str = Query("", alias="parent"),
    search: str = Query(""),
    sort: str = Query("name"),
    db: AsyncSession = Depends(get_db),
):
    per_page = 48
    query = select(Strain)

    if type_filter and type_filter in ("indica", "sativa", "hybrid"):
        query = query.where(Strain.strain_type == type_filter)

    if breeder_filter:
        query = query.where(Strain.breeder.ilike(f"%{breeder_filter}%"))
    
    # Parent-based search — find strains whose genetics mention a parent name
    if parent_filter:
        query = query.where(Strain.genetics.ilike(f"%{parent_filter}%"))

    if effect_filter:
        query = query.where(Strain.effects.ilike(f"%{effect_filter}%"))

    if terpene_filter:
        query = query.where(Strain.terpenes.ilike(f"%{terpene_filter}%"))

    if search:
        query = query.where(Strain.name.ilike(f"%{search}%"))

    if sort == "rating":
        query = query.order_by(Strain.rating.desc())
    elif sort == "thc":
        query = query.order_by(Strain.thc_max.desc().nulls_last())
    elif sort == "reviews":
        query = query.order_by(Strain.review_count.desc())
    else:
        query = query.order_by(Strain.name.asc())

    # Count total
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    strains = result.scalars().all()

    total_pages = max(1, (total + per_page - 1) // per_page)
    is_logged_in = request.state.user_id is not None

    # Build strain cards
    cards_html = ""
    type_options = {"": "All Types", "indica": "Indica", "sativa": "Sativa", "hybrid": "Hybrid"}
    sort_options = {"name": "Name", "rating": "Rating", "thc": "THC", "reviews": "Most Reviewed"}
    effect_options = {"": "Any Effect", "Happy": "Happy", "Euphoric": "Euphoric", "Relaxed": "Relaxed",
                      "Uplifted": "Uplifted", "Creative": "Creative", "Focused": "Focused",
                      "Energetic": "Energetic", "Hungry": "Hungry", "Sleepy": "Sleepy",
                      "Talkative": "Talkative", "Giggly": "Giggly", "Tingly": "Tingly"}
    terpene_options = {"": "Any Terpene", "myrcene": "Myrcene", "caryophyllene": "Caryophyllene",
                       "limonene": "Limonene", "pinene": "Pinene", "humulene": "Humulene",
                       "linalool": "Linalool", "terpinolene": "Terpinolene", "ocimene": "Ocimene"}
    breeder_options = {"": "Any Breeder", "Clone Only Strains": "Clone Only Strains",
                       "Bodhi Seeds": "Bodhi Seeds", "DNA Genetics Seeds": "DNA Genetics",
                       "Barneys Farm": "Barneys Farm", "Exotic Genetix": "Exotic Genetix",
                       "Rare Dankness Seeds": "Rare Dankness Seeds",
                       "Dutch Passion": "Dutch Passion", "Royal Queen Seeds": "Royal Queen Seeds",
                       "Sensi Seeds": "Sensi Seeds", "Nirvana Seeds": "Nirvana Seeds",
                       "TH Seeds": "TH Seeds", "Seedism Seeds": "Seedism Seeds"}
    parent_options = {"": "Any Parent", "OG Kush": "OG Kush", "Blueberry": "Blueberry",
                      "Sour Diesel": "Sour Diesel", "White Widow": "White Widow",
                      "Afghani": "Afghani", "Haze": "Haze", "Bubba Kush": "Bubba Kush",
                      "Chemdawg": "Chemdawg", "Skunk": "Skunk", "Northern Lights": "Northern Lights",
                      "Jack Herer": "Jack Herer", "GSC": "Girl Scout Cookies", "Blue Dream": "Blue Dream"}

    for s in strains:
        effects = s.effect_list
        terps = s.terpene_list
        effects_html = "".join(f'<span class="pill">{e}</span>' for e in effects[:3])
        top_terp = terps[0]["name"].title() if terps else ""
        top_terp_pct = terps[0]["percentage"] if terps else 0
        terp_badge = f'<span class="text-xs text-weed-400">🌿 {top_terp} {top_terp_pct}%</span>' if top_terp else ""

        type_class = f"strain-card-{s.strain_type}" if s.strain_type in ("indica", "sativa", "hybrid") else ""

        img = s.image_url
        image_html = strain_image_html(
            img, s.name, "strain-card-image", s.type_emoji,
            fallback_class="strain-card-image flex items-center justify-center text-5xl",
        )

        breeder_tag = f'<span class="breeder-badge mt-1">👨‍🌾 {s.breeder[:35]}</span>' if s.breeder else ""
        stars = "★" * round(s.rating) + "☆" * (5 - round(s.rating))

        cards_html += f"""<div class="strain-card {type_class} relative">
            <a href="/strains/{s.id}" class="block">
                <div class="relative overflow-hidden">
                    {image_html}
                    {f'<span class="absolute top-2 right-2 text-xs bg-black/60 backdrop-blur-sm px-2 py-0.5 rounded-full">{s.type_emoji}</span>' if img else ''}
                </div>
            </a>
            <label class="absolute top-2 left-2 z-10 bg-black/60 backdrop-blur-sm rounded-full px-2 py-1 text-xs cursor-pointer flex items-center gap-1 hover:bg-weed-700/60 transition" onclick="event.stopPropagation()">
                <input type="checkbox" class="compare-cb" value="{s.id}" onchange="updateCompare()" style="accent-color:#22c55e">
                <span class="text-neutral-300 text-[10px]">Compare</span>
            </label>
            <a href="/strains/{s.id}" class="block p-4">
                <div class="flex items-start justify-between gap-2">
                    <h3 class="font-semibold text-lg group-hover:text-weed-400 transition line-clamp-1 flex-1">{s.name}</h3>
                    <span class="text-yellow-500 text-xs shrink-0">{stars}</span>
                </div>
                <div class="flex items-center gap-2 text-xs text-neutral-500 mt-0.5">
                    <span class="capitalize">{s.strain_type}</span>
                    <span>·</span>
                    <span class="font-medium text-weed-400">{s.thc_display}</span>
                </div>
                {f'<div class="mt-1">{terp_badge}</div>' if terp_badge else ''}
                {breeder_tag}
                <div class="flex flex-wrap gap-1 mt-2">{effects_html}</div>
            </a>
        </div>"""

    # Pagination
    pagination = ""
    if total_pages > 1:
        params = f"type={type_filter}&search={search}&sort={sort}&breeder={breeder_filter}&effect={effect_filter}&terpene={terpene_filter}"
        pages = []
        for p in range(1, min(total_pages + 1, 12)):
            if p == page:
                pages.append(f'<span class="px-3 py-1 rounded bg-weed-700 text-sm font-medium">{p}</span>')
            else:
                pages.append(f'<a href="/strains?page={p}&{params}" class="px-3 py-1 rounded bg-glass hover:bg-neutral-800 text-sm transition">{p}</a>')
        if total_pages > 11:
            pages.append('<span class="text-neutral-500 px-2">…</span>')
            pages.append(f'<a href="/strains?page={total_pages}&{params}" class="px-3 py-1 rounded bg-glass hover:bg-neutral-800 text-sm transition">{total_pages}</a>')
        pagination = f'<div class="flex justify-center gap-2 mt-8">{"".join(pages)}</div>'

    # Active filter tags
    active_filters_html = ""
    if type_filter: active_filters_html += f'<span class="pill bg-weed-700 text-white text-xs">{type_filter.title()} <a href="?page={page}&search={search}&sort={sort}&breeder={breeder_filter}&effect={effect_filter}&terpene={terpene_filter}" class="ml-1 hover:text-white">&times;</a></span> '
    if breeder_filter: active_filters_html += f'<span class="pill bg-weed-700 text-white text-xs">{breeder_filter[:40]} <a href="?page={page}&type={type_filter}&search={search}&sort={sort}&effect={effect_filter}&terpene={terpene_filter}" class="ml-1 hover:text-white">&times;</a></span> '
    if effect_filter: active_filters_html += f'<span class="pill bg-weed-700 text-white text-xs">{effect_filter} <a href="?page={page}&type={type_filter}&search={search}&sort={sort}&breeder={breeder_filter}&terpene={terpene_filter}" class="ml-1 hover:text-white">&times;</a></span> '

    # Filters row — two rows, collapsed on mobile
    filters_html = f"""<div class="flex flex-wrap gap-3 items-end">
        <div>
            <label class="text-xs text-neutral-500 block mb-1">Search</label>
            <input type="text" name="search" value="{html_mod.escape(search, quote=True)}" placeholder="Search strains…" class="w-40 md:w-48">
        </div>
        <div>
            <label class="text-xs text-neutral-500 block mb-1">Type</label>
            <select name="type" class="w-28">
                {''.join(f'<option value="{k}"{" selected" if type_filter==k else ""}>{v}</option>' for k,v in type_options.items())}
            </select>
        </div>
        <div>
            <label class="text-xs text-neutral-500 block mb-1">Effect</label>
            <select name="effect" class="w-32">
                {''.join(f'<option value="{k}"{" selected" if effect_filter==k else ""}>{v}</option>' for k,v in effect_options.items())}
            </select>
        </div>
        <div>
            <label class="text-xs text-neutral-500 block mb-1">Terpene</label>
            <select name="terpene" class="w-32">
                {''.join(f'<option value="{k}"{" selected" if terpene_filter==k else ""}>{v}</option>' for k,v in terpene_options.items())}
            </select>
        </div>
        <div>
            <label class="text-xs text-neutral-500 block mb-1">Breeder</label>
            <select name="breeder" class="w-40">
                {''.join(f'<option value="{k}"{" selected" if breeder_filter==k else ""}>{v}</option>' for k,v in breeder_options.items())}
            </select>
        </div>
        <div>
            <label class="text-xs text-neutral-500 block mb-1">Parent</label>
            <select name="parent" class="w-32">
                {''.join(f'<option value="{k}"{" selected" if parent_filter==k else ""}>{v}</option>' for k,v in parent_options.items())}
            </select>
        </div>
        <div>
            <label class="text-xs text-neutral-500 block mb-1">Sort</label>
            <select name="sort" class="w-28">
                {''.join(f'<option value="{k}"{" selected" if sort==k else ""}>{v}</option>' for k,v in sort_options.items())}
            </select>
        </div>
        <div class="flex gap-2">
            <button type="submit" class="btn btn-primary">Filter</button>
            <a href="/strains" class="btn btn-ghost text-sm">Clear</a>
        </div>
    </div>"""

    html = render_page(f"""<div class="mb-6">
        <h1 class="text-3xl font-display text-weed-400">Strain Catalog</h1>
        <p class="text-neutral-400 mt-1">{total} strain{'s' if total != 1 else ''}</p>
    </div>
    <form method="get" action="/strains" class="mb-6 bg-elevated border border-glass rounded-xl p-4">{filters_html}</form>
    {f'<div class="flex flex-wrap gap-2 mb-4">{active_filters_html}</div>' if active_filters_html else ''}
    <div class="flex items-center justify-between mb-4">
        <div class="text-sm text-neutral-500">
            <span id="compare-count">0</span> selected for comparison
        </div>
        <a id="compare-btn" href="/strains/compare" class="btn btn-primary text-sm !py-1.5 opacity-50 pointer-events-none">
            Compare
        </a>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">{cards_html}</div>
    {pagination}

    <script>
    // ── Compare Function ──
    function updateCompare() {{
        var cbs = document.querySelectorAll('.compare-cb:checked');
        var ids = [];
        cbs.forEach(function(cb) {{ ids.push(cb.value); }});
        document.getElementById('compare-count').textContent = ids.length;
        var btn = document.getElementById('compare-btn');
        if (ids.length >= 2) {{
            btn.href = '/strains/compare?ids=' + ids.join(',');
            btn.classList.remove('opacity-50', 'pointer-events-none');
        }} else {{
            btn.href = '/strains/compare';
            btn.classList.add('opacity-50', 'pointer-events-none');
        }}
    }}
    // ── Search Autocomplete ──
    (function() {{
        const input = document.querySelector('input[name="search"]');
        const form = input?.closest('form');
        if (!input) return;
        let dropdown = document.createElement('div');
        dropdown.className = 'absolute z-50 top-full left-0 right-0 mt-1 bg-elevated border border-glass rounded-xl shadow-lg overflow-hidden hidden';
        dropdown.style.minWidth = '200px';
        input.parentElement.style.position = 'relative';
        input.parentElement.appendChild(dropdown);

        let timer;
        input.addEventListener('input', function() {{
            clearTimeout(timer);
            const q = this.value.trim();
            if (q.length < 2) {{ dropdown.classList.add('hidden'); return; }}
            timer = setTimeout(async () => {{
                const resp = await fetch('/strains/search?q=' + encodeURIComponent(q));
                const data = await resp.json();
                if (!data.length) {{ dropdown.classList.add('hidden'); return; }}
                dropdown.innerHTML = data.map(function(s) {{
                    return '<a href="/strains/' + s.id + '" class="flex items-center gap-3 px-3 py-2 hover:bg-glass transition border-b border-glass last:border-0">' +
                        (s.image ? '<img src="' + s.image + '" class="w-8 h-8 rounded object-cover" onerror="this.style.display=`none`">' : '<span class="text-lg">' + s.type_emoji + '</span>') +
                        '<div class="flex-1 min-w-0">' +
                            '<div class="text-sm font-medium truncate">' + s.name + '</div>' +
                            '<div class="text-xs text-neutral-500">' + (s.breeder ? s.breeder + ' &middot; ' : '') + s.thc + '</div>' +
                        '</div>' +
                        '<span class="text-yellow-500 text-xs">' + '&#9733;'.repeat(Math.round(s.rating)) + '</span>' +
                    '</a>';
                }}).join('');
                dropdown.classList.remove('hidden');
            }}, 200);
        }});
        input.addEventListener('blur', () => setTimeout(() => dropdown.classList.add('hidden'), 200));
        input.addEventListener('focus', () => {{ if (input.value.trim().length >= 2) dropdown.classList.remove('hidden'); }});
    }})();
    </script>""", f"Strains — WEED", request=request)
    return html


# ── Strain Comparison (side-by-side) ──
@router.get("/compare", response_class=HTMLResponse)
async def strain_compare(
    request: Request,
    ids: str = Query("", alias="ids"),
    db: AsyncSession = Depends(get_db),
):
    """Compare 2-5 strains side-by-side."""
    strain_ids = [i.strip() for i in ids.split(",") if i.strip()][:5]
    if len(strain_ids) < 2:
        return render_page("""<div class="text-center py-12">
            <p class="text-4xl mb-4">🔬</p>
            <h1 class="text-2xl font-display text-weed-400 mb-2">Strain Comparison</h1>
            <p class="text-neutral-500 mb-4">Select 2-5 strains to compare side-by-side.</p>
            <p class="text-sm text-neutral-600">Browse strains and click the compare checkbox on each card.</p>
        </div>""", "Compare — WEED", request=request)

    strains = []
    for sid in strain_ids:
        result = await db.execute(select(Strain).where((Strain.id == sid) | (Strain.slug == sid)))
        s = result.scalar_one_or_none()
        if s:
            strains.append(s)

    if len(strains) < 2:
        # Some IDs were unknown — show the empty state with guidance instead of a bare 400
        return render_page("""<div class="text-center py-12">
            <p class="text-4xl mb-4">🔬</p>
            <h1 class="text-2xl font-display text-weed-400 mb-2">Strain Comparison</h1>
            <p class="text-neutral-500 mb-4">Couldn't find at least 2 valid strains in that selection.</p>
            <p class="text-sm text-neutral-600 mb-6">Browse strains and check the "Compare" box on each card, then hit Compare.</p>
            <a href="/strains" class="btn btn-primary">Browse Strains</a>
        </div>""", "Compare — WEED", request=request)

    # Build comparison table
    def terp_str(s):
        terps = s.terpene_list
        if not terps:
            return '<span class="text-neutral-500">—</span>'
        return "<br>".join(f'{t["name"].title()}: {t["percentage"]}%' for t in terps[:4])

    def effect_str(s):
        effects = s.effect_list
        if not effects:
            return '<span class="text-neutral-500">—</span>'
        return " ".join(f'<span class="pill">{e}</span>' for e in effects[:5])

    def star_str(rating):
        return "★" * round(rating) + "☆" * (5 - round(rating))

    cols_html = ""
    for s in strains:
        img_html = strain_image_html(
            s.image_url, s.name, "w-full aspect-square object-cover rounded-lg", s.type_emoji,
            fallback_class="w-full aspect-square bg-elevated rounded-lg flex items-center justify-center text-5xl",
        )
        cols_html += f"""<div class="flex flex-col">
            <a href="/strains/{s.id}" class="block mb-3">{img_html}</a>
            <h3 class="font-semibold text-lg text-weed-400">{s.name}</h3>
            {f'<span class="breeder-badge text-xs mt-1">👨‍🌾 {s.breeder[:40]}</span>' if s.breeder else ''}
            <div class="text-yellow-500 text-sm mt-1">{star_str(s.rating)}</div>
            <div class="text-xs text-neutral-500 mt-1 capitalize">{s.strain_type} · {s.thc_display}</div>
            {f'<div class="text-xs text-neutral-500 mt-1">{s.sativa_pct or "?"}% S / {s.indica_pct or "?"}% I</div>' if s.sativa_pct or s.indica_pct else ''}
            {f'<div class="text-xs text-neutral-500 mt-1">🌱 {s.flowering_days}d · {s.seed_type}</div>' if s.flowering_days else ''}
            <hr class="border-glass my-3">
            <div class="space-y-2 text-sm">{effect_str(s)}</div>
            {f'<hr class="border-glass my-3"><div class="text-xs space-y-1">{terp_str(s)}</div>' if s.terpene_list else ''}
            {f'<hr class="border-glass my-3"><div class="text-xs text-neutral-300"><strong>🧬</strong> {s.genetics[:80]}</div>' if s.genetics else ''}
            <div class="mt-auto pt-3">
                <a href="/strains/{s.id}" class="btn btn-primary text-xs w-full text-center">View Details</a>
            </div>
        </div>"""

    html = render_page(f"""<div class="mb-6">
        <h1 class="text-3xl font-display text-weed-400">Strain Comparison</h1>
        <p class="text-neutral-400 mt-1">Comparing {len(strains)} strains</p>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 {'lg:grid-cols-3' if len(strains) >= 3 else ''} {'xl:grid-cols-4' if len(strains) >= 4 else ''} gap-4">
        {cols_html}
    </div>
    <div class="mt-8 text-center">
        <a href="/strains" class="btn btn-secondary">← Back to Strains</a>
    </div>""", "Compare — WEED", request=request)
    return html


# ── Wishlist toggle ──
@router.post("/{strain_id}/wishlist")
async def toggle_wishlist(strain_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user_id = request.state.user_id
    if not user_id:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    existing = await db.execute(
        select(WishlistItem).where(
            WishlistItem.user_id == user_id,
            WishlistItem.strain_id == strain_id,
        )
    )
    item = existing.scalar_one_or_none()
    if item:
        await db.delete(item)
        await db.commit()
        return JSONResponse({"saved": False, "message": "Removed from wishlist"})
    else:
        db.add(WishlistItem(user_id=user_id, strain_id=strain_id))
        await db.commit()
        return JSONResponse({"saved": True, "message": "Saved to wishlist"})


@router.get("/{strain_id}/wishlist-status")
async def wishlist_status(strain_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    from fastapi.responses import JSONResponse
    user_id = request.state.user_id
    if not user_id:
        return JSONResponse({"saved": False})
    existing = await db.execute(
        select(WishlistItem).where(
            WishlistItem.user_id == user_id,
            WishlistItem.strain_id == strain_id,
        )
    )
    return JSONResponse({"saved": existing.scalar_one_or_none() is not None})


@router.get("/sitemap.xml")
async def sitemap():
    """SEO sitemap — homepage, static pages, top strains."""
    from fastapi.responses import Response
    from sqlalchemy import text
    async with async_session() as db:
        rows = (await db.execute(text(
            "SELECT slug FROM strains WHERE slug IS NOT NULL ORDER BY review_count DESC, name LIMIT 5000"
        ))).fetchall()
    base = os.getenv("SITE_URL", "http://localhost:8003")
    urls = ["/", "/strains", "/dispensaries", "/map", "/seeds"]
    xml_items = "".join(f"<url><loc>{base}{u}</loc></url>" for u in urls)
    xml_items += "".join(f"<url><loc>{base}/strains/{slug}</loc></url>" for (slug,) in rows)
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{xml_items}</urlset>'
    return Response(content=xml, media_type="application/xml")


@router.get("/robots.txt")
async def robots():
    from fastapi.responses import Response
    base = os.getenv("SITE_URL", "http://localhost:8003")
    return Response(
        content=f"User-agent: *\nAllow: /\nDisallow: /auth\nDisallow: /profile\n\nSitemap: {base}/strains/sitemap.xml\n",
        media_type="text/plain",
    )


@router.get("/{strain_id}", response_class=HTMLResponse)
async def strain_detail(strain_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    # Try slug first (SEO URLs like /strains/blue-dream), fall back to ID
    result = await db.execute(select(Strain).where((Strain.slug == strain_id) | (Strain.id == strain_id)))
    strain = result.scalar_one_or_none()
    if not strain:
        return HTMLResponse("Strain not found", status_code=404)

    is_logged_in = request.state.user_id is not None

    # Get reviews
    reviews_result = await db.execute(
        select(Review).where(Review.strain_id == strain_id).order_by(Review.created_at.desc()).limit(20)
    )
    reviews = reviews_result.scalars().all()

    # Get lineage
    from backend.models.lineage import StrainLink
    parents_result = await db.execute(
        select(StrainLink).where(
            StrainLink.child_id == strain_id,
            StrainLink.rel_type.in_(["parent", "cross", "phenotype", "descendant", "genetics_source"])
        ).order_by(StrainLink.confidence.desc())
    )
    parent_links = parents_result.scalars().all()

    children_result = await db.execute(
        select(StrainLink).where(
            StrainLink.parent_id == strain_id,
            StrainLink.rel_type.in_(["parent", "cross"])
        ).order_by(StrainLink.confidence.desc())
    )
    child_links = children_result.scalars().all()

    effects = strain.effect_list
    flavors = strain.flavor_list
    terpenes = strain.terpene_list

    # ── Terpene Profile ──
    TERP_COLORS = {
        "caryophyllene": "var(--t-caryophyllene)", "myrcene": "var(--t-myrcene)",
        "limonene": "var(--t-limonene)", "pinene": "var(--t-pinene)",
        "humulene": "var(--t-humulene)", "linalool": "var(--t-linalool)",
        "terpinolene": "var(--t-terpinolene)", "ocimene": "var(--t-ocimene)",
    }
    terp_html = ""
    if terpenes:
        for t in terpenes:
            pct = t.get("percentage", 0)
            bar_w = min(pct * 2, 100)
            terp_color = TERP_COLORS.get((t.get("name") or "").lower(), "var(--weed)")
            terp_html += f"""<div class="flex items-center gap-3">
                <span class="text-sm w-24 capitalize text-neutral-300"><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:{terp_color};margin-right:6px;"></span>{t.get("name","")}</span>
                <div class="terp-bar-track"><div class="terp-bar-fill" style="width:{bar_w}%;background:{terp_color}"></div></div>
                <span class="text-xs text-neutral-500 w-8 text-right" style="font-family:'JetBrains Mono',monospace;">{pct}%</span>
            </div>"""

    # ── Effects Pills ──
    effects_html = "".join(
        f'<span class="pill">{e}</span>' for e in effects
    ) if effects else ""

    # ── Flavor Pills ──
    flavors_html = "".join(
        f'<span class="pill">{f}</span>' for f in flavors
    ) if flavors else ""

    # ── Photo Gallery ──
    gallery_html = f"""<div class="mb-8">
        <h2 class="section-title">Photos</h2>
        <div class="upload-zone" onclick="document.getElementById('photo-upload').click()">
            <div class="text-3xl mb-2 opacity-40">📷</div>
            <p class="text-sm text-neutral-400">Upload photos of this strain to help the community</p>
            <p class="text-xs text-neutral-500 mt-1">JPG, PNG • Max 10MB</p>
            <input type="file" id="photo-upload" accept="image/*" class="hidden" multiple
                   onchange="uploadPhotos(this.files, '{strain_id}')">
        </div>
        <div id="gallery-grid" class="gallery-grid mt-4">
            <div class="gallery-grid-main bg-glass flex items-center justify-center text-neutral-600">
                {strain_image_html(strain.image_url, strain.name, "w-full h-full object-cover", strain.type_emoji, fallback_class="text-4xl")}
            </div>
        </div>
    </div>"""

    # ── Lineage Tree ──
    # Fallback: when we have no structured lineage, try to read the cross out of
    # the description prose ("...a cross between Dark Night and Blue Dream").
    derived_parents = []
    if not (parent_links or child_links or strain.genetics):
        names = parse_parents(strain.description or "", strain.name)
        if names:
            rows = (await db.execute(
                select(Strain).where(or_(*[Strain.name.ilike(n) for n in names]))
            )).scalars().all()
            by_name = {r.name.lower(): r for r in rows}
            derived_parents = [(n, by_name.get(n.lower())) for n in names]

    lineage_html = ""
    if parent_links or child_links or strain.genetics:
        lineage_html = '<div class="mb-8"><h2 class="section-title">Genetic Lineage</h2><div class="bg-elevated border rounded-xl p-6">'

        # Genetics string
        if strain.genetics:
            lineage_html += f'<div class="flex items-center gap-2 mb-4"><span class="pill">🧬 {strain.genetics}</span></div>'

        # Build tree data for JS visualization
        tree_data = {"name": strain.name, "id": strain_id, "children": []}
        if parent_links:
            lineage_html += '<div class="lineage-tree"><ul>'
            for link in parent_links:
                p = link.parent
                tree_data["children"].append({"name": p.name, "id": p.id, "type": p.strain_type, "type_emoji": p.type_emoji})
                lineage_html += f'''<li>
                    <a href="/strains/{p.id}" class="lineage-tree-node">
                        <span>{p.type_emoji}</span>
                        <span class="font-medium">{p.name}</span>
                        <span class="text-xs text-neutral-500">{p.strain_type.title()} · {p.thc_display}</span>
                    </a>
                </li>'''
            lineage_html += '</ul></div>'

        if child_links:
            lineage_html += '<div class="mt-4"><h3 class="text-xs font-semibold text-neutral-500 uppercase tracking-wider mb-3">Known Offspring</h3>'
            lineage_html += '<div class="lineage-tree"><ul>'
            for link in child_links[:8]:
                c = link.child
                lineage_html += f'''<li>
                    <a href="/strains/{c.id}" class="lineage-tree-node">
                        <span>{c.type_emoji}</span>
                        <span class="font-medium">{c.name}</span>
                        <span class="text-xs text-neutral-500">{c.strain_type.title()} · {c.thc_display}</span>
                    </a>
                </li>'''
            if len(child_links) > 8:
                lineage_html += f'<li><span class="text-xs text-neutral-500">… and {len(child_links) - 8} more</span></li>'
            lineage_html += '</ul></div></div>'

        lineage_html += '</div></div>'

        # Add D3.js tree visualization for lineages with data
        if parent_links or child_links:
            tree_json = json.dumps(tree_data)
            lineage_html += f'''<div class="mb-8 bg-elevated border rounded-xl p-6">
                <h3 class="text-xs font-semibold text-neutral-500 uppercase tracking-wider mb-3">Family Tree</h3>
                <div id="lineage-viz" class="w-full" style="min-height:200px">
                    <div class="flex items-center justify-center h-48 text-neutral-500 text-sm">
                        <span class="animate-pulse">Loading lineage visualization…</span>
                    </div>
                </div>
                <script src="https://d3js.org/d3.v7.min.js"></script>
                <script>
                (function() {{
                    var data = {tree_json};
                    var container = document.getElementById('lineage-viz');
                    if (!container || !data.children || !data.children.length) {{
                        if (container) container.innerHTML = '<div class="flex items-center justify-center h-32 text-neutral-500 text-sm">No lineage tree to display</div>';
                        return;
                    }}
                    var width = container.clientWidth || 600;
                    var height = 200 + data.children.length * 40;

                    var svg = d3.select(container).html('').append('svg')
                        .attr('width', width)
                        .attr('height', height)
                        .style('overflow', 'visible');

                    var g = svg.append('g').attr('transform', 'translate(20,20)');

                    var root = d3.hierarchy(data);
                    var treeLayout = d3.tree().size([width - 60, height - 60]);
                    treeLayout(root);

                    // Links
                    g.selectAll('.link')
                        .data(root.links())
                        .enter().append('path')
                        .attr('class', 'link')
                        .attr('fill', 'none')
                        .attr('stroke', 'rgba(255,255,255,0.08)')
                        .attr('stroke-width', 1.5)
                        .attr('d', d3.linkHorizontal()
                            .x(function(d) {{ return d.y; }})
                            .y(function(d) {{ return d.x; }})
                        );

                    // Nodes
                    var node = g.selectAll('.node')
                        .data(root.descendants())
                        .enter().append('g')
                        .attr('transform', function(d) {{ return 'translate(' + d.y + ',' + d.x + ')'; }});

                    node.append('circle')
                        .attr('r', 4)
                        .attr('fill', function(d) {{
                            if (d.data.type === 'indica') return '#818cf8';
                            if (d.data.type === 'sativa') return '#fb923c';
                            return '#c084fc';
                        }})
                        .attr('stroke', 'rgba(255,255,255,0.1)')
                        .attr('stroke-width', 1);

                    node.append('text')
                        .attr('dx', 10)
                        .attr('dy', 4)
                        .attr('fill', '#ccc')
                        .style('font-size', '12px')
                        .style('font-family', 'Inter, sans-serif')
                        .text(function(d) {{ return d.data.name; }});
                }})();
                </script>
            </div>'''

    elif derived_parents:
        # Lineage read from the description prose (no verified links yet).
        items = ""
        for pname, pstrain in derived_parents:
            safe = html_mod.escape(pname)
            if pstrain:
                items += f'''<li>
                    <a href="/strains/{pstrain.slug or pstrain.id}" class="lineage-tree-node">
                        <span>{pstrain.type_emoji}</span>
                        <span class="font-medium">{safe}</span>
                        <span class="text-xs text-neutral-500">{pstrain.strain_type.title()} · {pstrain.thc_display}</span>
                    </a>
                </li>'''
            else:
                items += f'''<li>
                    <span class="lineage-tree-node opacity-70">
                        <span>🧬</span>
                        <span class="font-medium">{safe}</span>
                        <span class="text-xs text-neutral-500">not in catalog yet</span>
                    </span>
                </li>'''
        cross_str = html_mod.escape(genetics_string([n for n, _ in derived_parents]))
        lineage_html = f'''<div class="mb-8"><h2 class="section-title">Genetic Lineage</h2>
        <div class="bg-elevated border rounded-xl p-6">
            <div class="flex items-center gap-2 mb-4"><span class="pill">🧬 {cross_str}</span></div>
            <div class="lineage-tree"><ul>{items}</ul></div>
            <p class="text-xs text-neutral-500 mt-3">Parsed from this strain's description — not yet verified against a genetics source.</p>
        </div></div>'''
    elif strain.breeder:
        # Show breeder as genetics placeholder
        lineage_html = f'''<div class="mb-8"><h2 class="section-title">Genetic Lineage</h2>
        <div class="bg-elevated border rounded-xl p-6 text-center">
            <p class="text-sm text-neutral-400">Bred by <strong class="text-neutral-200">{strain.breeder}</strong></p>
            <p class="text-xs text-neutral-500 mt-2">Lineage enrichment in progress — parents will appear here as we process genetic data.</p>
        </div></div>'''
    else:
        suggest_block = ""
        if is_logged_in:
            suggest_block = f"""<details class="mt-4 text-left">
                <summary class="text-xs text-weed-400 cursor-pointer hover:underline">🧬 Know the parents? Suggest genetics</summary>
                <form method="post" action="/suggestions/genetics/{strain_id}" class="mt-3 flex flex-wrap gap-2 items-end">
                    <input type="text" name="parent_1" placeholder="Parent 1" required class="w-36 text-sm">
                    <input type="text" name="parent_2" placeholder="Parent 2 (optional)" class="w-36 text-sm">
                    <input type="text" name="notes" placeholder="Source (optional)" class="w-36 text-sm">
                    <button type="submit" class="btn btn-primary text-xs">Submit</button>
                </form>
            </details>"""
        lineage_html = f'''<div class="mb-8"><h2 class="section-title">🌳 Genetic Lineage</h2>
        <div class="bg-elevated border rounded-xl p-6 text-center">
            <div class="text-3xl mb-2 opacity-40">🧬</div>
            <p class="text-sm text-neutral-500">Genetic lineage data not yet available for this strain.</p>
            {suggest_block}
        </div></div>'''

    # ── Reviews ──
    from backend.services.escape import esc
    reviews_html = ""
    for r in reviews:
        reviews_html += f"""<div class="bg-elevated border rounded-xl p-4">
            <div class="flex items-center justify-between mb-2">
                <div class="flex items-center gap-2">
                    <span class="text-sm font-medium">{esc(r.user.display_name if r.user and r.user.display_name else (r.user.username if r.user else 'Anonymous'))}</span>
                    <span class="text-yellow-500">{'★' * r.rating}{'☆' * (5 - r.rating)}</span>
                </div>
                <span class="text-xs text-neutral-500">{r.created_at.strftime('%b %d, %Y') if r.created_at else ''}</span>
            </div>
            {f'<p class="text-sm text-neutral-300 mb-1"><strong>Aroma:</strong> {esc(r.aroma)}</p>' if r.aroma else ''}
            {f'<p class="text-sm text-neutral-300 mb-1"><strong>Flavor:</strong> {esc(r.flavor)}</p>' if r.flavor else ''}
            {f'<p class="text-sm text-neutral-300 mb-1"><strong>Effect:</strong> {esc(r.effect)}</p>' if r.effect else ''}
            {f'<p class="text-sm text-neutral-300 mb-1"><strong>Appearance:</strong> {esc(r.appearance)}</p>' if r.appearance else ''}
            <p class="text-sm text-neutral-400">{esc(r.notes)}</p>
            {f'<p class="text-xs text-neutral-500 mt-2">💨 {esc(r.consumption_method)}{f" · 💰 ${r.price_paid}" if r.price_paid else ""}</p>' if r.consumption_method else ''}
        </div>"""
    if not reviews_html:
        reviews_html = '<p class="text-neutral-500 text-sm italic text-center py-8">No reviews yet.</p>'

    # ── Similar Strains: shared parents > same breeder > same type ──
    similar = []
    seen_ids = {strain_id}

    if parent_links:
        parent_ids = [l.parent_id for l in parent_links]
        sib_result = await db.execute(
            select(StrainLink).where(
                StrainLink.parent_id.in_(parent_ids),
                StrainLink.child_id != strain_id,
            ).limit(60)
        )
        sib_links = sib_result.scalars().all()
        if sib_links:
            sib_ids = []
            for l in sib_links:
                if l.child_id not in seen_ids:
                    seen_ids.add(l.child_id)
                    sib_ids.append(l.child_id)
            if sib_ids:
                sib_strains = (await db.execute(
                    select(Strain).where(Strain.id.in_(sib_ids[:24]))
                )).scalars().all()
                by_id = {s.id: s for s in sib_strains}
                # Order by how many parents they share
                from collections import Counter
                shared_count = {}
                for l in sib_links:
                    if l.child_id in by_id:
                        shared_count[l.child_id] = shared_count.get(l.child_id, 0) + 1
                similar = sorted(by_id.values(), key=lambda s: -shared_count.get(s.id, 0))[:4]

    # 2. Fill with same-breeder top-rated
    if len(similar) < 4 and strain.breeder:
        fill = (await db.execute(
            select(Strain).where(
                (Strain.breeder == strain.breeder) & (~Strain.id.in_(seen_ids))
            ).order_by(Strain.rating.desc()).limit(4 - len(similar))
        )).scalars().all()
        for s in fill:
            if s.id not in seen_ids:
                seen_ids.add(s.id)
                similar.append(s)

    # 3. Final fill: same type, decent rating
    if len(similar) < 4 and strain.strain_type:
        fill = (await db.execute(
            select(Strain).where(
                (Strain.strain_type == strain.strain_type)
                & (~Strain.id.in_(seen_ids))
                & (Strain.image_url != "")
            ).order_by(Strain.rating.desc()).limit(4 - len(similar))
        )).scalars().all()
        for s in fill:
            similar.append(s)

    if similar:
        cards = ""
        for s in similar[:4]:
            img_html = strain_image_html(
                s.image_url, s.name, "w-full aspect-square object-cover rounded-lg", s.type_emoji,
                fallback_class="w-full aspect-square bg-elevated rounded-lg flex items-center justify-center text-4xl",
            )
            if parent_links and any(l.parent_id for l in parent_links) and s.breeder != strain.breeder:
                why = "🧬 shared genetics"
            elif s.breeder == strain.breeder:
                why = "👨‍🌾 same breeder"
            else:
                why = "similar profile"
            cards += f"""<a href="/strains/{s.slug or s.id}" class="strain-card">
                <div class="p-3">
                    <div class="mb-2">{img_html}</div>
                    <h4 class="text-sm font-semibold group-hover:text-weed-400 transition">{s.name}</h4>
                    <div class="text-xs text-neutral-500 mt-0.5">{s.strain_type.title()} · {s.thc_display}</div>
                    <div class="text-[10px] text-neutral-600 mt-1">{why}</div>
                </div>
            </a>"""
        similar_html = f"""<div class="mb-8">
            <h2 class="section-title">Similar Strains</h2>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-3">{cards}</div>
        </div>"""

    # ── Type badge + colors ──
    type_colors = {"indica": ("bg-indica", "text-indigo-300", "Indica"),
                   "sativa": ("bg-sativa", "text-orange-300", "Sativa"),
                   "hybrid": ("bg-hybrid", "text-purple-200", "Hybrid")}
    type_bg, type_text, type_label = type_colors.get(strain.strain_type, ("bg-glass", "text-neutral-300", strain.strain_type.title()))

    # Badges row
    badges = f'<span class="pill {type_bg} {type_text} font-semibold">{type_label}</span>'
    if strain.is_landrace:
        badges += f'<span class="pill bg-amber-900 text-amber-200">🌍 Landrace{f" · {strain.landrace_origin}" if strain.landrace_origin else ""}</span>'
    if strain.genetics:
        badges += f'<span class="pill">🧬 {strain.genetics[:40]}</span>'
    if strain.breeder:
        badges += f'<a href="/strains?breeder={strain.breeder}" class="breeder-badge hover:text-weed-400 transition">👨‍🌾 {strain.breeder[:40]}</a>'

    stars = "★" * round(strain.rating) + "☆" * (5 - round(strain.rating))

    # ── Description (full text, collapsible when long) ──
    desc_html = ""
    if strain.description:
        desc_text = html_mod.escape(strain.description.strip())
        if len(strain.description.strip()) > 300:
            desc_html = f"""<div class="strain-desc">
                <input type="checkbox" id="desc-toggle" class="strain-desc__toggle">
                <p class="strain-desc__text">{desc_text}</p>
                <label for="desc-toggle" class="strain-desc__btn"></label>
            </div>"""
        else:
            desc_html = f'<p class="text-neutral-300 leading-relaxed">{desc_text}</p>'

    # ── THC Meter ──
    thc_pct = 0
    if strain.thc_max:
        thc_pct = min(strain.thc_max * 2, 100)

    # ── Full page ──
    html = render_page(f"""<div class="max-w-5xl mx-auto">

    <!-- Hero Section -->
    <div class="relative overflow-hidden rounded-2xl mb-8 bg-gradient-hero border border-glass">
        <div class="flex flex-col md:flex-row">
            <div class="md:w-2/5 aspect-4/3 md:aspect-auto md:min-h-[400px] relative overflow-hidden">
                {strain_image_html(strain.image_url, strain.name, "w-full h-full object-cover hover:scale-105 transition-transform duration-700", strain.type_emoji, fallback_class="w-full h-full flex items-center justify-center text-8xl bg-elevated")}
            </div>
            <div class="md:w-3/5 p-6 md:p-8 flex flex-col justify-center">
                <div class="flex items-center gap-2 mb-2">{badges}</div>
                <h1 class="text-4xl md:text-5xl font-display text-white mb-2">{strain.name}</h1>
                <div class="flex items-center gap-2 mb-4">
                    <span class="text-yellow-500 text-lg">{stars}</span>
                    <span class="text-neutral-400">{strain.rating} ({int(strain.review_count or 0)} reviews)</span>
                </div>
                {desc_html}
            </div>
        </div>
    </div>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <!-- THC Card -->
        <div class="stat-card">
            <div class="text-3xl font-bold text-weed-400">{strain.thc_display}</div>
            <div class="thc-meter mt-2">
                <div class="thc-meter-fill" style="width:{thc_pct}%"></div>
            </div>
            <div class="text-xs text-neutral-500 mt-2 uppercase tracking-wider">THC</div>
        </div>
        <!-- CBD Card -->
        <div class="stat-card">
            <div class="text-3xl font-bold text-weed-400">{strain.cbd_display}</div>
            <div class="text-xs text-neutral-500 mt-2 uppercase tracking-wider">CBD</div>
        </div>
        <!-- Type Card -->
        <div class="stat-card">
            <div class="text-3xl">{strain.type_emoji}</div>
            <div class="text-xs text-neutral-500 mt-2 uppercase tracking-wider">{strain.strain_type.title()}</div>
            {f'<div class="text-xs text-neutral-500 mt-1">{strain.sativa_pct or "?"}% S / {strain.indica_pct or "?"}% I</div>' if strain.sativa_pct or strain.indica_pct else ''}
        </div>
        <!-- Flowering Card -->
        <div class="stat-card">
            <div class="text-3xl font-bold text-weed-400">{strain.flowering_days or "—"}</div>
            <div class="text-xs text-neutral-500 mt-2 uppercase tracking-wider">Flower Days</div>
            {f'<div class="text-xs text-neutral-500 mt-1 capitalize">{strain.seed_type}</div>' if strain.seed_type else ''}
        </div>
    </div>

    <!-- Effects & Flavors -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        {f'<div><h2 class="section-title">Effects</h2><div class="flex flex-wrap gap-2">{effects_html}</div></div>' if effects else ''}
        {f'<div><h2 class="section-title">Flavors</h2><div class="flex flex-wrap gap-2">{flavors_html}</div></div>' if flavors else ''}
    </div>

    <!-- Terpene Profile -->
    {f'<div class="mb-8"><h2 class="section-title">Terpene Profile</h2><div class="bg-elevated border rounded-xl p-6 space-y-3">{terp_html}</div></div>' if terp_html else ''}

    <!-- Photo Gallery -->
    {gallery_html}

    <!-- Lineage -->
    {lineage_html}

    <!-- Similar Strains -->
    {similar_html if similar else ''}

    <!-- Reviews -->
    <div class="mb-6 flex items-center justify-between">
        <h2 class="section-title mb-0">Reviews ({len(reviews)})</h2>
        {'<a href="/reviews/add/' + strain_id + '" class="btn btn-primary">Write Review</a>' if is_logged_in else '<a href="/auth/login" class="text-weed-400 text-sm hover:underline">Sign in to write a review</a>'}
    </div>
    <div class="space-y-4">{reviews_html}</div>

    </div>

    <!-- Lightbox -->
    <div id="lightbox" class="lightbox" onclick="this.classList.remove('open')">
        <img id="lightbox-img" src="" alt="">
    </div>

    <!-- Upload & Gallery JS -->
    <script>
    async function uploadPhotos(files, strainId) {{
        const zone = document.querySelector('.upload-zone');
        for (const file of files) {{
            const formData = new FormData();
            formData.append('photo', file);
            try {{
                const resp = await fetch('/api/strains/' + strainId + '/photos', {{ method: 'POST', body: formData }});
                if (resp.ok) {{
                    const data = await resp.json();
                    addGalleryImage(data.url);
                }}
            }} catch (e) {{ console.error(e); }}
        }}
        zone.innerHTML = '<div class="text-3xl mb-2 opacity-40">✅</div><p class="text-sm text-neutral-400">Photos uploaded!</p>';
        setTimeout(() => {{
            zone.innerHTML = `<div class="text-3xl mb-2 opacity-40">📷</div>
                <p class="text-sm text-neutral-400">Upload more photos</p>
                <p class="text-xs text-neutral-500 mt-1">JPG, PNG • Max 10MB</p>
                <input type="file" id="photo-upload" accept="image/*" class="hidden" multiple
                       onchange="uploadPhotos(this.files, '{strain_id}')">`;
        }}, 2000);
    }}
    function addGalleryImage(url) {{
        const grid = document.getElementById('gallery-grid');
        const thumbs = grid.querySelector('.gallery-grid-thumbs') || (() => {{
            const d = document.createElement('div');
            d.className = 'gallery-grid-thumbs';
            grid.appendChild(d);
            return d;
        }})();
        const thumb = document.createElement('div');
        thumb.className = 'gallery-thumb';
        thumb.innerHTML = '<img src="' + url + '" class="w-full h-full object-cover" loading="lazy" onclick="openLightbox(\\'' + url + '\\')">';
        thumbs.appendChild(thumb);
    }}
    function openLightbox(url) {{
        document.getElementById('lightbox-img').src = url;
        document.getElementById('lightbox').classList.add('open');
    }}
    </script>""", f"{strain.name} — WEED", request=request)
    return html