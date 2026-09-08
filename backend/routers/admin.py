"""Admin panel — data management for the WEED team. Admin-only."""
import re
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func, text, or_
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db, async_session
from backend.models.user import User
from backend.models.strain import Strain
from backend.models.review import Review
from backend.models.dispensary import Dispensary
from backend.services.auth import hash_password
from backend.templates import render_page

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_admin(request: Request, db: AsyncSession):
    if not request.state.user_id:
        return None
    user = await db.get(User, request.state.user_id)
    if not user or not user.is_admin:
        return None
    return user


@router.get("", response_class=HTMLResponse)
async def admin_home(request: Request, db: AsyncSession = Depends(get_db)):
    admin = await require_admin(request, db)
    if not admin:
        return HTMLResponse("Admins only", status_code=403)

    counts = {}
    from sqlalchemy import func as safunc
    for label, model in [("Strains", Strain), ("Reviews", Review), ("Users", User), ("Dispensaries", Dispensary)]:
        counts[label] = (await db.execute(select(safunc.count()).select_from(model))).scalar() or 0

    stats_html = "".join(
        f'<div class="stat-card"><div class="text-3xl font-bold text-weed-400">{n:,}</div><div class="text-xs text-neutral-500 mt-1 uppercase tracking-wider">{label}</div></div>'
        for label, n in counts.items()
    )

    return render_page(f"""<div class="mb-8">
        <h1 class="text-3xl font-display text-weed-400">🛠 Admin</h1>
        <p class="text-neutral-500 text-sm">Signed in as {admin.username}</p>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">{stats_html}</div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <a href="/admin/strains" class="strain-card p-5">
            <h3 class="font-semibold text-lg">🌿 Manage Strains</h3>
            <p class="text-xs text-neutral-500 mt-1">Search, edit, feature, merge, delete</p>
        </a>
        <a href="/admin/users" class="strain-card p-5">
            <h3 class="font-semibold text-lg">👥 Users</h3>
            <p class="text-xs text-neutral-500 mt-1">Promote admins, deactivate accounts</p>
        </a>
        <a href="/suggestions/admin" class="strain-card p-5">
            <h3 class="font-semibold text-lg">🧬 Genetics Suggestions</h3>
            <p class="text-xs text-neutral-500 mt-1">Review community lineage proposals</p>
        </a>
    </div>
    """, "Admin — WEED", request=request)


