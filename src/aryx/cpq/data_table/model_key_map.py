"""Product value -> data-table model key, read from the catalog's own mapping script.

A catalog can file its data-table rows (Attrsequence, Whitelist, NewCountryRegMapping) under a model key that is not
the model name Aryx resolves. Live case (ws 1267, 2026-10-07): the rows of the plain APX 8000 radio sit under the key
"APX8000/XE". The catalog says so itself, in a script function that maps the product selection to the key with a
repeated ``if/elif (product == "A" OR product == "B") { var = "KEY"; }`` chain and then reads the data tables with
``CPQModel = $var``.

This module finds such functions by their shape (no function id, variable name or model name is hardcoded), parses
the chain into one product -> key map per workspace, and offers that key as a candidate ahead of a model that has no
rule rows of its own. It is lazy and additive: a first candidate that already has rows is never touched, a key is used
only when the Attrsequence table really has rows under it, and everything is off unless
``cpq_catalog_model_key_enabled`` is on. It does not parse arbitrary BML; a function of another shape is ignored.
"""
from __future__ import annotations

import re
import threading
import time

from aryx.config import get_settings
from aryx.cpq.data_table.data_table_product import _sequence_model_codes
from aryx.raven_log import raven_log, would_log

_POLICY = "catalog_model_key_v1"
_MIN_PRODUCT_TESTS = 5          # a mapping chain tests many product values; one or two is some other script
_FAILURE_TTL_SECONDS = 60.0     # an empty map is retried soon, a real one is kept for the configured time
_USED_VAR = re.compile(r"CPQModel\s*=\s*\$(\w+)")

_CACHE: dict[tuple[int, str], tuple[float, dict[str, str]]] = {}   # key -> (expires_at, product -> model key)
_LOCKS: dict[tuple[int, str], threading.Lock] = {}   # one load at a time PER workspace; other workspaces never wait
_LOCKS_GUARD = threading.Lock()                       # protects the two dicts only, never held during a load
# string literals are matched first so a "//" or "/*" inside one is not taken for a comment
_TOKENS = re.compile(r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'|/\*.*?\*/|//[^\n]*", re.S)
_ONLY_OR = re.compile(r"[\s()]*(?:(?:\bOR\b|\bor\b|\|\|)[\s()]*)*")


def clear_model_key_map_cache() -> None:
    """Forget every loaded map (tests, and a catalog re-ingest)."""
    with _LOCKS_GUARD:
        _CACHE.clear()


def _product_literal() -> str:
    """Return the product-selection attribute name (imported late: catalog_profile imports the candidate module)."""
    from aryx.cpq.catalog_profile import PRODUCT_LITERAL
    return PRODUCT_LITERAL


def _strip_comments(text: str) -> str:
    """Drop /* */ and // comments in one pass; text inside a string literal is kept as it is."""
    return _TOKENS.sub(lambda m: m.group(0) if m.group(0)[0] in "\"'" else " ", text)


def parse_model_key_chain(script: str) -> tuple[str, dict[str, str]]:
    """Return (variable, {product value: key}) from a mapping chain, or ("", {}) when the script has none.

    The variable is the one the script passes to the data tables as ``CPQModel = $variable``.
    """
    text = _strip_comments(script)
    product_attr = _product_literal()
    used = _USED_VAR.search(text)
    if not used or product_attr not in text:
        return "", {}
    product_test = re.compile(re.escape(product_attr) + r'\s*==\s*"([^"]+)"')
    var = used.group(1)
    branch = re.compile(r"(?:\bif|\belif|\belse\s+if)\s*\((?P<cond>[^{}]*?)\)\s*\{?\s*"
                        + re.escape(var) + r'\s*=\s*"(?P<key>[^"]+)"', re.S)
    mapping: dict[str, str] = {}
    for found in branch.finditer(text):
        cond = found.group("cond")
        if not _ONLY_OR.fullmatch(product_test.sub("", cond)):
            continue    # another test (AND, <>, a second attribute) sits in the condition: not a plain product list
        for product in product_test.findall(cond):
            mapping.setdefault(product, found.group("key"))
    return var, mapping


def build_model_key_map(scripts: dict[int, str]) -> dict[str, str]:
    """Merge the mapping chains of every mapping-shaped script; the highest function id wins a disagreement."""
    merged: dict[str, str] = {}
    clashes = 0
    used = 0
    for fn_id in sorted(scripts, reverse=True):
        _var, mapping = parse_model_key_chain(scripts[fn_id])
        if len(mapping) < _MIN_PRODUCT_TESTS:
            continue
        used += 1
        for product, key in mapping.items():
            if merged.setdefault(product, key) != key:
                clashes += 1
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ask.model_key.map_built product to model key map built from catalog scripts",
                  context={"selected_option": "built" if merged else "empty", "available_options": ["built", "empty"],
                           "reason_code": "MAP_BUILT" if merged else "NO_MAPPING_SCRIPT", "policy_version": _POLICY,
                           "scripts_scanned": len(scripts), "scripts_used": used,
                           "products": len(merged), "keys": len(set(merged.values())), "clashes": clashes})
    return merged


