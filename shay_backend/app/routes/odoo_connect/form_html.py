"""
FORM_HTML — the multi-step Odoo credential page markup used by form.py's
GET /connect/form endpoint. The client-side JS behavior lives in
form_script.py and is spliced in at the `__SCRIPT__` placeholder below.

Split out of the original form.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

from .form_script import FORM_SCRIPT

FORM_HTML = ("""\
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
__SCRIPT__</script>
</body>
</html>
""" ).replace("__SCRIPT__", FORM_SCRIPT)
