"""Effect & terpene browse pages — every pill becomes a navigation hub."""
import re
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db, async_session
from backend.models.strain import Strain
from sqlalchemy import select
from backend.templates import render_page

router = APIRouter(prefix="/browse", tags=["browse"])

EFFECT_META = {
    "relaxed": ("😌", "Body calm, tension melt, couch-friendly."),
    "happy": ("😊", "Uplifted, giggly, social-buzz territory."),
    "euphoric": ("🌟", "Blissed-out, waves of well-being."),
    "creative": ("🎨", "Ideas flow, music sounds better, projects get started."),
    "energetic": ("⚡", "Get-up-and-go — chores, hikes, daylight strains."),
    "focused": ("🎯", "Locked-in, task-oriented clarity."),
    "hungry": (" munchies", "Appetite on full — medical use for nausea/eating."),
    "sleepy": ("😴", "Heavy lids, nightcap strains, insomnia relief."),
    "aroused": ("🔥", "Warming, sensual, date-night territory."),
    "talkative": ("💬", "Chatty, social-lubricant mode."),
    "uplifted": ("🌤", "Mood brightened, negative loops quieted."),
    "tingly": ("✨", "Spreading body tingle, sensory amplification."),
}

TERP_META = {
    "myrcene": ("🌙", "Earthy, musky. The most common terpene — sedating, 'couch-lock' associated."),
    "limonene": ("🍋", "Citrus peel. Mood-lift, stress relief."),
    "caryophyllene": ("🌶", "Peppery/spicy. Also found in black pepper; anti-inflammatory."),
    "terpinolene": ("🌸", "Floral/herbal, found in ~1 in 10 strains. Heady, multi-effect."),
    "pinene": ("🌲", "Pine. Alertness, memory retention, 'clear-headed'."),
    "linalool": ("🌺", "Floral/lavender. Calming, anti-anxiety association."),
    "humulene": ("🍺", "Hoppy/earthy (also in hops). Appetite suppressant."),
    "ocimene": ("🌿", "Sweet, herbal. Found in mint, parsley."),
    "nerolidol": ("🍎", "Woody, apple-ish. Sedative at higher doses."),
    "camphene": ("❄️", "Cool, pine-like. Cardiovascular research interest."),
    "bisabolol": ("🍯", "Chamomile-like, gentle and calming."),
    "carene": ("🌲", "Sweet pine, resinous. Sometimes 'dry mouth' culprit."),
}

_SLUG2NAME = {}


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


@router.get("/effects", response_class=HTMLResponse)
async def effects_index(request: Request, db: AsyncSession = Depends(get_db)):
    async with async_session() as db:
        rows = (await db.execute(text("SELECT effects FROM strains WHERE effects IS NOT NULL AND effects != '[]'"))).fetchall()
    import json
    counts = {}
    for (raw,) in rows:
        try:
            for e in json.loads(raw):
                key = (e or "").strip().lower()
                if key:
                    counts[key] = counts.get(key, 0) + 1
        except Exception:
            continue
    top = sorted(counts.items(), key=lambda x: -x[1])[:24]
    cards = ""
    for name, n in top:
        emoji, desc = EFFECT_META.get(name.lower(), ("⚡", ""))
        cards += f"""<a href="/browse/effects/{_slugify(name)}" class="strain-card p-5">
            <div class="text-3xl mb-2">{emoji}</div>
            <h3 class="font-semibold group-hover:text-weed-400 transition capitalize">{name}</h3>
            <p class="text-xs text-neutral-500 mt-1">{n:,} strains{f' · {desc}' if desc else ''}</p>
        </a>"""
    return render_page(f"""<div class="mb-6">
        <h1 class="text-3xl font-display text-weed-400">⚡ Browse by Effect</h1>
        <p class="text-neutral-400 mt-1">What are you looking for today?</p>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">{cards}</div>
    """, "Effects — WEED", request=request)


@router.get("/terpenes", response_class=HTMLResponse)
async def terpenes_index(request: Request, db: AsyncSession = Depends(get_db)):
    async with async_session() as db:
        rows = (await db.execute(text("SELECT terpenes FROM strains WHERE terpenes IS NOT NULL AND terpenes != '[]'"))).fetchall()
    import json
    counts = {}
    for (raw,) in rows:
        try:
            for t in json.loads(raw):
                name = (t.get("name") or "").strip().lower()
                if name:
                    counts[name] = counts.get(name, 0) + 1
        except Exception:
            continue
    top = sorted(counts.items(), key=lambda x: -x[1])[:20]
    cards = ""
    for name, n in top:
        emoji, desc = TERP_META.get(name.lower(), ("🧪", ""))
        cards += f"""<a href="/browse/terpenes/{_slugify(name)}" class="strain-card p-5">
            <div class="text-3xl mb-2">{emoji}</div>
            <h3 class="font-semibold group-hover:text-weed-400 transition capitalize">{name}</h3>
            <p class="text-xs text-neutral-500 mt-1">{n:,} strains profiled</p>
            <p class="text-xs text-neutral-600 mt-1">{desc}</p>
        </a>"""
    return render_page(f"""<div class="mb-6">
        <h1 class="text-3xl font-display text-weed-400">🧪 Terpenes</h1>
        <p class="text-neutral-400 mt-1">The aromatic compounds driving each strain's character</p>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">{cards}</div>
    """, "Terpenes — WEED", request=request)


