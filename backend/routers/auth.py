"""Auth router — login, register, logout (DB-backed sessions + rate limiting)."""
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db, async_session
from backend.models.user import User
from backend.services.auth import (
    hash_password, verify_password, create_session, destroy_session, SESSION_COOKIE,
)
from backend.middleware import enforce_rate_limit
from backend.config import settings
from backend.templates import render_page, LOGO_SVG

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return render_page(f"""<div class="max-w-sm w-full mx-auto my-16">
        <div class="text-center mb-8"><h1 class="text-4xl font-display text-weed-400" style="display:inline-flex;align-items:center;gap:10px;justify-content:center;">{LOGO_SVG} WEED</h1><p class="text-neutral-400 mt-2">Strain Catalog &amp; Dispensary Finder</p></div>
        <div class="bg-elevated rounded-xl p-6 border border-glass">
        <h2 class="text-lg font-semibold mb-4">Sign In</h2>
        <form method="post" action="/auth/login">
        <div class="mb-4"><label class="block text-sm text-neutral-400 mb-1">Email</label><input type="email" name="email" required class="w-full"></div>
        <div class="mb-4"><label class="block text-sm text-neutral-400 mb-1">Password</label><input type="password" name="password" required class="w-full"></div>
        <button type="submit" class="btn btn-primary w-full">Sign In</button>
        </form>
        <p class="text-center text-sm text-neutral-500 mt-4">No account? <a href="/auth/register" class="text-weed-400 hover:underline">Register</a></p>
        <p class="text-center text-xs text-neutral-600 mt-2"><a href="/profile/forgot-password" class="text-neutral-600 hover:text-weed-400 transition">Forgot password?</a></p>
        </div></div>""", "Sign In — WEED", request=request)


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not enforce_rate_limit(request, settings.rate_limit_login, "login"):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a minute.")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = await create_session(db, user.id, ttl_hours=settings.session_ttl_hours)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE, value=token,
        httponly=True, max_age=settings.session_ttl_hours * 3600,
        secure=settings.secure_cookies, samesite="lax",
    )
    return response


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return render_page(f"""<div class="max-w-sm w-full mx-auto my-16">
        <div class="text-center mb-8"><h1 class="text-4xl font-display text-weed-400" style="display:inline-flex;align-items:center;gap:10px;justify-content:center;">{LOGO_SVG} WEED</h1><p class="text-neutral-400 mt-2">Join the community</p></div>
        <div class="bg-elevated rounded-xl p-6 border border-glass">
        <h2 class="text-lg font-semibold mb-4">Create Account</h2>
        <form method="post" action="/auth/register">
        <div class="mb-4"><label class="block text-sm text-neutral-400 mb-1">Username</label><input type="text" name="username" required class="w-full"></div>
        <div class="mb-4"><label class="block text-sm text-neutral-400 mb-1">Email</label><input type="email" name="email" required class="w-full"></div>
        <div class="mb-4"><label class="block text-sm text-neutral-400 mb-1">Password</label><input type="password" name="password" required minlength="6" class="w-full"></div>
        <button type="submit" class="btn btn-primary w-full">Create Account</button>
        </form>
        <p class="text-center text-sm text-neutral-500 mt-4">Already have an account? <a href="/auth/login" class="text-weed-400 hover:underline">Sign in</a></p>
        </div></div>""", "Register — WEED", request=request)


@router.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not enforce_rate_limit(request, settings.rate_limit_register, "register"):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a minute.")

    username = username.strip()
    email = email.strip().lower()
    if len(username) < 2 or len(username) > 30:
        raise HTTPException(status_code=400, detail="Username must be 2-30 characters")
    if not all(c.isalnum() or c in "_-." for c in username):
        raise HTTPException(status_code=400, detail="Username can only contain letters, numbers, _ - .")

    existing = await db.execute(select(User).where((User.email == email) | (User.username == username)))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email or username already taken")

    user = User(username=username, email=email, password_hash=hash_password(password))
    db.add(user)
    await db.commit()

    token = await create_session(db, user.id, ttl_hours=settings.session_ttl_hours)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE, value=token,
        httponly=True, max_age=settings.session_ttl_hours * 3600,
        secure=settings.secure_cookies, samesite="lax",
    )
    return response


@router.get("/logout")
async def logout(request: Request):
    token = getattr(request.state, "session_token", None)
    async with async_session() as db:
        await destroy_session(db, token)
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    return response