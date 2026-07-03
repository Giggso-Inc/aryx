"""
Odoo Connect web form proxy — lets MCP route Odoo workspace connectivity
through a shay_backend-hosted form so credentials never pass through Claude chat.

Flow:
  1. MCP calls GET /api/v1/odoo/connect/initiate?sid=&redirect_uri=
     → shay_backend returns form_url pointing to the multi-step credential form.
  2. User opens form in browser:
       Step 1 — Enter Odoo URL  → POST /api/v1/odoo/connect/verify-url  → returns DB list.
       Step 2 — Pick database (auto-skipped if single).
       Step 3 — Enter username + API key → native form POST to /api/v1/odoo/connect/complete.
  3. shay_backend verifies credentials via orchestrator, then redirects to:
       {mcp_redirect_uri}#odoo_data=<base64url JSON>
  4. MCP's odoo_callback.html reads the fragment, POSTs tokens to /odoo/token.
  5. _odoo_complete picks up the payload and saves the connection.
"""
import base64
import json
import re
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.core.config import settings
from app.services.sso_service import build_state, is_allowed_redirect_uri, verify_state

_SID_RE = re.compile(r'^[A-Za-z0-9_\-]{1,128}$')

# Bearer tokens captured from MCP's initiate call, keyed by sid → (token, created_at).
# Used by the complete endpoint to call the orchestrator with the user's own token.
_TOKEN_TTL_S: int = 600
_sid_token_store: dict[str, tuple[str, float]] = {}


def _prune_token_store() -> None:
    """Remove entries older than _TOKEN_TTL_S seconds."""
    cutoff = time.monotonic() - _TOKEN_TTL_S
    stale = [sid for sid, (_, ts) in _sid_token_store.items() if ts < cutoff]
    for sid in stale:
        _sid_token_store.pop(sid, None)

router = APIRouter(tags=["Odoo Connect"])


def _encode_payload(data: dict) -> str:
    """Encode a dict as base64url JSON (no padding) — same pattern as zoho_connect."""
    return base64.urlsafe_b64encode(
        json.dumps(data, separators=(",", ":")).encode()
    ).decode().rstrip("=")


# ── Initiate ──────────────────────────────────────────────────────────────────

@router.get("/connect/initiate")
async def odoo_connect_initiate(
    request: Request,
    sid: str = Query(..., description="MCP session ID"),
    redirect_uri: str = Query(..., description="MCP odoo callback URL"),
) -> JSONResponse:
    """Return a form_url — the shay_backend-hosted Odoo credential form."""
    if not _SID_RE.match(sid):
        return JSONResponse({"error": "invalid_sid"}, status_code=400)
    if not is_allowed_redirect_uri(redirect_uri):
        return JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)

    # Store the MCP user's Bearer token so the complete endpoint can forward it
    # to the orchestrator — same token already used for all other BE API calls.
    _prune_token_store()
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        _sid_token_store[sid] = (auth_header[len("Bearer "):], time.monotonic())

    csrf_token = secrets.token_urlsafe(32)
    # invite_id slot carries the MCP session ID here (not a user invite UUID).
    state = build_state(invite_id=sid, redirect_uri=redirect_uri, csrf_token=csrf_token)

    base = (settings.SHAY_BE_PUBLIC_URL or str(request.base_url)).rstrip("/")
    form_url = f"{base}/api/v1/odoo/connect/form?state={state}"

    response = JSONResponse({"form_url": form_url})
    response.set_cookie("sso_csrf", csrf_token, max_age=600, httponly=True, samesite="lax")
    return response


# ── Form page ─────────────────────────────────────────────────────────────────

