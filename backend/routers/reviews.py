"""Reviews router — create and list reviews."""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.models.strain import Strain
from backend.models.review import Review
from backend.models.dispensary import Dispensary

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("/add/{strain_id}", response_class=HTMLResponse)
async def add_review_page(strain_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    if not request.state.user_id:
        return RedirectResponse(url="/auth/login", status_code=302)

    result = await db.execute(select(Strain).where(Strain.id == strain_id))
    strain = result.scalar_one_or_none()
    if not strain:
        return HTMLResponse("Strain not found", status_code=404)

    # Get dispensaries for dropdown
    dispo_result = await db.execute(select(Dispensary).limit(50))
    dispos = dispo_result.scalars().all()

    dispo_options = '<option value="">None (home/general)</option>'
    for d in dispos:
        dispo_options += f'<option value="{d.id}">{d.name} — {d.city}, {d.state}</option>'

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Review {strain.name} — WEED</title><link rel="stylesheet" href="/static/css/app.css"></head>
    <body class="bg-black text-white min-h-screen">
    <nav class="bg-neutral-900 border-b border-neutral-800 px-4 py-3">
    <div class="max-w-6xl mx-auto flex items-center justify-between">
        <a href="/" class="text-2xl font-display text-weed-400">🌿 WEED</a>
        <div class="flex items-center gap-4 text-sm">
            <a href="/strains" class="text-neutral-300 hover:text-white transition">Strains</a>
            <a href="/dispensaries" class="text-neutral-300 hover:text-white transition">Dispensaries</a>
            <a href="/auth/logout" class="text-neutral-400 hover:text-white transition">Logout</a>
        </div>
    </div>
    </nav>
    <main class="max-w-2xl mx-auto px-4 py-8">
    <div class="mb-6"><h1 class="text-2xl font-display text-weed-400">Write a Review</h1><p class="text-neutral-400">for <a href="/strains/{strain.id}" class="text-weed-400 hover:underline">{strain.name}</a></p></div>
    <form method="post" action="/reviews/add/{strain_id}" class="space-y-4">
        <div><label class="block text-sm text-neutral-400 mb-1">Rating</label>
        <div class="flex gap-2 text-2xl" id="rating-picker">
            {' '.join(f'<button type="button" class="rating-star text-neutral-600 hover:text-yellow-500 transition" data-val="{i}">★</button>' for i in range(1,6))}
        </div>
        <input type="hidden" name="rating" id="rating-input" value="3"></div>

        <div class="grid grid-cols-2 gap-4">
            <div><label class="block text-sm text-neutral-400 mb-1">Aroma / Nose</label>
            <textarea name="aroma" rows="2" class="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-weed-500" placeholder="Earthy, citrus, pine..."></textarea></div>
            <div><label class="block text-sm text-neutral-400 mb-1">Flavor Profile</label>
            <textarea name="flavor" rows="2" class="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-weed-500" placeholder="Sweet, diesel, berry..."></textarea></div>
        </div>

        <div><label class="block text-sm text-neutral-400 mb-1">Effects</label>
        <textarea name="effect" rows="2" class="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-weed-500" placeholder="Relaxed, euphoric, creative..."></textarea></div>

        <div><label class="block text-sm text-neutral-400 mb-1">Appearance</label>
        <input type="text" name="appearance" class="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-weed-500" placeholder="Frosty trichomes, dense nugs, orange hairs..."></div>

        <div class="grid grid-cols-2 gap-4">
            <div><label class="block text-sm text-neutral-400 mb-1">Consumption Method</label>
            <select name="consumption_method" class="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-weed-500">
                <option value="smoked">💨 Smoked (joint/blunt/bowl)</option>
                <option value="vaped">💨 Vaped</option>
                <option value="edible">🍪 Edible</option>
                <option value="tincture">💧 Tincture</option>
                <option value="topical">🧴 Topical</option>
                <option value="dab">💎 Dab/Concentrate</option>
            </select></div>
            <div><label class="block text-sm text-neutral-400 mb-1">Price Paid ($)</label>
            <input type="number" name="price_paid" step="0.01" min="0" class="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-weed-500"></div>
        </div>

        <div><label class="block text-sm text-neutral-400 mb-1">Dispensary (optional)</label>
        <select name="dispensary_id" class="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-weed-500">{dispo_options}</select></div>

        <div><label class="block text-sm text-neutral-400 mb-1">Notes</label>
        <textarea name="notes" rows="3" class="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-weed-500" placeholder="Overall experience, setting, how it felt..."></textarea></div>

        <button type="submit" class="w-full bg-weed-700 hover:bg-weed-600 py-3 rounded-lg font-medium transition">Submit Review 🌿</button>
    </form>
    </main>
    <script>
    document.querySelectorAll('.rating-star').forEach(function(star) {{
        star.addEventListener('click', function() {{
            var val = parseInt(this.dataset.val);
            document.getElementById('rating-input').value = val;
            document.querySelectorAll('.rating-star').forEach(function(s) {{
                s.classList.toggle('text-yellow-500', parseInt(s.dataset.val) <= val);
                s.classList.toggle('text-neutral-600', parseInt(s.dataset.val) > val);
            }});
        }});
    }});
    // Default to 3
    document.querySelector('.rating-star[data-val="3"]').click();
    </script>
    </body></html>"""
    return html


@router.post("/add/{strain_id}")
async def add_review(
    strain_id: str,
    request: Request,
    rating: int = Form(...),
    aroma: str = Form(""),
    flavor: str = Form(""),
    effect: str = Form(""),
    appearance: str = Form(""),
    consumption_method: str = Form("smoked"),
    price_paid: float = Form(None),
    dispensary_id: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if not request.state.user_id:
        return RedirectResponse(url="/auth/login", status_code=302)

    review = Review(
        strain_id=strain_id,
        user_id=request.state.user_id,
        dispensary_id=dispensary_id or None,
        rating=max(1, min(5, rating)),
        aroma=aroma,
        flavor=flavor,
        effect=effect,
        appearance=appearance,
        consumption_method=consumption_method,
        price_paid=price_paid,
        notes=notes,
    )
    db.add(review)
    await db.commit()
    return RedirectResponse(url=f"/strains/{strain_id}", status_code=302)