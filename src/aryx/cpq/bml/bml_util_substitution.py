"""`util.getConstraintVals(...)` BML script substitution, split out of
`cpq/engine.py`'s module-level scope (Phase 4, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md -- module-level helper extraction, done
purely to shrink engine.py further). Re-exported from `aryx.cpq.engine`
(see the import there) so every existing `from aryx.cpq.engine import
<name>` caller/test keeps working unchanged. `_fill_signature`,
`_cpq_model_candidates`, and `dt_resolve_whitelist_values` are all looked
up through the engine MODULE object (not imported by name): tests patch
`aryx.cpq.engine._fill_signature`/`._cpq_model_candidates`/
`.dt_resolve_whitelist_values` directly, and a frozen import-time
reference would silently bypass those. Logic unchanged from the original
inline definitions (one genuinely unreachable trailing `return script`
after the function's real `return _result` was dropped as dead code --
it could never execute).
"""

from __future__ import annotations

import re
import time

from aryx.cpq import engine as _engine_module
from aryx.cpq.catalog_profile import resolve_base_model_vn
from aryx.cpq.data_table.data_table_cache import _cache_write_if_marker_unchanged, _invalidate_on_marker_change
from aryx.cpq.engine import (
    _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE,
    _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE_LAST_SEEN_MARKER,
    _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE_TTL_SECONDS,
)

# Matches `put(<dictVar>,"Attribute Variable Name","<attrName>")` -- the
# real BML idiom rule scripts use to name their own target attribute.
# Case/quote-style-tolerant since real scripts vary ("inputparam" vs
# "inputParam", "Attribute Variable Name" is always this exact label
# though -- confirmed across every traced rule).
_UTIL_ATTR_VAR_NAME_RE = re.compile(
    r'put\(\s*\w+\s*,\s*"Attribute Variable Name"\s*,\s*"([^"]+)"\s*\)',
)
# Matches the actual `util.getConstraintVals(<dictVar>, <listVar>)` call
# site to replace -- same idiom every real constraint-rule script uses
# (docs/CPQ_UTIL_LIBRARY_FUNCTION_INVENTORY_2026_08_13.md). This is a
# NATIVE, compiled Oracle Java platform function with no BML source in
# any export ever seen -- the BML evaluator correctly can't execute it and
# returns "unknown" (never guess), which is why a constraint rule calling
# it silently narrows nothing instead of erroring. Confirmed live
# (2026-08-14): "Restrict Model Selection Attributes (Portable)" targeting
# modelSelectionFrequencyBands_astro returns None from
# BmlEvaluator.allowed_values_for_script for exactly this reason, leaving
# the raw catalog menu unfiltered instead of the real, narrowed legal set.
_UTIL_GET_CONSTRAINT_VALS_CALL_RE = re.compile(
    r'util\.getConstraintVals\s*\(\s*\w+\s*,\s*\w+\s*\)',
)


