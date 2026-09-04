"""Auth router — login, register, logout."""
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.models.user import User
from backend.services.auth import hash_password, verify_password, create_session, destroy_session
from backend.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign In — WEED</title><link rel="stylesheet" href="/static/css/app.css"></head><body class="bg-black text-white min-h-screen flex items-center justify-center">
<div class="max-w-sm w-full mx-4"><div class="text-center mb-8"><h1 class="text-4xl font-display text-weed-400">🌿 WEED</h1><p class="text-neutral-400 mt-2">Strain Catalog &amp; Dispensary Finder</p></div>
<div class="bg-neutral-900 rounded-xl p-6 border border-neutral-800">
<h2 class="text-lg font-semibold mb-4">Sign In</h2>
<form method="post" action="/auth/login">
<div class="mb-4"><label class="block text-sm text-neutral-400 mb-1">Email</label><input type="email" name="email" required class="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-weed-500"></div>
<div class="mb-4"><label class="block text-sm text-neutral-400 mb-1">Password</label><input type="password" name="password" required class="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-weed-500"></div>
<button type="submit" class="w-full bg-weed-600 hover:bg-weed-500 text-white font-medium py-2 rounded-lg transition">Sign In</button>
</form>
<p class="text-center text-sm text-neutral-500 mt-4">No account? <a href="/auth/register" class="text-weed-400 hover:underline">Register</a></p>
<p class="text-center text-xs text-neutral-600 mt-2"><a href="/profile/forgot-password" class="hover:text-weed-400 transition">Forgot password?</a></p>
</div></div></body></html>"""


@router.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_session(user.id, ttl_hours=settings.session_ttl_hours)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(key="session", value=token, httponly=True, max_age=settings.session_ttl_hours * 3600, secure=settings.secure_cookies)
    return response


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Register — WEED</title><link rel="stylesheet" href="/static/css/app.css"></head><body class="bg-black text-white min-h-screen flex items-center justify-center">
<div class="max-w-sm w-full mx-4"><div class="text-center mb-8"><h1 class="text-4xl font-display text-weed-400">🌿 WEED</h1><p class="text-neutral-400 mt-2">Join the community</p></div>
<div class="bg-neutral-900 rounded-xl p-6 border border-neutral-800">
<h2 class="text-lg font-semibold mb-4">Create Account</h2>
<form method="post" action="/auth/register">
<div class="mb-4"><label class="block text-sm text-neutral-400 mb-1">Username</label><input type="text" name="username" required class="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-weed-500"></div>
<div class="mb-4"><label class="block text-sm text-neutral-400 mb-1">Email</label><input type="email" name="email" required class="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-weed-500"></div>
<div class="mb-4"><label class="block text-sm text-neutral-400 mb-1">Password</label><input type="password" name="password" required minlength="6" class="w-full bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-weed-500"></div>
<button type="submit" class="w-full bg-weed-600 hover:bg-weed-500 text-white font-medium py-2 rounded-lg transition">Create Account</button>
</form>
<p class="text-center text-sm text-neutral-500 mt-4">Already have an account? <a href="/auth/login" class="text-weed-400 hover:underline">Sign in</a></p>
</div></div></body></html>"""


@router.post("/register")
async def register(request: Request, username: str = Form(...), email: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)):
    # Check existing
    existing = await db.execute(select(User).where((User.email == email) | (User.username == username)))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email or username already taken")

    user = User(username=username, email=email, password_hash=hash_password(password))
    db.add(user)
    await db.commit()

    token = create_session(user.id, ttl_hours=settings.session_ttl_hours)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(key="session", value=token, httponly=True, max_age=settings.session_ttl_hours * 3600, secure=settings.secure_cookies)
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("session")
    return response