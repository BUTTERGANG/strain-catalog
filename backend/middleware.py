"""Rate limiting and session middleware (DB-backed sessions)."""
from collections import defaultdict
import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from backend.config import settings
from backend.database import async_session
from backend.services.auth import get_session_user_id

_rl_store: dict[str, list] = defaultdict(list)
_rl_persist: dict[str, list] = defaultdict(list)  # survives across workers via DB? no — per-worker, acceptable


def _check_rate_limit(key: str, limit_str: str) -> bool:
    """Check if key is within the rate limit. Returns True if allowed."""
    if settings.test_mode or settings.debug:
        return True
    try:
        count, period = limit_str.split("/")
        count, period = int(count), {"minute": 60, "second": 1}.get(period, 60)
    except (ValueError, KeyError):
        return True

    now = time.time()
    _rl_store[key] = [t for t in _rl_store[key] if now - t < period]
    if len(_rl_store[key]) >= count:
        return False
    _rl_store[key].append(now)
    return True


def client_ip(request: Request) -> str:
    """Best-effort client IP (works behind Replit/Caddy proxy)."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request, limit_str: str, bucket: str) -> bool:
    """Public helper for route-level rate limiting."""
    return _check_rate_limit(f"{bucket}:{client_ip(request)}", limit_str)


class SessionMiddleware(BaseHTTPMiddleware):
    """Resolves the session cookie to request.state.user_id via DB lookup."""

    async def dispatch(self, request: Request, call_next):
        token = request.cookies.get("session")
        user_id = None
        is_admin = False
        if token:
            # One short DB session just for the auth lookup
            async with async_session() as db:
                user_id = await get_session_user_id(db, token)
                if user_id:
                    from backend.models.user import User
                    user = await db.get(User, user_id)
                    is_admin = bool(user and user.is_admin)
        request.state.user_id = user_id
        request.state.is_admin = is_admin
        request.state.session_token = token
        response = await call_next(request)
        return response