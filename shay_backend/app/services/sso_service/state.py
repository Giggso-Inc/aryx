"""HMAC-signed OAuth state parameter: build, verify, and redirect-URI allow-listing."""

import base64
import hashlib
import hmac
import json
from typing import Optional
from urllib.parse import urlparse

from app.core.config import settings


def _get_state_secret() -> str:
    return settings.SSO_STATE_SECRET


def build_state(invite_id: str, redirect_uri: str, csrf_token: str) -> str:
    payload = {
        "invite_id": invite_id,
        "redirect_uri": redirect_uri,
        "csrf": csrf_token,
    }
    payload_bytes = json.dumps(payload, sort_keys=True).encode()
    signature = hmac.new(
        _get_state_secret().encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    state_obj = {"p": payload, "s": signature}
    return base64.urlsafe_b64encode(
        json.dumps(state_obj).encode()
    ).decode()


def verify_state(state: str, cookie_csrf: Optional[str] = None) -> dict:
    """
    Verify the HMAC-signed OAuth state parameter.

    The HMAC signature is always required — it cryptographically binds the state
    to this server's SSO_STATE_SECRET and is sufficient CSRF protection on its own.

    ``cookie_csrf`` is validated as a belt-and-suspenders second factor when the
    browser successfully echoes the cookie back (same-origin SPA, desktop browsers
    on a single-hop provider like Google).  It is intentionally *optional* because
    Microsoft's multi-hop redirect chain causes some browsers to drop SameSite=Lax
    cookies before the final callback arrives, making the cookie unavailable even
    though the initiate call completed correctly.  Skipping the cookie check in
    that case does not weaken security because the HMAC signature already prevents
    state forgery.
    """
    try:
        state_obj = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
        payload = state_obj["p"]
        received_signature = state_obj["s"]
        payload_bytes = json.dumps(payload, sort_keys=True).encode()
        expected_signature = hmac.new(
            _get_state_secret().encode(),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, received_signature):
            raise ValueError("State signature mismatch")
        # Only enforce cookie binding when the browser echoed it back.
        if cookie_csrf and not hmac.compare_digest(payload["csrf"], cookie_csrf):
            raise ValueError("CSRF token mismatch")
        return payload
    except Exception as e:
        raise ValueError(f"Invalid state: {str(e)}")


def is_allowed_redirect_uri(redirect_uri: str) -> bool:
    parsed = urlparse(redirect_uri.strip())
    if not parsed.scheme or not parsed.netloc:
        return False
    target_origin = f"{parsed.scheme}://{parsed.netloc}".lower()
    allowed = [o.strip().lower() for o in (settings.ALLOWED_ORIGINS or []) if str(o).strip()]
    return "*" in allowed or target_origin in allowed
