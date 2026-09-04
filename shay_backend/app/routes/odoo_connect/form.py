"""
GET /connect/form — serve the multi-step Odoo credential HTML form.

Split from the original app/routes/odoo_connect.py (Raven style-compliance
pass, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).

STATED EXCEPTION: this file is longer than the ~150-line target because the
bulk of it (_FORM_HTML) is a single cohesive, self-contained HTML/CSS/JS
template string for one page. Splitting the template itself across files
would fragment a single artifact and hurt readability without reducing
real complexity.
"""

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from app.services.sso_service import verify_state

router = APIRouter()

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
