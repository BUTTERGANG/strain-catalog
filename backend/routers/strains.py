"""Strains router — catalog, search, detail views with modern image-first design."""

import json
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.models.strain import Strain
from backend.models.review import Review
from backend.templates import render_page

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

    # Effect filter — search within JSON effects array
    if effect_filter:
        query = query.where(Strain.effects.ilike(f"%{effect_filter}%"))

    # Terpene filter — search within JSON terpenes array  
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

    for s in strains:
        effects = s.effect_list
        terps = s.terpene_list
        effects_html = "".join(f'<span class="pill">{e}</span>' for e in effects[:3])
        top_terp = terps[0]["name"].title() if terps else ""
        top_terp_pct = terps[0]["percentage"] if terps else 0
        terp_badge = f'<span class="text-xs text-weed-400">🌿 {top_terp} {top_terp_pct}%</span>' if top_terp else ""

        type_class = f"strain-card-{s.strain_type}" if s.strain_type in ("indica", "sativa", "hybrid") else ""

        img = s.image_url
        image_html = (
            f'<img src="{img}" alt="{s.name}" class="strain-card-image" loading="lazy" onerror="this.parentElement.innerHTML=\'<div class=\\\\\'strain-card-image flex items-center justify-center text-5xl\\\\\'>{s.type_emoji}</div>\'">'
            if img
            else f'<div class="strain-card-image flex items-center justify-center text-5xl">{s.type_emoji}</div>'
        )

        breeder_tag = f'<span class="breeder-badge mt-1">👨‍🌾 {s.breeder[:35]}</span>' if s.breeder else ""
        stars = "★" * round(s.rating) + "☆" * (5 - round(s.rating))

        cards_html += f"""<a href="/strains/{s.id}" class="strain-card {type_class}">
            <div class="relative overflow-hidden">
                {image_html}
                {f'<span class="absolute top-2 right-2 text-xs bg-black/60 backdrop-blur-sm px-2 py-0.5 rounded-full">{s.type_emoji}</span>' if img else ''}
            </div>
            <div class="p-4">
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
            </div>
        </a>"""

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
            <input type="text" name="search" value="{search}" placeholder="Search strains…" class="w-40 md:w-48">
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
        <h1 class="text-3xl font-display text-weed-400">🌿 Strain Catalog</h1>
        <p class="text-neutral-400 mt-1">{total} strain{'s' if total != 1 else ''}</p>
    </div>
    <form method="get" action="/strains" class="mb-6 bg-elevated border border-glass rounded-xl p-4">{filters_html}</form>
    {f'<div class="flex flex-wrap gap-2 mb-4">{active_filters_html}</div>' if active_filters_html else ''}
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">{cards_html}</div>
    {pagination}

    <script>
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


