"""Breeder pages — hub listing + per-breeder catalog."""
import re
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db, async_session
from backend.models.strain import Strain
from backend.templates import render_page, strain_image_html

router = APIRouter(prefix="/breeders", tags=["breeders"])


def _breeder_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


@router.get("", response_class=HTMLResponse)
async def breeder_index(request: Request, q: str = Query(""), db: AsyncSession = Depends(get_db)):
    """Directory of all breeders with strain counts."""
    from sqlalchemy import text
    async with async_session() as db:
        raw_rows = (await db.execute(text("""
            SELECT breeder, COUNT(*) as n, AVG(rating) as avg_rating
            FROM strains
            WHERE breeder IS NOT NULL AND breeder != ''
              AND breeder NOT IN ('Unknown or Legendary', 'Clone Only Strains', 'Unknown')
            GROUP BY breeder
            ORDER BY n DESC
            LIMIT 500
        """))).fetchall()
        # Round in Python — ROUND(double precision, int) isn't portable across
        # Postgres (needs a ::numeric cast) and SQLite (doesn't support casts).
        rows = [(b, n, round(avg, 1) if avg is not None else None) for b, n, avg in raw_rows]

    search = (q or "").lower()
    if search:
        rows = [r for r in rows if search in r[0].lower()]

    cards = ""
    for breeder, n, avg in rows[:200]:
        slug = _breeder_slug(breeder)
        cards += f"""<a href="/breeders/{slug}" class="strain-card p-4">
            <div class="flex items-center justify-between">
                <div>
                    <h3 class="font-semibold group-hover:text-weed-400 transition">👨‍🌾 {breeder}</h3>
                    <p class="text-xs text-neutral-500 mt-1">{n} strain{'s' if n != 1 else ''}{f' · avg ★ {avg}' if avg else ''}</p>
                </div>
                <span class="text-neutral-600">→</span>
            </div>
        </a>"""
    if not cards:
        cards = '<div class="col-span-full text-center py-12 text-neutral-500"><p class="text-4xl mb-2 opacity-40">👨‍🌾</p><p>No breeder data yet.</p><p class="text-sm mt-2">Breeders show up here once strains are enriched with breeder attribution.</p></div>'

    html = render_page(f"""<div class="mb-6">
        <h1 class="text-3xl font-display text-weed-400">👨‍🌾 Breeders</h1>
        <p class="text-neutral-400 mt-1">{len(rows)} breeders — the genetics houses behind the catalog</p>
    </div>
    <form method="get" action="/breeders" class="mb-6">
        <input type="text" name="q" value="{q}" placeholder="Search breeders…" class="w-64">
        <button type="submit" class="btn btn-primary ml-2">Search</button>
    </form>
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">{cards}</div>
    """, "Breeders — WEED", request=request)
    return html


@router.get("/{breeder_slug}", response_class=HTMLResponse)
async def breeder_page(breeder_slug: str, request: Request, page: int = Query(1, ge=1), db: AsyncSession = Depends(get_db)):
    """All strains from one breeder."""
    from sqlalchemy import func as safunc

    # Find breeder name from slug (breeders stored with original casing)
    async with async_session() as db:
        # Distinct breeder names matching the slug
        rows = (await db.execute(text("""
            SELECT DISTINCT breeder FROM strains
            WHERE breeder IS NOT NULL AND breeder != ''
        """))).fetchall()
        match = next((r[0] for r in rows if _breeder_slug(r[0]) == breeder_slug), None)
        if not match:
            return HTMLResponse("Breeder not found", status_code=404)

        per_page = 48
        total = (await db.execute(
            select(safunc.count(Strain.id)).where(Strain.breeder == match)
        )).scalar() or 0

        result = await db.execute(
            select(Strain)
            .where(Strain.breeder == match)
            .order_by(Strain.rating.desc(), Strain.name)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        strains = result.scalars().all()

        # Breeder stats
        stats = (await db.execute(text("""
            SELECT strain_type, COUNT(*) FROM strains WHERE breeder = :b GROUP BY strain_type
        """), {"b": match})).fetchall()
        avg_rating = (await db.execute(
            select(safunc.avg(Strain.rating)).where((Strain.breeder == match) & (Strain.rating > 0))
        )).scalar()

    cards = ""
    for s in strains:
        image_html = strain_image_html(
            s.image_url, s.name, "strain-card-image w-full", s.type_emoji, fallback_class="strain-card-image",
        )
        cards += f"""<a href="/strains/{s.slug or s.id}" class="strain-card strain-card-{s.strain_type}">
            {image_html}
            <div class="p-4">
                <h3 class="font-semibold group-hover:text-weed-400 transition">{s.name}</h3>
                <div class="text-xs text-neutral-500 mt-1">{s.strain_type.title()} · {s.thc_display}</div>
                <div class="text-yellow-500 text-xs mt-1">{'★' * round(s.rating or 0)}{'☆' * (5 - round(s.rating or 0))}</div>
            </div>
        </a>"""

    # Pagination
    import math
    total_pages = math.ceil(total / per_page) if total else 1
    pager = ""
    if total_pages > 1:
        pager = '<div class="flex justify-center gap-2 mt-8">'
        if page > 1:
            pager += f'<a href="?page={page-1}" class="btn btn-ghost text-sm">← Prev</a>'
        if page < total_pages:
            pager += f'<a href="?page={page+1}" class="btn btn-ghost text-sm">Next →</a>'
        pager += "</div>"

    type_dist = " · ".join(f"{n} {t}" for t, n in stats)

    html = render_page(f"""<div class="mb-6">
        <h1 class="text-3xl font-display text-weed-400">👨‍🌾 {match}</h1>
        <p class="text-neutral-400 mt-1">{total} strains{f' · avg ★ {round(avg_rating, 1)}' if avg_rating else ''} · {type_dist}</p>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">{cards}</div>
    {pager}
    """, f"{match} — WEED", request=request)
    return html