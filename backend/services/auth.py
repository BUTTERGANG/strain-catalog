"""Auth utilities: password hashing, DB-backed sessions.

Sessions are stored in the `sessions` table so they survive restarts
and work across multiple workers. Expired sessions are purged lazily.
"""
import bcrypt
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.session import Session as SessionRow

SESSION_COOKIE = "session"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, pw_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), pw_hash.encode())


async def create_session(db: AsyncSession, user_id: str, ttl_hours: int = 24) -> str:
    """Create a DB-backed session. Returns the token."""
    token = secrets.token_urlsafe(48)
    row = SessionRow(
        token_hash=hash_token(token),
        user_id=user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
    )
    db.add(row)
    await db.commit()
    return token


def hash_token(token: str) -> str:
    """SHA-256 of token — DB leak shouldn't expose live session tokens."""
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


async def get_session_user_id(db: AsyncSession, token: str | None) -> str | None:
    """Resolve a session token to a user_id, or None."""
    if not token:
        return None
    row = (await db.execute(
        select(SessionRow).where(SessionRow.token_hash == hash_token(token))
    )).scalar_one_or_none()
    if not row:
        return None
    if row.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        await db.delete(row)
        await db.commit()
        return None
    return row.user_id


async def destroy_session(db: AsyncSession, token: str | None) -> None:
    if not token:
        return
    await db.execute(delete(SessionRow).where(SessionRow.token_hash == hash_token(token)))
    await db.commit()


async def purge_expired_sessions(db: AsyncSession) -> int:
    """Housekeeping — delete expired rows. Returns count removed."""
    result = await db.execute(
        delete(SessionRow).where(SessionRow.expires_at < datetime.now(timezone.utc))
    )
    await db.commit()
    return result.rowcount or 0