@router.get("/{strain_id}", response_class=HTMLResponse)
async def strain_detail(strain_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Strain).where(Strain.id == strain_id))
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
    terp_html = ""
    if terpenes:
        for t in terpenes:
            pct = t.get("percentage", 0)
            bar_w = min(pct * 2, 100)
            type_class = f"terp-bar-fill-{strain.strain_type}" if strain.strain_type in ("indica", "sativa", "hybrid") else "terp-bar-fill-hybrid"
            terp_html += f"""<div class="flex items-center gap-3">
                <span class="text-sm w-24 capitalize text-neutral-300">{t.get("name","")}</span>
                <div class="terp-bar-track"><div class="terp-bar-fill {type_class}" style="width:{bar_w}%"></div></div>
                <span class="text-xs text-neutral-500 w-8 text-right">{pct}%</span>
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
        <h2 class="section-title">📸 Photos</h2>
        <div class="upload-zone" onclick="document.getElementById('photo-upload').click()">
            <div class="text-3xl mb-2 opacity-40">📷</div>
            <p class="text-sm text-neutral-400">Upload photos of this strain to help the community</p>
            <p class="text-xs text-neutral-500 mt-1">JPG, PNG • Max 10MB</p>
            <input type="file" id="photo-upload" accept="image/*" class="hidden" multiple
                   onchange="uploadPhotos(this.files, '{strain_id}')">
        </div>
        <div id="gallery-grid" class="gallery-grid mt-4">
            <div class="gallery-grid-main bg-glass flex items-center justify-center text-neutral-600">
                {f'<img src="{strain.image_url}" alt="{strain.name}" class="w-full h-full object-cover" id="main-image">' if strain.image_url else f'<span class="text-4xl">{strain.type_emoji}</span>'}
            </div>
        </div>
    </div>"""

    # ── Lineage Tree ──
    lineage_html = ""
    if parent_links or child_links or strain.genetics:
        lineage_html = '<div class="mb-8"><h2 class="section-title">🌳 Genetic Lineage</h2><div class="bg-elevated border rounded-xl p-6">'

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

    elif strain.breeder:
        # Show breeder as genetics placeholder
        lineage_html = f'''<div class="mb-8"><h2 class="section-title">🌳 Genetic Lineage</h2>
        <div class="bg-elevated border rounded-xl p-6 text-center">
            <p class="text-sm text-neutral-400">Bred by <strong class="text-neutral-200">{strain.breeder}</strong></p>
            <p class="text-xs text-neutral-500 mt-2">Lineage enrichment in progress — parents will appear here as we process genetic data.</p>
        </div></div>'''
    else:
        lineage_html = f'''<div class="mb-8"><h2 class="section-title">🌳 Genetic Lineage</h2>
        <div class="bg-elevated border rounded-xl p-6 text-center">
            <div class="text-3xl mb-2 opacity-40">🧬</div>
            <p class="text-sm text-neutral-500">Genetic lineage data not yet available for this strain.</p>
        </div></div>'''

    # ── Reviews ──
    reviews_html = ""
    for r in reviews:
        reviews_html += f"""<div class="bg-elevated border rounded-xl p-4">
            <div class="flex items-center justify-between mb-2">
                <div class="flex items-center gap-2">
                    <span class="text-sm font-medium">{r.user.display_name if r.user else 'Anonymous'}</span>
                    <span class="text-yellow-500">{'★' * r.rating}{'☆' * (5 - r.rating)}</span>
                </div>
                <span class="text-xs text-neutral-500">{r.created_at.strftime('%b %d, %Y') if r.created_at else ''}</span>
            </div>
            {f'<p class="text-sm text-neutral-300 mb-1"><strong>Aroma:</strong> {r.aroma}</p>' if r.aroma else ''}
            {f'<p class="text-sm text-neutral-300 mb-1"><strong>Flavor:</strong> {r.flavor}</p>' if r.flavor else ''}
            {f'<p class="text-sm text-neutral-300 mb-1"><strong>Effect:</strong> {r.effect}</p>' if r.effect else ''}
            <p class="text-sm text-neutral-400">{r.notes}</p>
            {f'<p class="text-xs text-neutral-500 mt-2">💨 {r.consumption_method}{f" · 💰 ${r.price_paid}" if r.price_paid else ""}</p>' if r.consumption_method else ''}
        </div>"""
    if not reviews_html:
        reviews_html = '<p class="text-neutral-500 text-sm italic text-center py-8">No reviews yet.</p>'

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
                {f'<img src="{strain.image_url}" alt="{strain.name}" class="w-full h-full object-cover hover:scale-105 transition-transform duration-700">' if strain.image_url else f'<div class="w-full h-full flex items-center justify-center text-8xl bg-elevated">{strain.type_emoji}</div>'}
            </div>
            <div class="md:w-3/5 p-6 md:p-8 flex flex-col justify-center">
                <div class="flex items-center gap-2 mb-2">{badges}</div>
                <h1 class="text-4xl md:text-5xl font-display text-white mb-2">{strain.name}</h1>
                <div class="flex items-center gap-2 mb-4">
                    <span class="text-yellow-500 text-lg">{stars}</span>
                    <span class="text-neutral-400">{strain.rating} ({int(strain.review_count or 0)} reviews)</span>
                </div>
                {f'<p class="text-neutral-300 leading-relaxed line-clamp-3">{strain.description}</p>' if strain.description else ''}
            </div>
        </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
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
        </div>
    </div>

    <!-- Effects & Flavors -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        {f'<div><h2 class="section-title">⚡ Effects</h2><div class="flex flex-wrap gap-2">{effects_html}</div></div>' if effects else ''}
        {f'<div><h2 class="section-title">👃 Flavors</h2><div class="flex flex-wrap gap-2">{flavors_html}</div></div>' if flavors else ''}
    </div>

    <!-- Terpene Profile -->
    {f'<div class="mb-8"><h2 class="section-title">🧪 Terpene Profile</h2><div class="bg-elevated border rounded-xl p-6 space-y-3">{terp_html}</div></div>' if terp_html else ''}

    <!-- Photo Gallery -->
    {gallery_html}

    <!-- Lineage -->
    {lineage_html}

    <!-- Reviews -->
    <div class="mb-6 flex items-center justify-between">
        <h2 class="section-title mb-0">💬 Reviews ({len(reviews)})</h2>
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