def _load_scripts(workspace_id: int, catalog_prefix: str) -> dict[int, str]:
    """Read the workspace's function scripts through the CPQ accessor (same source as the BML evaluator)."""
    from aryx.cpq.rdb.rdb import get_cpq_rdb
    return get_cpq_rdb().fetch_function_scripts(workspace_id, catalog_prefix)


def model_key_map(workspace_id: int, catalog_prefix: str = "") -> dict[str, str]:
    """Return the workspace's product -> model key map, loaded once and kept for the configured time.

    A failed load, or a load that returned no scripts at all, degrades to an empty map that is retried soon. Scripts
    that were read but hold no mapping chain give an empty map kept for the full time: that is a real answer.
    """
    cache_key = (workspace_id, catalog_prefix)
    with _LOCKS_GUARD:
        hit = _CACHE.get(cache_key)
        if hit is not None and time.monotonic() < hit[0]:
            return hit[1]
        lock = _LOCKS.setdefault(cache_key, threading.Lock())
    with lock:
        with _LOCKS_GUARD:
            hit = _CACHE.get(cache_key)             # another request may have finished the load while this one waited
        if hit is not None and time.monotonic() < hit[0]:
            return hit[1]
        scripts: dict[int, str] = {}
        try:
            scripts = _load_scripts(workspace_id, catalog_prefix)
            mapping = build_model_key_map(scripts)
        except Exception as exc:  # noqa: BLE001 -- the lookup is an extra route; the caller keeps its own candidates
            raven_log("WARN", "P3", "ask.model_key.map_failed catalog model key map not loaded, candidates unchanged",
                      error_code="ARYX_ASK_MODEL_KEY_MAP_FAILED",
                      context={"triggering_error": type(exc).__name__, "attempt": 1, "max_attempts": 1, "backoff_ms": 0,
                               "recovery_selected": "no_mapped_key", "fallback_target": "existing_candidates",
                               "exit_condition": "degraded", "result": "degraded", "workspace_id": workspace_id})
            mapping = {}
        mapping = {name.strip().upper(): key for name, key in mapping.items()}    # looked up case-insensitively
        ttl = float(get_settings().cpq_catalog_model_key_ttl_seconds) if scripts else _FAILURE_TTL_SECONDS
        with _LOCKS_GUARD:
            _CACHE[cache_key] = (time.monotonic() + ttl, mapping)
        return mapping


def mapped_model_key(
    product_name: str, workspace_id: int, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> str | None:
    """Return the data-table model key the catalog gives `product_name`, or None.

    None when the setting is off, the product has no entry, or the Attrsequence table has no rows under the key.
    """
    product = (product_name or "").strip()
    if not product or not get_settings().cpq_catalog_model_key_enabled:
        return None
    key = model_key_map(workspace_id, catalog_prefix).get(product.upper())
    if key is None:
        return None             # most products have no entry: the common case, not logged
    if key.upper() not in _sequence_model_codes(workspace_id, catalog_prefix, cache):
        if would_log("DEBUG"):
            raven_log("DEBUG", "P4", "ask.model_key.not_used mapped key has no rule rows, not offered",
                      context={"selected_option": "none", "available_options": ["mapped_key", "none"],
                               "reason_code": "KEY_HAS_NO_ROWS", "policy_version": _POLICY,
                               "workspace_id": workspace_id})
        return None
    return key


def front_mapped_key(
    codes: tuple[str, ...], product_name: str, workspace_id: int | None, catalog_prefix: str = "",
    cache: dict[tuple[int, str], tuple] | None = None,
) -> tuple[str, ...]:
    """Put the catalog's model key first when the first candidate has no rule rows; otherwise return `codes` as is."""
    if workspace_id is None:
        return codes
    key = mapped_model_key(product_name, workspace_id, catalog_prefix, cache)
    if key is None:
        return codes
    if codes and codes[0].strip().upper() in _sequence_model_codes(workspace_id, catalog_prefix, cache):
        return codes
    fronted = (key, *(code for code in codes if code != key))
    if would_log("DEBUG"):
        raven_log("DEBUG", "P4", "ask.model_key.fronted mapped model key put first, first candidate has no rows",
                  context={"selected_option": key, "available_options": list(codes)[:8],
                           "reason_code": "FIRST_CANDIDATE_HAS_NO_ROWS", "policy_version": _POLICY,
                           "workspace_id": workspace_id})
    return fronted
