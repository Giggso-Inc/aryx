"""HMAC-signed state build/verify for the Salesforce PKCE OAuth flow.

The code_verifier is embedded inside the HMAC-signed state so no
server-side storage is needed for the verifier.

Split from the original app/routes/sf_connect.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
"""

import base64
import hashlib
import hmac
import json

from .state import _get_state_secret


def _build_sf_state(
    sid: str,
    redirect_uri: str,
    csrf_token: str,
    code_verifier: str,
) -> str:
    """Build an HMAC-signed state that carries sid, redirect_uri, csrf, and code_verifier."""
    payload = {
        "invite_id":    sid,
        "redirect_uri": redirect_uri,
        "csrf":         csrf_token,
        "cv":           code_verifier,
    }
    payload_bytes = json.dumps(payload, sort_keys=True).encode()
    signature = hmac.new(
        _get_state_secret().encode(), payload_bytes, hashlib.sha256
    ).hexdigest()
    state_obj = {"p": payload, "s": signature}
    return base64.urlsafe_b64encode(json.dumps(state_obj).encode()).decode()


def _verify_sf_state(state: str, cookie_csrf: str | None) -> dict:
    """Verify and decode the Salesforce HMAC-signed state. Returns the payload dict."""
    try:
        state_obj = json.loads(base64.urlsafe_b64decode(state.encode()).decode())
        payload = state_obj["p"]
        received_sig = state_obj["s"]
        payload_bytes = json.dumps(payload, sort_keys=True).encode()
        expected_sig = hmac.new(
            _get_state_secret().encode(), payload_bytes, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_sig, received_sig):
            raise ValueError("State signature mismatch")
        if cookie_csrf and not hmac.compare_digest(payload["csrf"], cookie_csrf):
            raise ValueError("CSRF token mismatch")
        return payload
    except Exception as e:
        raise ValueError(f"Invalid state: {e}")
