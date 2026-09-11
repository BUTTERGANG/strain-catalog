"""Shared HTML template helpers for WEED routers."""
from urllib.parse import quote
from fastapi import Request

# Single bold leaf mark, used for the nav logo and the favicon. Uses CSS custom
# properties so it inherits the live theme in-page; the favicon (no CSS context)
# gets the same paths with the colors hardcoded instead. A wide serrated fan
# reads fine at 100px+ but blurs into an arrow at 22px nav scale — this single
# asymmetric leaf silhouette stays legible at both sizes.
_LOGO_PATHS = """<path d="M12 2 C16.8 5 18.6 10.2 16.8 15.3 C15.5 19 13.3 20.6 12 20.6
    C10.7 20.6 8.7 19.2 7.6 15.6 C6.2 11 7.7 5.6 12 2 Z" fill="{weed}"/>
    <path d="M12 20.6V23.2" stroke="{ink}" stroke-width="1.4" stroke-linecap="round"/>"""

LOGO_SVG = f'<svg width="22" height="22" viewBox="0 0 24 24" fill="none" style="flex-shrink:0">{_LOGO_PATHS.format(weed="var(--weed)", ink="var(--weed-ink)")}</svg>'

_FAVICON_SVG = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">{_LOGO_PATHS.format(weed="#6fcf6f", ink="#12220f")}</svg>'
FAVICON_LINK = f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,{quote(_FAVICON_SVG)}">'


def strain_image_html(url: str, alt: str, img_class: str, emoji: str, fallback_class: str = "") -> str:
    """<img> with an emoji fallback of the same footprint — used both when image_url
    is empty and swapped in via onerror when a non-empty URL fails to load in the browser."""
    fallback_class = fallback_class or f"{img_class} flex items-center justify-center text-4xl"
    fallback = f'<div class="{fallback_class}">{emoji}</div>'
    if not url:
        return fallback
    escaped_fallback = fallback.replace('"', "&quot;").replace("'", "\\'")
    return (
        f'<img src="{url}" alt="{alt}" class="{img_class}" loading="lazy" '
        f'onerror="this.outerHTML=\'{escaped_fallback}\'">'
    )


def build_nav(request: Request = None) -> str:
    """Shared nav bar — used by render_page and pages that keep custom DOCTYPE wrappers."""
    is_logged_in = request.state.user_id is not None if request else False
    is_admin = getattr(request.state, "is_admin", False) if request else False

    return f"""<nav class="nav-glass px-4 py-3">
        <div class="max-w-6xl mx-auto flex items-center justify-between">
            <a href="/" class="text-2xl font-display text-weed-400" style="display:inline-flex;align-items:center;gap:8px;letter-spacing:0.02em;">
                {LOGO_SVG}
                WEED
            </a>
            <div class="flex items-center gap-4 text-sm">
                <a href="/strains" class="text-neutral-300 hover:text-white transition">Strains</a>
                <a href="/breeders" class="text-neutral-300 hover:text-white transition">Breeders</a>
                <a href="/browse/effects" class="text-neutral-300 hover:text-white transition">Effects</a>
                <a href="/browse/terpenes" class="text-neutral-300 hover:text-white transition">Terpenes</a>
                <a href="/dispensaries" class="text-neutral-300 hover:text-white transition">Dispensaries</a>
                <a href="/map" class="text-neutral-300 hover:text-white transition">Map</a>
                <a href="/seeds" class="text-neutral-300 hover:text-white transition">Seeds</a>
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
    <title>{title}</title>{FAVICON_LINK}<link rel="stylesheet" href="/static/css/app.css">
    <style>.line-clamp-3{{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}}</style>
    </head><body class="min-h-screen">{nav}<main class="max-w-6xl mx-auto px-4 py-8">{content}</main></body></html>"""