"""Dispensary visit logging — check in, note what you bought, link reviews."""
import uuid
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.models.dispensary import Dispensary
from backend.models.wishlist import DispensaryVisit
from backend.templates import render_page

router = APIRouter(prefix="/visits", tags=["visits"])


@router.get("/add/{dispensary_id}", response_class=HTMLResponse)
async def add_visit_page(dispensary_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    if not request.state.user_id:
        return RedirectResponse(url="/auth/login", status_code=302)

    dispo = await db.get(Dispensary, dispensary_id)
    if not dispo:
        return HTMLResponse("Dispensary not found", status_code=404)

    return render_page(f"""<div class="max-w-lg mx-auto">
        <h1 class="text-2xl font-display text-weed-400 mb-1">📍 Log a Visit</h1>
        <p class="text-neutral-400 mb-6">{dispo.name} — {dispo.city}, {dispo.state}</p>
        <form method="post" action="/visits/add/{dispensary_id}" class="space-y-4">
            <div>
                <label class="text-xs text-neutral-500 block mb-1">Visit date</label>
                <input type="date" name="visit_date" value="{datetime.now().strftime('%Y-%m-%d')}" class="w-full">
            </div>
            <div>
                <label class="text-xs text-neutral-500 block mb-1">What did you get? / How was it?</label>
                <textarea name="notes" rows="4" class="w-full" placeholder="Picked up an eighth of Blue Dream, budtender was great, tried their house pre-rolls…"></textarea>
            </div>
            <button type="submit" class="btn btn-primary w-full">📍 Check In</button>
        </form>
        <p class="text-xs text-neutral-600 mt-4">Tip: after checking in, write strain reviews and link them to this visit via the review form's dispensary dropdown.</p>
    </div>""", f"Log Visit — {dispo.name} — WEED", request=request)


@router.post("/add/{dispensary_id}")
async def add_visit(
    dispensary_id: str,
    request: Request,
    visit_date: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    if not request.state.user_id:
        return RedirectResponse(url="/auth/login", status_code=302)

    visit_date_parsed = None
    if visit_date:
        try:
            visit_date_parsed = datetime.strptime(visit_date, "%Y-%m-%d")
        except ValueError:
            pass

    visit = DispensaryVisit(
        user_id=request.state.user_id,
        dispensary_id=dispensary_id,
        visit_date=visit_date_parsed,
        notes=notes or "",
    )
    db.add(visit)
    await db.commit()
    return RedirectResponse(url=f"/dispensaries/{dispensary_id}", status_code=302)