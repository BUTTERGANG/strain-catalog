"""Shared HTML template helpers for WEED routers."""
from fastapi import Request


def build_nav(request: Request = None) -> str:
    """Shared nav bar — used by render_page and pages that keep custom DOCTYPE wrappers."""
    is_logged_in = request.state.user_id is not None if request else False
    is_admin = getattr(request.state, "is_admin", False) if request else False

    return f"""<nav class="nav-glass px-4 py-3">
        <div class="max-w-6xl mx-auto flex items-center justify-between">
            <a href="/" class="text-2xl font-display text-weed-400">🌿 WEED</a>
            <div class="flex items-center gap-4 text-sm">
                <a href="/strains" class="text-neutral-300 hover:text-white transition">Strains</a>
                <a href="/breeders" class="text-neutral-300 hover:text-white transition">Breeders</a>
                <a href="/browse/effects" class="text-neutral-300 hover:text-white transition">Effects</a>
                <a href="/browse/terpenes" class="text-neutral-300 hover:text-white transition">Terpenes</a>
                <a href="/dispensaries" class="text-neutral-300 hover:text-white transition">Dispensaries</a>
                <a href="/map" class="text-neutral-300 hover:text-white transition">Map</a>
                <a href="/seeds" class="text-neutral-300 hover:text-white transition">🌱 Seeds</a>
                {f'<a href="/admin" class="text-weed-500 hover:text-weed-400 transition">🛠</a>' if is_admin else ''}
                {f'<a href="/profile" class="text-neutral-300 hover:text-white transition">Profile</a>' if is_logged_in else ''}
                {'' if is_logged_in else '<a href="/auth/login" class="text-weed-400 hover:underline">Sign In</a>'}
                {f'<a href="/auth/logout" class="text-neutral-400 hover:text-white transition">Logout</a>' if is_logged_in else '<a href="/auth/register" class="btn btn-primary">Join</a>'}
            </div>
        </div>
    </nav>"""


def render_page(content: str, title: str = "WEED", request: Request = None) -> str:
    """Full HTML page wrapper with shared nav and head.

    Both strains.py and pages.py use this instead of duplicating nav HTML.
    """
    nav = build_nav(request)

    return f"""<!DOCTYPE html><html lang="en"><head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{title}</title><link rel="stylesheet" href="/static/css/app.css">
    <style>.line-clamp-3{{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}}</style>
    </head><body class="min-h-screen">{nav}<main class="max-w-6xl mx-auto px-4 py-8">{content}</main></body></html>"""