def _substitute_util_get_constraint_vals(
    script: str, filled: dict[str, str],
    workspace_id: int | None, catalog_prefix: str,
    cache: dict[tuple[int, str], tuple] | None,
) -> str:
    """Precompute `util.getConstraintVals(...)` and splice the real,
    ingested legal-value set into `script` as a pipe-delimited string
    literal (the same delimiter convention BmlEvaluator's own Tier-2
    prompt already documents: "determine which values the script allows
    (its returnVal, split on '|')"), so the shared Tier-1/Tier-2 evaluator
    sees a script with NO `util.` reference left and can parse the
    surrounding if/elif chain (or, for the common single-statement idiom,
    the bare `return "<literal>"`) normally instead of being forced to
    Tier-2 LLM guessing purely because of this one call.

    `util.getConstraintVals`'s real backing data (docs/CPQ_UTIL_LIBRARY_
    FUNCTION_INVENTORY_2026_08_13.md) is the same already-ingested
    constraint-shaped Data Table `resolve_whitelist_values` already
    queries for the narrowed-ask/blind-pick paths elsewhere in this file
    (the "Constrain Master String" the real script reads from is itself
    built from these same rows) -- reused directly here rather than
    reimplementing the AND-condition matching a second time.

    Deliberately narrow: only substitutes when (a) the call is present at
    all, (b) the script's own "Attribute Variable Name" param names the
    real target attr, (c) CPQModel/base model both resolve from `filled`,
    and (d) `resolve_whitelist_values` finds real ingested rows for this
    exact (cpq_model, base_model, attr_var_name) combination -- `None` (no
    rows at all, e.g. the confirmed-live APX NEXT Enhanced/Frequency Bands
    gap) leaves the script unchanged, still falling through to Tier-2
    exactly as before; only a genuine `None`-vs-list distinction changes
    behavior, never a guess. An empty list (`[]`, real rows exist but none
    match the current filled context) still substitutes -- a confirmed
    "nothing legal right now" is real information, not an unknown.
    """
    if "util.getConstraintVals" not in script or workspace_id is None:
        return script
    attr_match = _UTIL_ATTR_VAR_NAME_RE.search(script)
    if not attr_match:
        return script
    attr_var_name = attr_match.group(1)
    base_model = filled.get(resolve_base_model_vn(filled, workspace_id, catalog_prefix, cache), "")
    product = filled.get("productSelectionProduct_all", "")
    if not base_model:
        return script

    # 2026-08-28 perf fix: called once per script-backed ConstraintRule on
    # every apply_constraint_rules cache-miss (its own RC6 whole-function
    # cache -- see _constraint_cache -- only avoids re-running this when
    # NOTHING relevant changed; a genuine narrowing/resync still forces a
    # full recompute here). Each call independently re-walks the full
    # _cpq_model_candidates cross-product for its own attr_var_name --
    # confirmed live: this alone cost 82s/59s/37s across 3 passes for APX
    # Next before the per-pass constraint cache stabilized (see the
    # narrowing_rec_rules loop's own comment a few lines below this
    # function's second call site). Memoized here on exactly what
    # resolve_whitelist_values actually reads -- the full `filled` dict
    # (via _row_conditions_match's multi-condition row matching, NOT just
    # base_model/product) -- using the same broad, provably-safe
    # _fill_signature already used elsewhere in this file for this exact
    # class of problem (RC1: a narrower signature risks silently missing a
    # real narrowing). Still a real win: this function is called from two
    # sites within apply_constraint_rules, and apply_constraint_rules
    # itself has 4 call sites across a turn -- an identical (script,
    # filled-state) pair recurring across any of those no longer re-walks
    # the candidate list.
    _cache_key = (
        workspace_id, catalog_prefix, script,
        _engine_module._fill_signature(filled, {}, frozenset()),
    )
    _marker_at_read = _invalidate_on_marker_change(
        _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE,
        _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE_LAST_SEEN_MARKER,
    )
    _hit = _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE.get(_cache_key)
    if _hit is not None:
        _ts, _cached_result = _hit
        if time.monotonic() - _ts < _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE_TTL_SECONDS:
            return _cached_result

    _result = script
    for cpq_model in _engine_module._cpq_model_candidates(
        product, workspace_id, catalog_prefix, cache, base_model=base_model,
    ):
        values = _engine_module.dt_resolve_whitelist_values(
            cpq_model, base_model, attr_var_name, filled, workspace_id, catalog_prefix, cache,
        )
        if values is not None:
            joined = "|".join(values)
            escaped = joined.replace("\\", "\\\\").replace('"', '\\"')
            _result = _UTIL_GET_CONSTRAINT_VALS_CALL_RE.sub(f'"{escaped}"', script)
            break
    _cache_write_if_marker_unchanged(
        _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE, _cache_key, (time.monotonic(), _result), _marker_at_read,
    )
    return _result
