"""
FORM_SCRIPT — the client-side JS behavior for the Odoo credential form
(form_html.py's markup embeds this via a `<script>` placeholder).

Split out of the original form.py (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Wave B4).
"""

FORM_SCRIPT = """\
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
"""
