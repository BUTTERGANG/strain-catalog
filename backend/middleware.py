"""Rate limiting and session middleware."""
from functools import wraps
from collections import defaultdict
import time
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from backend.config import settings
from backend.services.auth import get_session

_rl_store: dict[str, list] = defaultdict(list)


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


def get_current_user(request: Request):
    """Extract user_id from session cookie."""
    token = request.cookies.get("session")
    if not token:
        return None
    session = get_session(token)
    if not session:
        return None
    return session["user_id"]


class SessionMiddleware(BaseHTTPMiddleware):
    """Middlewares for session and CSRF."""
    async def dispatch(self, request: Request, call_next):
        request.state.user_id = get_current_user(request)
        response = await call_next(request)
        return response