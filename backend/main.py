"""WEED — main application entry point."""
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func
from backend.config import settings
from backend.database import init_db, get_db, async_session
from backend.models.strain import Strain


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    if settings.auto_seed:
        try:
            from scripts.seed import seed
            await seed()
        except Exception as exc:
            print(f"[startup] auto-seed skipped: {exc}")
    yield


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    debug=settings.debug,
)

# Middleware
from backend.middleware import SessionMiddleware
app.add_middleware(SessionMiddleware)

# Static files
static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Uploads — serve as /uploads/ for cleaner URLs
uploads_dir = Path(settings.upload_dir)
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")


# ── Strain Photo Upload API ──
@app.post("/api/strains/{strain_id}/photos")
async def upload_strain_photo(strain_id: str, photo: UploadFile = File(...)):
    import uuid, shutil

    # Verify strain exists and save photo in one session
    async with async_session() as session:
        result = await session.execute(select(Strain).where(Strain.id == strain_id))
        strain = result.scalar_one_or_none()
        if not strain:
            return JSONResponse({"error": "Strain not found"}, status_code=404)

        ext = Path(photo.filename).suffix if photo.filename else ".jpg"
        filename = f"{strain_id}_{uuid.uuid4().hex[:8]}{ext}"
        filepath = uploads_dir / filename
        with open(filepath, "wb") as f:
            shutil.copyfileobj(photo.file, f)

        # Set as hero if first photo
        if not strain.image_url or "default" in strain.image_url:
            strain.image_url = f"/uploads/{filename}"
            await session.commit()

    return {"url": f"/uploads/{filename}", "filename": filename}


# Import and register routers
from backend.routers import strains, dispensaries, reviews, auth, pages, profile
app.include_router(auth.router)
app.include_router(strains.router)
app.include_router(dispensaries.router)
app.include_router(reviews.router)
app.include_router(pages.router)
app.include_router(profile.router)


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}


@app.get("/api/stats")
async def live_stats(db=Depends(get_db)):
    from backend.models.review import Review
    from backend.models.user import User
    from backend.models.dispensary import Dispensary
    strain_count = (await db.execute(select(func.count()).select_from(Strain))).scalar() or 0
    review_count = (await db.execute(select(func.count()).select_from(Review))).scalar() or 0
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    dispo_count = (await db.execute(select(func.count()).select_from(Dispensary))).scalar() or 0
    return HTMLResponse(f"""<div class="grid grid-cols-4 gap-3 max-w-2xl mx-auto mb-10 text-center" id="live-stats">
        <div class="stat-card"><div class="text-2xl md:text-3xl font-display text-weed-400">{strain_count}</div><div class="text-xs text-neutral-400 uppercase tracking-[0.15em] mt-0.5">Strains</div></div>
        <div class="stat-card"><div class="text-2xl md:text-3xl font-display text-weed-400">{review_count}</div><div class="text-xs text-neutral-400 uppercase tracking-[0.15em] mt-0.5">Reviews</div></div>
        <div class="stat-card"><div class="text-2xl md:text-3xl font-display text-weed-400">{dispo_count}</div><div class="text-xs text-neutral-400 uppercase tracking-[0.15em] mt-0.5">Dispensaries</div></div>
        <div class="stat-card"><div class="text-2xl md:text-3xl font-display text-weed-400">{user_count}</div><div class="text-xs text-neutral-400 uppercase tracking-[0.15em] mt-0.5">Heads</div></div>
    </div>""")