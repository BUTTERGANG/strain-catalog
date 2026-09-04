"""AgentMail service — send transactional emails for password reset, verification, etc.

Scaffolding: expects AGENTMAIL_API_KEY and AGENTMAIL_DOMAIN in env/.env.
When keys aren't set, logs to console instead of sending.
"""
import os
import json
from pathlib import Path
from typing import Optional

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent

# Read from .env or environment
AGENTMAIL_API_KEY = os.getenv("AGENTMAIL_API_KEY", "")
AGENTMAIL_DOMAIN = os.getenv("AGENTMAIL_DOMAIN", "")
AGENTMAIL_FROM = os.getenv("AGENTMAIL_FROM", "noreply@weed.app")

# In-memory password reset token store (would use DB in production)
RESET_TOKENS: dict[str, dict] = {}


async def send_email(to: str, subject: str, html_body: str) -> bool:
    """Send an email via AgentMail, or log to console if not configured."""
    if not AGENTMAIL_API_KEY or not AGENTMAIL_DOMAIN:
        print(f"[agentmail] Would send email to {to}")
        print(f"[agentmail] Subject: {subject}")
        print(f"[agentmail] Body: {html_body[:200]}...")
        return True

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://api.agentmail.to/v1/{AGENTMAIL_DOMAIN}/send",
                headers={
                    "Authorization": f"Bearer {AGENTMAIL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": AGENTMAIL_FROM,
                    "to": to,
                    "subject": subject,
                    "html": html_body,
                },
            )
            if resp.status_code == 200:
                return True
            print(f"[agentmail] Send failed: HTTP {resp.status_code}")
            return False
    except Exception as e:
        print(f"[agentmail] Error: {e}")
        return False


def create_reset_token(user_id: str, email: str) -> str:
    """Create a password reset token."""
    import secrets
    token = secrets.token_urlsafe(32)
    RESET_TOKENS[token] = {
        "user_id": user_id,
        "email": email,
    }
    return token


def verify_reset_token(token: str) -> Optional[dict]:
    """Verify a password reset token and return user info."""
    data = RESET_TOKENS.get(token)
    if not data:
        return None
    del RESET_TOKENS[token]  # One-time use
    return data


async def send_password_reset(email: str, token: str) -> bool:
    """Send a password reset email."""
    reset_url = f"http://localhost:8003/auth/reset-password?token={token}"
    html = f"""
    <div style="max-width:480px;margin:0 auto;font-family:system-ui,sans-serif">
        <div style="text-align:center;padding:24px 0">
            <span style="font-size:48px">🌿</span>
            <h1 style="color:#22c55e;margin:0">WEED</h1>
        </div>
        <div style="background:#111;border:1px solid #222;border-radius:12px;padding:24px">
            <h2 style="color:#fff;margin:0 0 12px 0">Password Reset</h2>
            <p style="color:#999;line-height:1.6">Click the button below to reset your password. This link expires in 1 hour.</p>
            <a href="{reset_url}" style="display:inline-block;background:#22c55e;color:#000;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;margin:16px 0">Reset Password</a>
            <p style="color:#666;font-size:12px">If you didn't request this, you can ignore this email.</p>
        </div>
    </div>
    """
    return await send_email(email, "Reset your WEED password", html)