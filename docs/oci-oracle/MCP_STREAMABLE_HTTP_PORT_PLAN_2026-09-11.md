# MCP server-side Streamable HTTP transport — port plan (2026-09-11)

Branch: `fix/mcp-streamable-http-transport-2026-09-11` → `dev_oci`
Source commit ported from: `1b269664` (on `dev-rv-msi` and several derived
`fix/*` branches — confirmed **not** an ancestor of `dev_oci`)

## Goal

Swap `/mcp`'s server-side transport in `dev_oci` from
`mcp.server.sse.SseServerTransport` to
`mcp.server.streamable_http_manager.StreamableHTTPSessionManager(stateless=True)`,
matching `dev-rv-msi`'s already-verified fix, adapted to `dev_oci`'s own
post-Phase-2b file split — and, in the same branch, add `--workers 2` to
`docker-compose-oci.yml`'s `api` service, since that setting is only safe
to introduce once the transport no longer has a cross-worker session
registry to desync.

## Why this is one change, not two

`dev-rv-msi`'s `1b269664` bundles two sub-commits: a revert of
`--workers 1` back to `--workers 2` (a *different* compose file,
`docker-compose.yml`, which is out of scope for `dev_oci` — see
"Explicitly out of scope" below), and the actual transport fix. On
`dev_oci`, `docker-compose-oci.yml`'s `api` service currently has **no**
`--workers` flag at all (defaults to 1), so there is no revert to make —
but there is an opportunity: `dev-rv-msi` already live-validated that
`--workers 2` gives real throughput benefit over single-worker, and that
benefit was only blocked by the SSE transport's cross-worker session-registry
race (`SseServerTransport` splits each call into a GET that registers a
`session_id` in an in-process dict and a POST that looks it up — under
multiple workers behind `SO_REUSEPORT`, the two can land on different
processes, and the POST's worker 404s with "Could not find session for ID").

`StreamableHTTPSessionManager(stateless=True)` removes the session
registry entirely — every request is a single self-contained POST, nothing
to register or miss, at any worker count. That means adding `--workers 2`
to `docker-compose-oci.yml` is **only safe once this fix lands in the same
branch** — landing the workers change first (or alone) would actively
introduce the exact race this fix exists to prevent. They ship together
by necessity, not convenience.

## Investigation findings that reshaped this port

All confirmed directly against this `dev_oci` checkout (not assumed from
`dev-rv-msi`'s own commit message):

1. **File layout differs from `1b269664`'s diff.** `_mount_mcp`,
   `_authenticate_mcp`, `_bearer_ok` live in `src/aryx/api/main_mcp.py`
   (split out of `main.py` in this session's own Phase 2b restructuring,
   2026-09-03) — not in `main.py` itself, which now only re-exports them.
   `_lifespan` lives in `src/aryx/api/main_lifespan.py`. The `1b269664`
   diff must be re-split across these two files, not applied as a literal
   patch against `main.py`.
2. **`docker-compose-oci.yml`'s `api` service has no `--workers` flag** —
   confirmed by direct read; defaults to 1 worker. The cross-worker 404 bug
   this fix targets does not currently manifest anywhere in `dev_oci`'s
   world. This port is protocol-correctness / forward-compat plus (per the
   decision above) an enabler for the `--workers 2` throughput win, not a
   fix for something already broken today.
3. **`docker-compose.yml` (the non-OCI local compose file) is out of
   scope for all `dev_oci` planning** — corrected explicitly this session;
   never cite it as motivation or touch it in `dev_oci` branches. Only
   `docker-compose-oci.yml` applies.
4. **`mcp~=1.6` in `requirements.txt`** allows up to `<2.0`; the installed
   version in this environment is `1.12.4`, confirmed via
   `pkgutil.iter_modules` to ship
   `mcp.server.streamable_http_manager.StreamableHTTPSessionManager`. No
   requirements pin change needed. Residual, not chased further: a frozen
   lockfile that resolved to exactly `1.6.0` would need separate
   verification that the module exists that far back — flagged, not
   blocking, since no such lockfile exists in this repo today.
5. **Server-push usage grep, re-run against `dev_oci`'s own
   `src/aryx/mcp/`** (`send_notification`, `progress_notification`,
   `create_message`, `elicit`, `session.send`): zero matches. Confirms
   stateless mode (which gives up server-initiated push) is safe here,
   independent of `dev-rv-msi`'s own equivalent check.
6. **`tests/test_mcp_sse_mount.py`** imports `_mount_mcp` from
   `aryx.api.main` by bare name (re-exported, no patch-surface issue), but
   every test body asserts SSE-specific shape (`SseServerTransport`
   monkeypatch, a `/mcp/messages` `Mount`, `route.methods == {"GET",
   "HEAD"}`) and must be rewritten for streamable-http shape (single
   `Route` with `methods == {"GET", "POST", "DELETE"}`, no `/mcp/messages`
   `Mount`, `app.state.mcp_session_manager` set).

## Dependency map

**Touches:**
- `src/aryx/api/main_mcp.py` — `_mount_mcp` body
- `src/aryx/api/main_lifespan.py` — `_lifespan`, to enter/exit
  `session_manager.run()` around the existing `yield`
- `tests/test_mcp_sse_mount.py` — full rewrite of assertions
- `docker-compose-oci.yml` — `api` service command gains `"--workers",
  "2"`

**Does NOT touch:**
- `src/aryx/api/main.py` (imports/re-exports unchanged)
- `docker-compose.yml` (out of scope for `dev_oci` — see above)
- `sales_streamlit/mcp_client.py` (client-side counterpart, PR #303 /
  commit `0416772c` on `cpq-streamlit-dev`/`cpq-streamlit-oci-dev` — a
  separate, already-identified follow-up, not part of this branch)
- `src/aryx/mcp/sse.py` (the standalone port-8765 service; runs single
  process, was deliberately left untouched by `1b269664` itself, same
  reasoning applies here)

**Breaks if wrong:** any live `/mcp` client mid-port — the transport swap
is a hard break, not additive. Deploying the server-side fix without the
client-side counterpart (or vice versa) breaks every MCP call outright,
not just the racy ones. This branch alone is a **prerequisite**, not a
standalone-deployable improvement — call this out explicitly in the PR
description so it isn't deployed to `dev_oci` production ahead of the
client-side port landing too.

## File structure (target line counts)

| File | Before | After (target) | Change |
|---|---|---|---|
| `src/aryx/api/main_mcp.py` | 109 | ~120 | Replace SSE mount block with stateless streamable-http mount; set `app.state.mcp_session_manager`; single `Route("/mcp", ..., methods=["GET","POST","DELETE"])`; drop the `/mcp/messages` `Mount` |
| `src/aryx/api/main_lifespan.py` | 45 | ~55 | `_lifespan` reads `app.state.mcp_session_manager`, enters/exits its `run()` context |
| `tests/test_mcp_sse_mount.py` | 109 | ~90 | Rewrite all 4 tests for streamable-http shape |
| `docker-compose-oci.yml` | — | — | `api` service command: add `"--workers", "2"` |

All files stay well under the 150-line cap.

## Stack compliance

No new library — `mcp.server.streamable_http_manager` ships in the
already-approved, already-installed `mcp` package (`requirements.txt`
`mcp~=1.6`, installed `1.12.4`).

## Risk flags

- Stateless mode gives up server-initiated push — verified unused twice
  (once on `dev-rv-msi`, once independently here on `dev_oci`).
- This branch is a prerequisite for, not a replacement for, the
  client-side `sales_streamlit/mcp_client.py` port — must not ship to
  `dev_oci` production ahead of that companion change, or `/mcp` breaks
  for every caller.
- `--workers 2` and the transport swap must land together, in this order
  of dependency: transport fix makes workers-2 safe, not the reverse.
- `docker-compose.yml` must not be touched or cited in this branch's
  reasoning — `dev_oci` scope is `docker-compose-oci.yml` only (standing
  rule, corrected this session).

## Explicitly out of scope

- `sales_streamlit/mcp_client.py` client-side transport swap (separate
  follow-up branch)
- Any change to `docker-compose.yml` (not part of `dev_oci`'s world)
- Any change to `src/aryx/mcp/sse.py` (the standalone port-8765 service)

## End state

New branch off latest `dev_oci` (this branch,
`fix/mcp-streamable-http-transport-2026-09-11`, created from
`27a8d39d`), one commit implementing the file structure above, PR opened
against `dev_oci` once implemented and verified.
