# CPQ Turn Latency Fixes — Correctness Risk Assessment

**Date:** 2026-08-19
**Status:** Risk analysis, companion to `CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md`
**Question this answers:** after implementing both performance root-cause fixes, will
accuracy regress or new attribute-level bugs appear?

**Short answer:** both fixes carry genuine, non-hypothetical correctness risk if
implemented carelessly. Neither is risk-free, and both risks share the same shape —
a cache/gate meant to detect "something changed" quietly failing to notice for one
specific class of change. This document exists so those risks are explicit,
verified where possible, and mitigated by design rather than discovered later in
production.

---

## RC1 fix risk — gating `default_first_available` re-derivation

### The risk

Today's behavior (re-derive an auto-guessed attribute unconditionally on every
pass) is *accidentally* generous: it keeps retrying even when nothing looks
different, which gives it more chances to catch a late-resolving constraint simply
by trying again on a later pass. Gating re-derivation on a narrower "did the input
change" signature removes that safety margin. If the signature is built only from
declarative `constrained_opts` and the REAL narrowing for a given attribute comes
from a script/BML-evaluated rule (not reflected in that signature), the gate will
wrongly conclude "nothing changed" and skip re-deriving — leaving a stale, wrong
guess sitting in `session.filled` for the rest of the turn.

**This is the same failure family as the Package Type bug already fixed this
session** (`docs/CPQ_APX_NEXT_RULE_CATALOG.md`'s "Constraint Package Type Based on
Bundle Type" / ICE-KIT chain — a script-backed dependency that resolves later than
`auto_fill`'s own synchronous declarative check) — just approached from the opposite
direction: that fix stopped the system from *over-asking* about a value it could
already compute; this new risk would be *under-correcting* a value silently, with
no re-ask at all to surface the problem to anyone.

### Mitigation (must be built in, not a follow-up)

- Use a **broad** signature — a hash of `filled`'s full value set, not a narrow
  per-attribute `constrained_opts` snapshot — to minimize false negatives. This
  trades away some of the performance gain for safety margin; a narrower signature
  would save more passes but carries materially higher risk of missing a real
  script-driven change.
- Add a dedicated regression test that replays the exact ICE-KIT/Package-Type
  scenario (and the `extendRangeTo762764MHz_astro` case already cited in
  `engine.py`'s own code comments as a real instance of this pattern) against the
  new gated logic, confirming it still resolves correctly within the same turn —
  not deferred or silently wrong.
- Do not ship the gating change without this test passing; it is the concrete,
  falsifiable proof that the mitigation actually works, not just a design intention.

---

## RC2 fix risk — widening cache TTLs + adding an invalidation hook

### The risk, and what was actually verified

`_TABLES_CACHE` (and its siblings `_VALUE_RULES_CACHE`/`_RULE_JOIN_DATA_CACHE`) are
in-memory, per-process Python dicts. Calling a `_clear_*_cache()` invalidation hook
only clears the cache of the process that runs the hook — if ingestion and API
serving ever run in different processes, an invalidation call would be silently
ineffective for whichever process is actually serving live traffic.

**Verified**: `docker-compose.yml` runs `worker` and `api` as separate containers
(`worker`: `python -m aryx`; `api`: `uvicorn aryx.api.main:app`). Tracing the actual
call site, `ingest_confirmed()` is invoked from `src/aryx/api/doc_discover_api.py:
116`, wired into the `api` service's own router — **not** the worker. So in this
repo's current dev/test topology, ingestion and the cache genuinely share one
process; an invalidation hook placed there would work correctly.

**Not verifiable from this repo alone**: whether production ever runs the `api`
service as **multiple replicas** (common for throughput/HA, not represented in this
single-container dev `docker-compose.yml`). If it does, each replica holds its own
independent in-memory cache. An invalidation call only clears the replica that
happened to handle the ingest request — every other replica keeps serving
potentially stale data until its own TTL naturally expires. This is not a new risk
introduced by this fix — `_VALUE_RULES_CACHE` already has this exact exposure today,
bounded by its existing 30s TTL — but widening any of these TTLs from 30s to
10-15 minutes makes that latent gap 20-30x wider **if** it is ever actually hit in a
multi-replica deployment.

### Mitigation

- Treat the invalidation hook as the **primary** protection, not a nice-to-have
  alongside a long TTL. The hook is what should be doing the real work in the common
  case; the TTL should only be a backstop for whatever the hook doesn't catch.
- Keep the TTL widening **moderate**, not aggressive — long enough to survive normal
  conversational turn pacing (the actual, measured problem — 30s is shorter than
  realistic think-time between turns), not so long that an unverified multi-replica
  staleness window becomes hours instead of minutes if one exists.
- **Open question requiring an answer before implementing**: does production ever
  run the `api` service with more than one replica/worker process? If yes, the
  invalidation hook needs a cross-process mechanism (e.g. a shared flag/timestamp in
  Postgres or Redis that every replica checks, not a same-process function call) —
  a materially larger implementation than the single-process hook currently scoped
  in the performance plan. If no (single replica, as today's docker-compose
  reflects), the hook as scoped is sufficient and this risk doesn't materialize.
  **Answered (2026-08-24, confirmed by the deployment owner): production runs a
  single `api` replica.** The single-process invalidation hook as currently scoped
  is sufficient; the cross-process design is not needed. Re-open this question if
  production topology ever moves to multiple replicas.

---

## Summary table

| Fix | Failure mode if mitigation is skipped | Mitigation | Verified today? |
|---|---|---|---|
| RC1 (gated re-derivation) | Silently stale auto-filled value, no re-ask to surface it | Broad signature (all of `filled`, not one attr's narrow snapshot) + regression test replaying the known script-dependency case | Not yet — mitigation must ship with the fix, proven by the new test |
| RC2 (TTL widen + invalidation) | Stale table/rule data served after a real mid-session re-ingest, for up to the new TTL duration | Invalidation hook as primary defense; keep TTL moderate; confirm single-vs-multi-replica topology first | Same-process topology confirmed in this repo's dev setup; multi-replica production topology is an open question |

## Recommendation

Proceed with both fixes, but only with their respective mitigations included in the
same change (not as follow-ups), and only after getting an answer to the
multi-replica production-topology question — that answer determines whether RC2's
invalidation hook, as currently scoped, is actually sufficient or needs the larger
cross-process design instead.
