"""AgentMail service — send transactional emails for password reset, verification, etc.

Scaffolding: expects AGENTMAIL_API_KEY and AGENTMAIL_DOMAIN in env/.env.
When keys aren't set, logs to console instead of sending.
"""
import os

import httpx

# Read from .env or environment
AGENTMAIL_API_KEY = os.getenv("AGENTMAIL_API_KEY", "")
AGENTMAIL_DOMAIN = os.getenv("AGENTMAIL_DOMAIN", "")
AGENTMAIL_FROM = os.getenv("AGENTMAIL_FROM", "noreply@weed.app")


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


async def send_password_reset(email: str, token: str) -> bool:
    """Send a password reset email. Token is DB-backed; this just delivers the link."""
    reset_url = f"{os.getenv('SITE_URL', 'http://localhost:8003')}/profile/reset-password?token={token}"
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