@router.get("/effects/{effect_slug}", response_class=HTMLResponse)
async def effect_page(effect_slug: str, request: Request, page: int = Query(1, ge=1), db: AsyncSession = Depends(get_db)):
    """All strains tagged with an effect."""
    # Match effect inside JSON array (ilike covers "relaxed" inside ["Relaxed","Happy"])
    effect_name = _SLUG2NAME.get(effect_slug, effect_slug.replace("-", " ").title())
    per_page = 48
    where = text("""SELECT id, slug, name, strain_type, thc_display, image_url, rating FROM strains
                    WHERE LOWER(effects) LIKE :pat
                    ORDER BY rating DESC, review_count DESC
                    LIMIT :lim OFFSET :off""")
    async with async_session() as db:
        rows = (await db.execute(text("""
            SELECT id, slug, name, strain_type, thc_min, thc_max, image_url, rating FROM strains
            WHERE LOWER(effects) LIKE :pat
            ORDER BY rating DESC, review_count DESC
            LIMIT :lim OFFSET :off
        """), {"pat": f'%"{effect_name.lower()}"%', "lim": per_page, "off": (page-1)*per_page})).fetchall()
        total = (await db.execute(text(
            "SELECT COUNT(*) FROM strains WHERE LOWER(effects) LIKE :pat"
        ), {"pat": f'%"{effect_name.lower()}"%'})).scalar() or 0

    emoji, desc = EFFECT_META.get(effect_name.lower(), ("⚡", ""))
    cards = ""
    for r in rows:
        rid, slug, name, stype, tmin, tmax, img, rating = r
        thc = f"{tmin}%-{tmax}%" if (tmin and tmax) else (f"{tmin}%+" if tmin else "—")
        image_html = f'<img src="{img}" class="strain-card-image w-full" loading="lazy">' if img else f'<div class="strain-card-image">{ {"indica":"🔵","sativa":"🟠","hybrid":"🟣"}.get(stype, "🟢") }</div>'
        cards += f"""<a href="/strains/{slug or rid}" class="strain-card strain-card-{stype}">
            {image_html}
            <div class="p-4">
                <h3 class="font-semibold group-hover:text-weed-400 transition">{name}</h3>
                <div class="text-xs text-neutral-500 mt-1">{stype.title()} · {f"{tmin}-{tmax}%" if (tmin and tmax) else (f"{tmin}%+" if tmin else "THC ?")}</div>
            </div>
        </a>"""

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

    return render_page(f"""<div class="mb-6">
        <div class="text-5xl mb-2">{emoji}</div>
        <h1 class="text-3xl font-display text-weed-400 capitalize">{effect_name}</h1>
        <p class="text-neutral-400 mt-1">{total:,} strains{f' · {desc}' if desc else ''}</p>
        <a href="/browse/effects" class="text-xs text-neutral-500 hover:text-weed-400 mt-2 inline-block">← all effects</a>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">{cards}</div>
    {pager}
    """, f"{effect_name.title()} strains — WEED", request=request)


@router.get("/terpenes/{terp_slug}", response_class=HTMLResponse)
async def terpene_page(terp_slug: str, request: Request, page: int = Query(1, ge=1), db: AsyncSession = Depends(get_db)):
    terp_name = _SLUG2NAME.get(terp_slug, terp_slug.replace("-", " "))
    per_page = 48
    async with async_session() as db:
        rows = (await db.execute(text("""
            SELECT id, slug, name, strain_type, thc_min, thc_max, image_url, rating, terpenes FROM strains
            WHERE LOWER(terpenes) LIKE :pat
            ORDER BY rating DESC, review_count DESC
            LIMIT :lim OFFSET :off
        """), {"pat": f'%"{terp_name.lower()}"%', "lim": per_page, "off": (page-1)*per_page})).fetchall()
        total = (await db.execute(text(
            "SELECT COUNT(*) FROM strains WHERE LOWER(terpenes) LIKE :pat"
        ), {"pat": f'%"{terp_name.lower()}"%'})).scalar() or 0

    emoji, desc = TERP_META.get(terp_name.lower(), ("🧪", ""))
    cards = ""
    for r in rows:
        rid, slug, name, stype, tmin, tmax, img, rating, terp_raw = r
        # Extract this terp's percentage
        pct = ""
        try:
            import json
            for t in json.loads(terp_raw):
                if (t.get("name") or "").lower() == terp_name.lower():
                    pct = f'{t.get("percentage", "?")}% '
                    break
        except Exception:
            pass
        image_html = f'<img src="{img}" class="strain-card-image w-full" loading="lazy">' if img else f'<div class="strain-card-image">{ {"indica":"🔵","sativa":"🟠","hybrid":"🟣"}.get(stype, "🟢") }</div>'
        cards += f"""<a href="/strains/{slug or rid}" class="strain-card strain-card-{stype}">
            {image_html}
            <div class="p-4">
                <h3 class="font-semibold group-hover:text-weed-400 transition">{name}</h3>
                <div class="text-xs text-weed-400 mt-1">🧪 {pct}{terp_name.title()}</div>
                <div class="text-xs text-neutral-500 mt-1">{stype.title()} · {f"{tmin}-{tmax}%" if (tmin and tmax) else (f"{tmin}%+" if tmin else "THC ?")}</div>
            </div>
        </a>"""

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

    return render_page(f"""<div class="mb-6">
        <div class="text-5xl mb-2">{emoji}</div>
        <h1 class="text-3xl font-display text-weed-400 capitalize">{terp_name}</h1>
        <p class="text-neutral-400 mt-1">{total:,} strains{f' · {desc}' if desc else ''}</p>
        <a href="/browse/terpenes" class="text-xs text-neutral-500 hover:text-weed-400 mt-2 inline-block">← all terpenes</a>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">{cards}</div>
    {pager}
    """, f"{terp_name.title()} strains — WEED", request=request)