"""Process-wide module-level caches for `cpq/engine.py` (Phase 4, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md -- module-level constant/cache
extraction, done purely to shrink engine.py further). Re-exported from
`aryx.cpq.engine` (see the import there) so every existing `from
aryx.cpq.engine import <name>` caller/test, every `_engine_module.<name>`
whole-module-reference read, and every `patch("aryx.cpq.engine.<name>")`/
`monkeypatch.setattr(engine_mod, "<name>", ...)` dotted-path test patch
keep working unchanged -- these dicts are mutated in place (`.clear()`,
`[key] = ...`) by the modules that actually use them, so re-exporting the
same object here preserves every existing reference. Logic unchanged from
the original inline definitions.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.layout_source import LayoutFileSource, OracleLayoutFileSource

# Process-wide, keyed by (workspace_id, catalog_prefix) — see
# CpqEngine._build_flag_keyword_index. Depends only on the catalog's own
# static rules/attrs, so it's safe to build once per catalog per process
# lifetime rather than re-scanning every BML script on every turn (same
# reasoning as bml.py's _SHARED_SCRIPT_CACHE).
_FLAG_KEYWORD_INDEX_CACHE: dict[tuple[int, str], dict[str, tuple[str, str]]] = {}

# Process-wide, keyed by (workspace_id, catalog_prefix) — see
# CpqEngine._detect_layout_tier / resolve_ui_layout_scope
# (docs/CPQ_LAYOUT_VISIBILITY_FLOW_PLAN.md). Layout placement is static
# ingested data, safe to compute once per catalog per process lifetime.
_LAYOUT_TIER_CACHE: dict[tuple[int, str], int] = {}
_LAYOUT_SCOPE_CACHE: dict[tuple[int, str], dict[str, Any] | None] = {}

# docs/CPQ_LAYOUT_TXT_VISIBILITY_ORDER_PLAN.md — {variable_name: rank} for a
# catalog's decoded native-UI layout export (distinct from the above: this
# carries the `hide` bit and document order the raw relational layout
# tables never decoded). Same process-lifetime caching rationale.
_LAYOUT_COMPONENTS_CACHE: dict[tuple[int, str], list[dict[str, Any]] | None] = {}
_LAYOUT_DISPLAY_ORDER_CACHE: dict[tuple[int, str], dict[str, int] | None] = {}
_LAYOUT_FULL_ORDER_CACHE: dict[tuple[int, str], dict[str, int] | None] = {}
# The three above are keyed by `layout_source.layout_cache_key`: (workspace_id,
# catalog_prefix) for the sentinel variant (unchanged), plus the variant for
# any other. Variant-choice caches (cpq_layout_variants_enabled): all keyed
# (workspace_id, catalog_prefix[, variant]) so invalidation clears the prefix.
_LAYOUT_VARIANT_KEYS_CACHE: dict[tuple[int, str], list[str]] = {}
_LAYOUT_FLOW_MAP_CACHE: dict[tuple[int, str], dict[str, frozenset[str]]] = {}
_LAYOUT_CONTROLSET_CACHE: dict[tuple[int, str, str], frozenset[str]] = {}


def _resolve_layout_file_source() -> LayoutFileSource:
    """CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md Phase 5:
    Oracle ADB / Postgres is now the only backend -- the local-directory
    fallback and its env-var toggle are gone. `OracleLayoutFileSource`
    itself defers opening a connection pool to its first real `.get()`
    call (see its own docstring), so constructing it here at module-
    import time is safe even in environments with no live database."""
    from aryx.config import get_settings  # noqa: PLC0415
    return OracleLayoutFileSource(dsn=get_settings().effective_dsn())


_DEFAULT_LAYOUT_FILE_SOURCE: LayoutFileSource = _resolve_layout_file_source()


def invalidate_layout_cache(workspace_id: int, catalog_prefix: str) -> None:
    """Drop the process-lifetime layout caches for one (workspace_id,
    catalog_prefix) pair. Called by `cpq_ingestion.layout_store.
    store_layout_file()` right after a successful upsert -- without this,
    an uploaded layout replacing an already-queried pair would keep
    serving the OLD (or None) cached value for the rest of this process's
    lifetime, since these caches have no TTL and no other invalidation
    path (see CPQ_LAYOUT_FILE_STORAGE_MIGRATION_PLAN_2026-09-30.md)."""
    key = (workspace_id, catalog_prefix)
    for cache in (
        _LAYOUT_COMPONENTS_CACHE, _LAYOUT_DISPLAY_ORDER_CACHE,
        _LAYOUT_FULL_ORDER_CACHE, _LAYOUT_VARIANT_KEYS_CACHE,
        _LAYOUT_FLOW_MAP_CACHE, _LAYOUT_CONTROLSET_CACHE,
    ):
        # Every variant of the prefix: the sentinel's 2-tuple key and the
        # 3-tuple (workspace_id, catalog_prefix, variant) keys.
        for stale in [k for k in cache if k[:2] == key]:
            cache.pop(stale, None)

# docs/CPQ_RULE_JOIN_DATA_CACHING_PERFORMANCE_PLAN_2026_08_10.md — module-
# level, short-TTL cache for CpqEngine._load_rule_join_data, keyed by
# (workspace_id, catalog_prefix). Mirrors data_table_resolver._TABLES_CACHE
# exactly (same problem, same fix): confirmed live a single /ask HTTP
# request calls load_hiding_rules() + load_recommendation_and_constraint_
# rules() + load_validation_rules() back to back, each independently
# re-running the same 4 join-table queries from scratch -- 3+ full re-fetches
# of ~1,300 rules' worth of join data from ONE block of code, in every turn,
# with 14 total call sites across ask_api.py. A short TTL (rather than pure
# process-lifetime) keeps this safe against rule data being re-ingested
# mid-session.
_RULE_JOIN_DATA_CACHE: dict[tuple[int, str], tuple[float, tuple]] = {}
# docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md -- widened from 30.0.
# 30s is shorter than realistic time between two conversational turns (a
# customer reading a question and typing a reply), so this cache was almost
# never actually hit across turns in practice, only within one turn's own
# back-to-back call sites. The staleness risk this TTL guards against (a
# mid-session rule re-ingest) is an occasional admin action, not something
# that happens every 30s -- 300s is a real cross-turn win while still
# bounding staleness to 5 minutes worst-case if the invalidation hook
# (doc_discovery.ingest_confirmed) is ever bypassed.
_RULE_JOIN_DATA_CACHE_TTL_SECONDS = 300.0


def _clear_rule_join_data_cache() -> None:
    """Test-isolation hook -- call from an autouse fixture to prevent this
    process-lifetime cache from leaking fake/monkeypatched rule data
    between tests that reuse the same (workspace_id, catalog_prefix) key.
    Mirrors data_table_resolver._clear_tables_cache."""
    _RULE_JOIN_DATA_CACHE.clear()


# 2026-08-18 perf fix: _load_value_rules' own raw-data dependency
# (_load_rule_join_data, above) was already cached, but _load_value_rules
# ITSELF -- the CPU-bound classification pass that builds 500+ Recommendation/
# Constraint/Validation/Hiding rule objects from those (cached) raw rows --
# was not. Confirmed live: this exact classification work re-runs from
# scratch on every one of its 5 call sites within engine.py (load_
# recommendation_and_constraint_rules, load_validation_rules, load_
# recommendation_rules, ...), which every real CPQ turn calls back-to-back --
# ~28s of pure CPU re-work per turn for a large catalog, not DB latency
# (confirmed live: workspace 93, 500 rec + 186 constraint + 105 hiding
# rules). Same short-TTL, leak-safe pattern as _RULE_JOIN_DATA_CACHE.
_VALUE_RULES_CACHE: dict[tuple[int, str], tuple[float, tuple]] = {}

# 2026-08-28 perf fix: _data_table_forced_vns has NO cache parameter at any
# of its 4 real call sites (build_payload never threads one through), so
# every call re-runs its full _ATTRSEQ_CONFIRMED_REQUIRED_VNS x candidate-
# CPQ-models cross-product from scratch, each candidate lookup only hitting
# data_table_resolver's module-level TABLE cache (no DB re-query) but still
# paying real Python-level function-call/dict-lookup/logging overhead --
# confirmed live: 3,580 such lookups logged within a single APX Next
# Product-selection turn (elapsed_s=177.75 for that turn's rule-eval step
# alone). Same short-TTL, leak-safe pattern as _RULE_JOIN_DATA_CACHE and
# _VALUE_RULES_CACHE above -- keyed on exactly the inputs the function
# actually reads (workspace/catalog/base_model/product plus each
# _ATTRSEQ_CONFIRMED_REQUIRED_VNS member's own filled/filled_multi value),
# so a real change to any of those inputs naturally misses and recomputes;
# nothing else can go stale under this key.
_DATA_TABLE_FORCED_VNS_CACHE: dict[tuple, tuple[float, frozenset]] = {}
_DATA_TABLE_FORCED_VNS_CACHE_TTL_SECONDS = 300.0


def _clear_data_table_forced_vns_cache() -> None:
    """Test-isolation hook -- call from an autouse fixture to prevent this
    process-lifetime cache from leaking fake/monkeypatched data between
    tests that reuse the same cache key. Mirrors _clear_rule_join_data_cache."""
    _DATA_TABLE_FORCED_VNS_CACHE.clear()


# 2026-08-28 perf fix (P5, follow-up to the P2 fix above): _substitute_util_
# get_constraint_vals has no memoization of its own -- confirmed live it
# alone cost 82s/59s/37s across 3 real APX Next passes before
# apply_constraint_rules' own whole-function cache (_constraint_cache)
# stabilized, and on any genuine cache-miss (a real narrowing/resync)
# still re-walks the full _cpq_model_candidates cross-product once per
# script-backed ConstraintRule. Keyed on the full `filled`-state signature
# (not just base_model/product) because resolve_whitelist_values' own
# multi-condition row matching (_row_conditions_match) can depend on ANY
# filled attribute, not just the two obviously-relevant ones -- see
# _fill_signature's own docstring for why a narrower signature is unsafe
# here (same failure class as the Package Type bug it was written to
# prevent).
_SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE: dict[tuple, tuple[float, str]] = {}
_SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE_TTL_SECONDS = 300.0


def _clear_substitute_util_get_constraint_vals_cache() -> None:
    """Test-isolation hook -- mirrors _clear_data_table_forced_vns_cache."""
    _SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE.clear()


_RULE_JOIN_DATA_CACHE_LAST_SEEN_MARKER: list[float | None] = [None]
_VALUE_RULES_CACHE_LAST_SEEN_MARKER: list[float | None] = [None]
_DATA_TABLE_FORCED_VNS_CACHE_LAST_SEEN_MARKER: list[float | None] = [None]
_SUBSTITUTE_UTIL_GET_CONSTRAINT_VALS_CACHE_LAST_SEEN_MARKER: list[float | None] = [None]
# docs/CPQ_TURN_LATENCY_PERFORMANCE_PLAN_2026_08_19.md -- widened from 30.0,
# same reasoning as _RULE_JOIN_DATA_CACHE_TTL_SECONDS above.
_VALUE_RULES_CACHE_TTL_SECONDS = 300.0


def _clear_value_rules_cache() -> None:
    """Test-isolation hook -- same purpose as _clear_rule_join_data_cache."""
    _VALUE_RULES_CACHE.clear()