@router.get("/strains", response_class=HTMLResponse)
async def admin_strains(
    request: Request,
    q: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    admin = await require_admin(request, db)
    if not admin:
        return HTMLResponse("Admins only", status_code=403)

    query = select(Strain)
    if q:
        query = query.where(or_(Strain.name.ilike(f"%{q}%"), Strain.breeder.ilike(f"%{q}%")))
    query = query.order_by(Strain.updated_at.desc()).limit(50)
    strains = (await db.execute(query)).scalars().all()

    rows = ""
    for s in strains:
        feat = "checked" if s.is_featured else ""
        rows += f"""<tr class="border-b border-glass">
            <td class="py-2"><a href="/strains/{s.slug or s.id}" class="text-weed-400 hover:underline">{s.name}</a></td>
            <td class="text-xs text-neutral-500">{s.strain_type}</td>
            <td class="text-xs text-neutral-500">{s.source}</td>
            <td class="text-center">
                <input type="checkbox" class="feat-cb" data-id="{s.id}" {feat} onchange="toggleFeatured(this)" style="accent-color:#22c55e">
            </td>
            <td class="text-center"><a href="/admin/strains/{s.id}/edit" class="text-xs text-weed-400 hover:underline">edit</a></td>
            <td class="text-center"><button class="text-xs text-red-400 hover:text-red-300" onclick="deleteStrain('{s.id}', '{s.name}')">delete</a></td>
        </tr>"""

    return render_page(f"""<div class="mb-6 flex items-center justify-between">
        <h1 class="text-2xl font-display text-weed-400">🌿 Strain Management</h1>
        <a href="/admin" class="btn btn-ghost text-sm">← Admin</a>
    </div>
    <form method="get" action="/admin/strains" class="mb-4 flex gap-2">
        <input type="text" name="q" value="{q}" placeholder="Search strains…" class="w-64">
        <button type="submit" class="btn btn-primary text-sm">Search</button>
    </form>
    <div class="bg-elevated border border-glass rounded-xl overflow-x-auto">
        <table class="w-full text-sm px-4">
            <thead><tr class="text-xs text-neutral-500 uppercase border-b border-glass">
                <th class="text-left py-3">Name</th><th class="text-left">Type</th><th class="text-left">Source</th>
                <th class="text-center">Featured</th><th></th><th></th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>

    <script>
    async function toggleFeatured(cb) {{
        await fetch('/admin/strains/' + cb.dataset.id + '/feature', {{ method: 'POST' }});
    }}
    async function deleteStrain(id, name) {{
        if (!confirm('Delete ' + name + '? This cannot be undone.')) return;
        const resp = await fetch('/admin/strains/' + id + '/delete', {{ method: 'POST' }});
        if (resp.ok) location.reload();
    }}
    </script>
    """, "Admin: Strains — WEED", request=request)


@router.get("/strains/{strain_id}/edit", response_class=HTMLResponse)
async def admin_edit_strain(strain_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await require_admin(request, db)
    if not admin:
        return HTMLResponse("Admins only", status_code=403)

    strain = await db.get(Strain, strain_id)
    if not strain:
        return HTMLResponse("Strain not found", status_code=404)

    return render_page(f"""<div class="max-w-xl mx-auto">
        <h1 class="text-2xl font-display text-weed-400 mb-6">Edit: {strain.name}</h1>
        <form method="post" action="/admin/strains/{strain_id}/edit" class="space-y-4">
            <div><label class="text-xs text-neutral-500 block mb-1">Name</label>
            <input type="text" name="name" value="{strain.name}" class="w-full"></div>
            <div class="grid grid-cols-2 gap-4">
                <div><label class="text-xs text-neutral-500 block mb-1">Type</label>
                <select name="strain_type" class="w-full">
                    {''.join(f'<option value="{t}" {"selected" if strain.strain_type == t else ""}>{t.title()}</option>' for t in ['indica', 'sativa', 'hybrid'])}
                </select></div>
                <div><label class="text-xs text-neutral-500 block mb-1">Breeder</label>
                <input type="text" name="breeder" value="{strain.breeder}" class="w-full"></div>
            </div>
            <div class="grid grid-cols-2 gap-4">
                <div><label class="text-xs text-neutral-500 block mb-1">THC min</label>
                <input type="number" step="0.1" name="thc_min" value="{strain.thc_min or ''}" class="w-full"></div>
                <div><label class="text-xs text-neutral-500 block mb-1">THC max</label>
                <input type="number" step="0.1" name="thc_max" value="{strain.thc_max or ''}" class="w-full"></div>
            </div>
            <div><label class="text-xs text-neutral-500 block mb-1">Genetics</label>
            <input type="text" name="genetics" value="{strain.genetics}" class="w-full"></div>
            <div><label class="text-xs text-neutral-500 block mb-1">Description</label>
            <textarea name="description" rows="4" class="w-full">{strain.description}</textarea></div>
            <div><label class="text-xs text-neutral-500 block mb-1">Image URL</label>
            <input type="text" name="image_url" value="{strain.image_url}" class="w-full"></div>
            <div class="flex gap-3">
                <button type="submit" class="btn btn-primary">Save</button>
                <a href="/admin/strains" class="btn btn-ghost">Cancel</a>
            </div>
        </form>
    </div>""", f"Admin: Edit {strain.name} — WEED", request=request)


@router.post("/strains/{strain_id}/edit")
async def admin_edit_strain_post(
    strain_id: str,
    request: Request,
    name: str = Form(...),
    strain_type: str = Form("hybrid"),
    breeder: str = Form(""),
    thc_min: float = Form(None),
    thc_max: float = Form(None),
    genetics: str = Form(""),
    description: str = Form(""),
    image_url: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    admin = await require_admin(request, db)
    if not admin:
        return HTMLResponse("Admins only", status_code=403)

    strain = await db.get(Strain, strain_id)
    if not strain:
        return HTMLResponse("Not found", status_code=404)

    strain.name = name
    strain.strain_type = strain_type
    strain.breeder = breeder
    strain.thc_min = thc_min
    strain.thc_max = thc_max
    strain.genetics = genetics
    strain.description = description
    strain.image_url = image_url
    await db.commit()
    return RedirectResponse(url="/admin/strains", status_code=302)


@router.post("/strains/{strain_id}/feature")
async def admin_toggle_feature(strain_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await require_admin(request, db)
    if not admin:
        return HTMLResponse("Admins only", status_code=403)
    strain = await db.get(Strain, strain_id)
    if strain:
        strain.is_featured = not strain.is_featured
        await db.commit()
    return {"featured": strain.is_featured if strain else None}


@router.post("/strains/{strain_id}/delete")
async def admin_delete_strain(strain_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await require_admin(request, db)
    if not admin:
        return HTMLResponse("Admins only", status_code=403)
    strain = await db.get(Strain, strain_id)
    if strain:
        # Clean up links first
        from backend.models.lineage import StrainLink
        from sqlalchemy import delete as sa_delete
        await db.execute(sa_delete(StrainLink).where(
            (StrainLink.parent_id == strain_id) | (StrainLink.child_id == strain_id)))
        await db.delete(strain)
        await db.commit()
    return HTMLResponse("deleted")


@router.get("/users", response_class=HTMLResponse)
async def admin_users(request: Request, db: AsyncSession = Depends(get_db)):
    admin = await require_admin(request, db)
    if not admin:
        return HTMLResponse("Admins only", status_code=403)

    users = (await db.execute(select(User).order_by(User.created_at.desc()).limit(200))).scalars().all()
    rows = ""
    for u in users:
        admin_badge = '<span class="pill bg-weed-700 text-xs">admin</span>' if u.is_admin else ""
        toggle = f'<button class="text-xs text-weed-400 hover:underline" onclick="toggleAdmin(\'{u.id}\')">{"revoke" if u.is_admin else "promote"}</button>' if u.id != admin.id else ""
        rows += f"""<tr class="border-b border-glass">
            <td class="py-3">{u.username} {admin_badge}</td>
            <td class="text-xs text-neutral-500">{u.email}</td>
            <td class="text-xs text-neutral-500">{u.created_at.strftime('%b %d, %Y') if u.created_at else ''}</td>
            <td class="text-right">{toggle}</td>
        </tr>"""

    return render_page(f"""<div class="mb-6">
        <h1 class="text-2xl font-display text-weed-400">👥 Users ({len(users)})</h1>
    </div>
    <div class="bg-elevated border border-glass rounded-xl p-4">
        <table class="w-full text-sm">{rows}</table>
    </div>
    <script>
    async function toggleAdmin(id) {{
        await fetch('/admin/users/' + id + '/toggle-admin', {{ method: 'POST' }});
        location.reload();
    }}
    </script>
    """, "Admin: Users — WEED", request=request)


@router.post("/users/{user_id}/toggle-admin")
async def admin_toggle_admin(user_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    admin = await require_admin(request, db)
    if not admin:
        return HTMLResponse("Admins only", status_code=403)
    user = await db.get(User, user_id)
    if user and user.id != admin.id:  # can't demote yourself
        user.is_admin = not user.is_admin
        await db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)