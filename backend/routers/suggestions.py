"""Community genetics suggestions — users propose parents for strains missing lineage.

Flow: user submits {parent_name_1, parent_name_2?, notes} → saved as pending suggestion
→ admin approves in /admin/genetics → approval applies genetics + StrainLink + credit.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db, async_session
from backend.models.strain import Strain
from backend.models.user import User
from backend.services.escape import esc
from backend.middleware import enforce_rate_limit
from backend.templates import render_page
import re
import sqlalchemy as sa
from backend.models.suggestion import GeneticsSuggestion

router = APIRouter(prefix="/suggestions", tags=["suggestions"])


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


@router.post("/genetics/{strain_id}")
async def suggest_genetics(
    strain_id: str,
    request: Request,
    parent_1: str = Form(...),
    parent_2: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """Submit a genetics suggestion (auth required, rate limited)."""
    if not request.state.user_id:
        return JSONResponse({"error": "Sign in to suggest genetics"}, status_code=401)
    if not enforce_rate_limit(request, "10/hour", "suggest-genetics"):
        return JSONResponse({"error": "Too many suggestions — try later"}, status_code=429)

    strain = await db.get(Strain, strain_id)
    if not strain:
        return JSONResponse({"error": "Strain not found"}, status_code=404)

    p1 = parent_1.strip()[:120]
    p2 = parent_2.strip()[:120]
    if not p1:
        return JSONResponse({"error": "At least one parent required"}, status_code=400)

    suggestion = GeneticsSuggestion(
        id=uuid.uuid4().hex[:12],
        strain_id=strain_id,
        user_id=request.state.user_id,
        parent_1=p1,
        parent_2=p2 or None,
        notes=(notes or "").strip()[:500],
        status="pending",
    )
    db.add(suggestion)
    await db.commit()
    return JSONResponse({"ok": True, "message": "Thanks! A moderator will review your suggestion."})


@router.get("/genetics/{strain_id}/status")
async def suggestion_status(strain_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Has this user already suggested genetics for this strain? (for UI gating)"""
    if not request.state.user_id:
        return JSONResponse({"suggested": False})
    row = (await db.execute(
        select(GeneticsSuggestion).where(
            (GeneticsSuggestion.strain_id == strain_id)
            & (GeneticsSuggestion.user_id == request.state.user_id)
        )
    )).scalar_one_or_none()
    return JSONResponse({"suggested": row is not None})


# ── Admin approval UI ──
async def _require_admin(request: Request, db: AsyncSession):
    if not request.state.user_id:
        return None
    user = await db.get(User, request.state.user_id)
    if not user or not user.is_admin:
        return None
    return user


@router.get("/admin", response_class=HTMLResponse)
async def admin_suggestions(request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _require_admin(request, db)
    if not admin:
        return HTMLResponse("Admins only", status_code=403)

    pending = (await db.execute(
        select(GeneticsSuggestion)
        .where(GeneticsSuggestion.status == "pending")
        .order_by(GeneticsSuggestion.created_at.desc())
        .limit(100)
    )).scalars().all()

    approved_count = (await db.execute(
        select(func.count()).select_from(GeneticsSuggestion).where(GeneticsSuggestion.status == "approved")
    )).scalar() or 0

    rows = ""
    for s in pending:
        strain = await db.get(Strain, s.strain_id)
        user = await db.get(User, s.user_id)
        genetics = s.parent_1 + (" x " + s.parent_2 if s.parent_2 else "")
        rows += f"""<div class="bg-elevated border border-glass rounded-xl p-4 mb-3">
            <div class="flex items-center justify-between">
                <div>
                    <a href="/strains/{strain.slug or strain.id}" class="font-semibold text-weed-400 hover:underline">{esc(strain.name)}</a>
                    <span class="text-neutral-500 text-sm"> — suggested genetics: <strong class="text-neutral-200">{esc(genetics)}</strong></span>
                </div>
                <div class="flex gap-2">
                    <button class="btn btn-primary text-xs" onclick="decide('{s.id}', 'approve')">✓ Approve</button>
                    <button class="btn btn-ghost text-xs text-red-400" onclick="decide('{s.id}', 'reject')">✗ Reject</button>
                </div>
            </div>
            <p class="text-xs text-neutral-500 mt-2">by {esc(user.username if user else 'unknown')}
            {f' · "{esc(s.notes)}"' if s.notes else ''}</p>
        </div>"""
    if not rows:
        rows = '<p class="text-neutral-500 italic text-center py-8">No pending suggestions.</p>'

    return render_page(f"""<div class="mb-6 flex items-center justify-between">
        <h1 class="text-2xl font-display text-weed-400">🧬 Genetics Suggestions</h1>
        <div class="text-sm text-neutral-500">{len(pending)} pending · {approved_count} approved</div>
    </div>
    <div>{rows}</div>
    <script>
    async function decide(id, action) {{
        const resp = await fetch('/suggestions/admin/' + id + '/' + action, {{ method: 'POST' }});
        if (resp.ok) location.reload();
        else alert('Failed: ' + await resp.text());
    }}
    </script>
    """, "Admin: Genetics Suggestions — WEED", request=request)


@router.post("/admin/{suggestion_id}/{action}")
async def admin_decide(suggestion_id: str, action: str, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await _require_admin(request, db)
    if not admin:
        return HTMLResponse("Admins only", status_code=403)
    if action not in ("approve", "reject"):
        return HTMLResponse("Bad action", status_code=400)

    s = await db.get(GeneticsSuggestion, suggestion_id)
    if not s or s.status != "pending":
        return HTMLResponse("Not found or already decided", status_code=404)

    if action == "reject":
        s.status = "rejected"
        s.decided_by = admin.id
        await db.commit()
        return HTMLResponse("rejected")

    # Approve: apply genetics + create StrainLinks
    strain = await db.get(Strain, s.strain_id)
    if not strain:
        return HTMLResponse("Strain gone", status_code=404)

    parents = [p for p in [s.parent_1.strip(), (s.parent_2 or "").strip()] if p]
    genetics = " x ".join(parents)

    def norm(name):
        return re.sub(r"[^a-z0-9]", "", name.lower())

    # Only apply if strain has no genetics yet — never overwrite
    if not strain.genetics:
        strain.genetics = genetics[:490]

    # Find/match parent strains — create missing parent stubs if unknown
    from backend.models.lineage import StrainLink
    for pname in parents:
        row = (await db.execute(
            select(Strain).where(sa.func.lower(Strain.name) == pname.lower())
        )).scalars().first()
        if row:
            if row.id != strain.id:
                db.add(StrainLink(
                    id=uuid.uuid4().hex[:12],
                    parent_id=row.id,
                    child_id=strain.id,
                    rel_type="parent",
                    confidence=0.8,
                    source="community_suggestion",
                    notes="",
                ))
        else:
            # Create parent stub so lineage tree can render
            stub = Strain(
                id=uuid.uuid4().hex[:12],
                name=pname,
                strain_type="hybrid",
                source="community_stub",
                slug=re.sub(r"[^a-z0-9]+", "-", pname.lower()).strip("-")[:80] or uuid.uuid4().hex[:8],
            )
            db.add(stub)
            await db.flush()
            db.add(StrainLink(
                id=uuid.uuid4().hex[:12],
                parent_id=stub.id,
                child_id=strain.id,
                rel_type="parent",
                confidence=0.8,
                source="community_suggestion",
                notes="",
            ))

    s.status = "approved"
    s.decided_by = admin.id
    await db.commit()
    return HTMLResponse("approved")