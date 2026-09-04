"""Auth utilities: password hashing, session handling."""
import bcrypt
import secrets
from datetime import datetime, timedelta


SESSION_STORE: dict[str, dict] = {}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, pw_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), pw_hash.encode())


def create_session(user_id: str, ttl_hours: int = 24) -> str:
    token = secrets.token_urlsafe(48)
    SESSION_STORE[token] = {
        "user_id": user_id,
        "expires": datetime.utcnow() + timedelta(hours=ttl_hours),
    }
    return token


def get_session(token: str) -> dict | None:
    session = SESSION_STORE.get(token)
    if not session:
        return None
    if datetime.utcnow() > session["expires"]:
        del SESSION_STORE[token]
        return None
    return session


def destroy_session(token: str):
    SESSION_STORE.pop(token, None)