_FORM_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Connect Odoo — Shay</title>
<style>
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f5f5;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
  .card{background:#fff;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,.1);padding:32px;width:100%;max-width:420px}
  h2{margin:0 0 4px;font-size:20px;color:#1a1a2e}
  .sub{color:#666;font-size:14px;margin-bottom:24px}
  label{display:block;font-size:13px;font-weight:600;color:#444;margin-bottom:4px}
  input[type=text],input[type=password],input[type=url]{width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #ddd;border-radius:6px;font-size:14px;outline:none}
  input:focus{border-color:#6c63ff;box-shadow:0 0 0 2px rgba(108,99,255,.15)}
  .btn{width:100%;padding:11px;background:#6c63ff;color:#fff;border:none;border-radius:6px;font-size:15px;font-weight:600;cursor:pointer;margin-top:16px}
  .btn:hover{background:#5a52d5}.btn:disabled{background:#b0addd;cursor:not-allowed}
  .error{color:#d32f2f;font-size:13px;margin-top:8px;display:none}
  .db-list{margin-top:12px;display:flex;flex-direction:column;gap:8px}
  .db-btn{padding:10px 14px;border:2px solid #ddd;border-radius:6px;background:#fff;cursor:pointer;text-align:left;font-size:14px}
  .db-btn:hover{border-color:#6c63ff;background:#faf9ff}
  .step{display:none}.step.active{display:block}
  .spinner{display:inline-block;width:16px;height:16px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin .7s linear infinite;vertical-align:middle;margin-right:6px}
  @keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div class="card">
  <h2>Connect Odoo CRM</h2>
  <p class="sub">Your credentials are verified against your Odoo instance and stored securely in Accsell — not in Claude chat.</p>

  <!-- Step 1: URL -->
  <div id="step1" class="step active">
    <label for="odoo_url">Odoo instance URL</label>
    <input id="odoo_url" type="url" placeholder="https://mycompany.odoo.com" autocomplete="off">
    <div id="err1" class="error"></div>
    <button class="btn" onclick="verifyUrl()">Continue</button>
  </div>

  <!-- Step 2: Database picker -->
  <div id="step2" class="step">
    <label>Select database</label>
    <div id="db-list" class="db-list"></div>
    <div id="err2" class="error"></div>
  </div>

  <!-- Step 3: Credentials (native form — browser follows redirect) -->
  <div id="step3" class="step">
    <form id="cred-form" method="POST" action="/api/v1/odoo/connect/complete">
      <input type="hidden" name="state" id="h_state" value="__STATE__">
      <input type="hidden" name="odoo_url" id="h_url">
      <input type="hidden" name="database" id="h_db">
      <label for="username">Odoo login (email)</label>
      <input id="username" name="username" type="text" placeholder="admin@example.com" autocomplete="username">
      <label for="api_key" style="margin-top:14px">API key <span style="font-weight:400;color:#888">(or password)</span></label>
      <input id="api_key" name="api_key" type="password" placeholder="Odoo API key or password" autocomplete="current-password">
      <div id="err3" class="error"></div>
      <button type="button" class="btn" onclick="submitCreds()">Connect Odoo</button>
    </form>
  </div>

  <!-- Submitting state -->
  <div id="step4" class="step">
    <p style="text-align:center;color:#555"><span class="spinner"></span> Connecting to Odoo, please wait...</p>
  </div>
</div>

<script>
(function() {
  var state  = document.getElementById('h_state').value;
  var baseUrl = '', db = '';

  function show(id) {
    ['step1','step2','step3','step4'].forEach(function(s) {
      document.getElementById(s).classList.remove('active');
    });
    document.getElementById(id).classList.add('active');
  }

  function showErr(id, msg) {
    var el = document.getElementById(id);
    el.textContent = msg;
    el.style.display = 'block';
  }

  function hideErr(id) { document.getElementById(id).style.display = 'none'; }

  window.verifyUrl = function() {
    var url = document.getElementById('odoo_url').value.trim().replace(/\\/+$/, '');
    hideErr('err1');
    if (!url) { showErr('err1', 'Please enter your Odoo URL.'); return; }
    if (!/^https?:\\/\\//.test(url)) { showErr('err1', 'URL must start with https:// or http://'); return; }

    fetch('/api/v1/odoo/connect/verify-url', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({state: state, odoo_url: url})
    })
    .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, d: d}; }); })
    .then(function(res) {
      if (!res.ok) { showErr('err1', res.d.error || 'Could not reach Odoo. Check the URL.'); return; }
      baseUrl = res.d.base_url;
      var dbs = res.d.databases || [];
      if (dbs.length === 1) {
        db = dbs[0];
        document.getElementById('h_url').value = baseUrl;
        document.getElementById('h_db').value = db;
        show('step3');
      } else {
        var list = document.getElementById('db-list');
        list.innerHTML = '';
        dbs.forEach(function(name) {
          var btn = document.createElement('button');
          btn.className = 'db-btn';
          btn.textContent = name;
          btn.onclick = function() {
            db = name;
            document.getElementById('h_url').value = baseUrl;
            document.getElementById('h_db').value = db;
            show('step3');
          };
          list.appendChild(btn);
        });
        show('step2');
      }
    })
    .catch(function() { showErr('err1', 'Network error. Please try again.'); });
  };

  window.submitCreds = function() {
    var u = document.getElementById('username').value.trim();
    var k = document.getElementById('api_key').value.trim();
    hideErr('err3');
    if (!u) { showErr('err3', 'Please enter your Odoo login email.'); return; }
    if (!k) { showErr('err3', 'Please enter your API key or password.'); return; }
    show('step4');
    document.getElementById('cred-form').submit();
  };

  // Enter key on URL field
  document.getElementById('odoo_url').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') verifyUrl();
  });
})();
</script>
</body>
</html>
"""


@router.get("/connect/form")
async def odoo_connect_form(state: str = Query(...)) -> HTMLResponse:
    """Serve the multi-step Odoo credential form."""
    try:
        verify_state(state, cookie_csrf=None)
    except Exception:
        return HTMLResponse(
            "<p style='font-family:sans-serif;padding:32px;color:#c00'>"
            "This link has expired or is invalid. Please start over from Claude.</p>",
            status_code=400,
        )
    return HTMLResponse(_FORM_HTML.replace("__STATE__", state))


# ── URL verification (AJAX) ───────────────────────────────────────────────────

@router.post("/connect/verify-url")
async def odoo_connect_verify_url(request: Request) -> JSONResponse:
    """Validate the Odoo URL and return available databases."""
    _prune_token_store()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)

    state = body.get("state", "")
    odoo_url = (body.get("odoo_url") or "").strip().rstrip("/")

    cookie_csrf = request.cookies.get("sso_csrf")
    try:
        state_data = verify_state(state, cookie_csrf=cookie_csrf)
    except Exception:
        return JSONResponse({"error": "invalid_state"}, status_code=400)

    if not odoo_url.startswith(("https://", "http://")):
        return JSONResponse(
            {"error": "URL must start with https:// or http://"}, status_code=400
        )

    sid = state_data.get("invite_id", "")
    entry = _sid_token_store.get(sid)
    if not entry:
        return JSONResponse({"error": "session_token_missing"}, status_code=401)

    orc_url = settings.ORCHESTRATOR_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=30) as http:
        try:
            resp = await http.post(
                f"{orc_url}/shay/sales/verify_odoo_url",
                json={"odoo_url": odoo_url},
                headers={"Authorization": f"Bearer {entry[0]}"},
            )
            data = resp.json()
        except Exception as exc:
            return JSONResponse(
                {"error": f"Could not reach Odoo — check the URL. ({exc})"}, status_code=502
            )

    if data.get("status") != "success":
        return JSONResponse(
            {"error": data.get("message", "Odoo instance unreachable")}, status_code=400
        )

    databases: list = data.get("data") or []
    if not databases:
        return JSONResponse(
            {"error": "No databases found on this Odoo instance."}, status_code=400
        )

    return JSONResponse({"databases": databases, "base_url": odoo_url})


# ── Complete (native form POST → redirect) ────────────────────────────────────

@router.post("/connect/complete")
async def odoo_connect_complete(
    request: Request,
    state: str = Form(...),
    odoo_url: str = Form(...),
    database: str = Form(...),
    username: str = Form(...),
    api_key: str = Form(...),
) -> RedirectResponse:
    """
    Verify Odoo credentials via orchestrator, then redirect to the MCP callback
    with the connection data encoded in the URL fragment.
    """
    _prune_token_store()
    cookie_csrf = request.cookies.get("sso_csrf")

    try:
        state_data = verify_state(state, cookie_csrf)
    except Exception:
        return HTMLResponse(
            "<p style='font-family:sans-serif;padding:32px;color:#c00'>"
            "Session expired. Please start over from Claude.</p>",
            status_code=400,
        )

    sid = state_data.get("invite_id", "")
    mcp_redirect_uri = state_data.get("redirect_uri", "")

    def _error_redirect(msg: str) -> RedirectResponse:
        fragment = urlencode({"error": msg, "_sid": sid})
        r = RedirectResponse(url=f"{mcp_redirect_uri}#{fragment}", status_code=302)
        r.delete_cookie("sso_csrf")
        return r

    odoo_url = odoo_url.strip().rstrip("/")
    database = database.strip()
    username = username.strip()
    api_key  = api_key.strip()

    if not all([odoo_url, database, username, api_key]):
        return _error_redirect("missing_fields")

    # Retrieve the user's Bearer token captured during initiate and forward it
    # to the orchestrator — same token already used for all other BE API calls.
    entry = _sid_token_store.pop(sid, None)
    user_token = entry[0] if entry else None
    if not user_token:
        return _error_redirect("session_token_missing")

    orc_url = settings.ORCHESTRATOR_URL.rstrip("/")
    orc_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {user_token}",
    }
    async with httpx.AsyncClient(timeout=30) as http:
        try:
            verify_resp = await http.post(
                f"{orc_url}/shay/sales/odoo/verify",
                json={
                    "odoo_url":       odoo_url,
                    "database_name":  database,
                    "username":       username,
                    "api_key":        api_key,
                },
                headers=orc_headers,
            )
            verify_data = verify_resp.json()
        except Exception:
            return _error_redirect("orchestrator_unreachable")

    if verify_data.get("status") != "success":
        return _error_redirect(verify_data.get("message", "authentication_failed"))

    payload = {
        "odoo_url":  odoo_url,
        "database":  database,
        "username":  username,
        "api_key":   api_key,
        "auth_type": "api_key",
        "_sid":      sid,
    }
    odoo_data = _encode_payload(payload)

    response = RedirectResponse(
        url=f"{mcp_redirect_uri}#odoo_data={odoo_data}", status_code=302
    )
    response.delete_cookie("sso_csrf")
    return response
