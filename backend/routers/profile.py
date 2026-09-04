"""Profile router — user dashboard, wishlist, dispensary visits, password reset."""
from fastapi import APIRouter, Request, Depends, Query, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.models.user import User
from backend.models.strain import Strain
from backend.models.wishlist import WishlistItem, DispensaryVisit
from backend.models.review import Review
from backend.services.auth import hash_password, verify_password
from backend.services.email import send_password_reset, create_reset_token, verify_reset_token
from backend.templates import render_page

router = APIRouter(prefix="/profile", tags=["profile"])


def require_auth(request: Request):
    if not request.state.user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    return request.state.user_id


@router.get("", response_class=HTMLResponse)
async def profile_page(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = request.state.user_id
    if not user_id:
        return RedirectResponse(url="/auth/login", status_code=302)

    user = await db.get(User, user_id)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    # Get wishlist
    wishlist_result = await db.execute(
        select(WishlistItem).where(WishlistItem.user_id == user_id).order_by(WishlistItem.created_at.desc())
    )
    wishlist = wishlist_result.scalars().all()

    # Get reviews
    reviews_result = await db.execute(
        select(Review).where(Review.user_id == user_id).order_by(Review.created_at.desc()).limit(10)
    )
    reviews = reviews_result.scalars().all()

    # Get visits
    visits_result = await db.execute(
        select(DispensaryVisit).where(DispensaryVisit.user_id == user_id).order_by(DispensaryVisit.created_at.desc()).limit(10)
    )
    visits = visits_result.scalars().all()

    # Build wishlist cards
    wishlist_html = ""
    for item in wishlist:
        s = item.strain
        if not s:
            continue
        wishlist_html += f"""<a href="/strains/{s.id}" class="strain-card strain-card-{s.strain_type if s.strain_type in ('indica','sativa','hybrid') else 'hybrid'}">
            <div class="p-4">
                <div class="flex items-center justify-between">
                    <h3 class="font-semibold group-hover:text-weed-400 transition">{s.name}</h3>
                    <span class="text-yellow-500 text-xs">{'★' * round(s.rating)}{'☆' * (5 - round(s.rating))}</span>
                </div>
                <div class="text-xs text-neutral-500 mt-1">{s.strain_type.title()} · {s.thc_display}</div>
                <button class="text-xs text-red-400 mt-2 hover:text-red-300" onclick="fetch('/strains/{s.id}/wishlist',{{method:'POST'}}).then(()=>location.reload())">Remove</button>
            </div>
        </a>"""
    if not wishlist_html:
        wishlist_html = '<p class="text-sm text-neutral-500 italic">No saved strains yet. Browse strains and click the heart to save them.</p>'

    # Build reviews list
    reviews_html = ""
    for r in reviews:
        reviews_html += f"""<div class="bg-elevated border rounded-xl p-4">
            <div class="flex items-center justify-between mb-1">
                <a href="/strains/{r.strain.id}" class="font-medium text-sm hover:text-weed-400">{r.strain.name}</a>
                <span class="text-yellow-500 text-xs">{'★' * r.rating}</span>
            </div>
            <p class="text-xs text-neutral-400">{r.consumption_method or ""}</p>
            {f'<p class="text-sm text-neutral-300 mt-1">{r.notes[:200]}</p>' if r.notes else ''}
        </div>"""
    if not reviews_html:
        reviews_html = '<p class="text-sm text-neutral-500 italic">No reviews yet.</p>'

    # Build visits list
    visits_html = ""
    for v in visits:
        d = v.dispensary
        visits_html += f"""<div class="bg-elevated border rounded-xl p-4">
            <div class="flex items-center justify-between">
                <div>
                    <a href="/dispensaries/{d.id}" class="font-medium text-sm hover:text-weed-400">{d.name}</a>
                    <p class="text-xs text-neutral-500">{d.city}, {d.state}</p>
                </div>
                {f'<span class="text-xs text-neutral-500">{v.visit_date.strftime("%b %d, %Y") if v.visit_date else ""}</span>' if v.visit_date else ''}
            </div>
            {f'<p class="text-sm text-neutral-300 mt-2">{v.notes}</p>' if v.notes else ''}
        </div>"""
    if not visits_html:
        visits_html = '<p class="text-sm text-neutral-500 italic">No dispensary visits logged yet.</p>'

    html = render_page(f"""<div class="max-w-4xl mx-auto">
        <div class="mb-8">
            <div class="flex items-center justify-between">
                <div>
                    <h1 class="text-3xl font-display text-weed-400">👤 {user.display_name or user.username}</h1>
                    <p class="text-neutral-500 text-sm">{user.email}</p>
                </div>
                <a href="/auth/logout" class="btn btn-ghost text-sm">Sign Out</a>
            </div>
        </div>

        <div class="mb-8">
            <h2 class="section-title">💾 Saved Strains ({len(wishlist)})</h2>
            <div class="grid grid-cols-2 md:grid-cols-3 gap-3">{wishlist_html}</div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-8 mb-8">
            <div>
                <h2 class="section-title">💬 Reviews ({len(reviews)})</h2>
                <div class="space-y-3">{reviews_html}</div>
            </div>
            <div>
                <h2 class="section-title">📍 Dispensary Visits ({len(visits)})</h2>
                <div class="space-y-3">{visits_html}</div>
            </div>
        </div>
    </div>""", "Profile — WEED", request=request)
    return html


# ── Password Reset ──
@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return render_page("""<div class="max-w-sm mx-auto text-center py-12">
        <p class="text-4xl mb-4">🔑</p>
        <h1 class="text-2xl font-display text-weed-400 mb-2">Forgot Password</h1>
        <p class="text-sm text-neutral-500 mb-6">Enter your email and we'll send a reset link.</p>
        <form method="post" action="/profile/forgot-password" class="space-y-4">
            <div>
                <label class="text-xs text-neutral-500 block mb-1">Email</label>
                <input type="email" name="email" required class="w-full">
            </div>
            <button type="submit" class="btn btn-primary w-full">Send Reset Link</button>
        </form>
        <p class="text-xs text-neutral-600 mt-4"><a href="/auth/login" class="text-weed-400 hover:underline">Back to sign in</a></p>
    </div>""", "Forgot Password — WEED", request=request)


@router.post("/forgot-password")
async def forgot_password(email: str = Form(...), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        token = create_reset_token(user.id, email)
        await send_password_reset(email, token)
    return HTMLResponse("""<div class="max-w-sm mx-auto text-center py-12">
        <p class="text-4xl mb-4">📬</p>
        <h1 class="text-xl font-display text-weed-400 mb-2">Check Your Email</h1>
        <p class="text-sm text-neutral-500">If an account exists with that email, we've sent a reset link.</p>
        <a href="/auth/login" class="btn btn-ghost mt-6">Back to Sign In</a>
    </div>""")


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(token: str = Query(""), request: Request = None):
    data = verify_reset_token(token)
    if not data:
        return HTMLResponse("Invalid or expired reset token", status_code=400)
    return render_page(f"""<div class="max-w-sm mx-auto py-12">
        <h1 class="text-2xl font-display text-weed-400 mb-2 text-center">Reset Password</h1>
        <form method="post" action="/profile/reset-password" class="space-y-4">
            <input type="hidden" name="token" value="{token}">
            <div>
                <label class="text-xs text-neutral-500 block mb-1">New Password</label>
                <input type="password" name="password" required minlength="6" class="w-full">
            </div>
            <button type="submit" class="btn btn-primary w-full">Reset Password</button>
        </form>
    </div>""", "Reset Password — WEED", request=request)


@router.post("/reset-password")
async def reset_password(token: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)):
    data = verify_reset_token(token)
    if not data:
        return HTMLResponse("Invalid or expired reset token", status_code=400)

    user = await db.get(User, data["user_id"])
    if not user:
        return HTMLResponse("User not found", status_code=404)

    user.password_hash = hash_password(password)
    await db.commit()
    return HTMLResponse("""<div class="max-w-sm mx-auto text-center py-12">
        <p class="text-4xl mb-4">✅</p>
        <h1 class="text-xl font-display text-weed-400 mb-2">Password Reset</h1>
        <p class="text-sm text-neutral-500">Your password has been updated.</p>
        <a href="/auth/login" class="btn btn-primary mt-6">Sign In</a>
    </div>""")