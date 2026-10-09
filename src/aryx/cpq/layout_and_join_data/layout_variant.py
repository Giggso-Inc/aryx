"""Choose which stored layout variant applies to a model (plan 3.3).

A layout export names its own Configuration Flow in its top-level
``variableName`` (the stored variant key, opaque here). The catalog's
Configuration Flow rules (rule_type "6") carry that name as their
``variable_name`` and list, as ``_bm_model_variable_name`` = <node> rule
inputs, the model nodes that use the flow. No name is hardcoded.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Iterable

from aryx.cpq import engine as _engine_module
from aryx.cpq import engine_caches
from aryx.cpq.layout_and_join_data.layout_variant_context import MODEL_NODE_VAR
from aryx.cpq.layout_source import DEFAULT_LAYOUT_VARIANT, LayoutFileSource

logger = logging.getLogger(__name__)

_OP_EQUALS = "4"  # BM operator code for "="


def _source(source: LayoutFileSource | None) -> LayoutFileSource:
    return source or _engine_module._DEFAULT_LAYOUT_FILE_SOURCE


def stored_variant_keys(
    workspace_id: int, catalog_prefix: str, source: LayoutFileSource | None = None,
) -> list[str]:
    """Stored variant keys (oldest upload first); cached per prefix. A
    source without ``variant_keys`` yields [] (single-layout behaviour)."""
    cache = engine_caches._LAYOUT_VARIANT_KEYS_CACHE
    key = (workspace_id, catalog_prefix)
    if key not in cache:
        fetch = getattr(_source(source), "variant_keys", None)
        cache[key] = list(fetch(catalog_prefix, workspace_id)) if fetch else []
    return cache[key]


def _model_attr_ids(rdb: Any, workspace_id: int, catalog_prefix: str) -> set[int]:
    """Native ids of the attribute(s) whose variable_name is the platform's
    model-context constant."""
    ids: set[int] = set()
    for _eid, attrs in rdb.fetch_entities_by_type(workspace_id, "bmconfigattr", catalog_prefix):
        if str(attrs.get("variable_name") or "").strip() == MODEL_NODE_VAR:
            try:
                ids.add(int(str(attrs.get("id")).strip()))
            except (TypeError, ValueError):
                continue
    return ids


def flow_nodes_by_variable(workspace_id: int, catalog_prefix: str) -> dict[str, frozenset[str]]:
    """{flow rule variable_name (lowercase): model nodes (lowercase)} from the
    active rule_type "6" rules; cached per (workspace_id, catalog_prefix)."""
    cache = engine_caches._LAYOUT_FLOW_MAP_CACHE
    key = (workspace_id, catalog_prefix)
    if key in cache:
        return cache[key]
    rdb = _engine_module.get_cpq_rdb()
    rules = rdb.fetch_rules(workspace_id, "6", catalog_prefix, active_only=True)
    attrs_by_eid = rdb.fetch_entity_attributes([r[0] for r in rules], workspace_id)
    name_by_src: dict[int, str] = {}
    for eid, src_id, _name, _fn in (r[:4] for r in rules):
        vn = str((attrs_by_eid.get(eid) or {}).get("variable_name") or "").strip().lower()
        if vn and src_id is not None:
            name_by_src[src_id] = vn
    attr_ids = _model_attr_ids(rdb, workspace_id, catalog_prefix)
    nodes: dict[str, set[str]] = {}
    for rule_id, attr_id, value, op in rdb.fetch_rule_inputs(workspace_id, catalog_prefix):
        if attr_id in attr_ids and op == _OP_EQUALS and rule_id in name_by_src:
            bucket = nodes.setdefault(name_by_src[rule_id], set())
            bucket.update(p.strip().lower() for p in value.split("~") if p.strip())
    result = {vn: frozenset(v) for vn, v in nodes.items()}
    cache[key] = result
    return result


def _control_set(
    workspace_id: int, catalog_prefix: str, variant: str, source: LayoutFileSource | None,
) -> frozenset[str]:
    """Attribute variable names a variant's layout file places; cached."""
    cache = engine_caches._LAYOUT_CONTROLSET_CACHE
    key = (workspace_id, catalog_prefix, variant)
    if key not in cache:
        from aryx.cpq.layout_and_join_data.components import (  # noqa: PLC0415
            _walk_layout_components,
        )
        names: frozenset[str] = frozenset()
        text = _source(source).get(catalog_prefix, workspace_id, variant=variant)
        try:
            data = json.loads(text) if text else None
            names = frozenset(
                str(c["resourceAttributeVarName"]) for c in _walk_layout_components(data))
        except (ValueError, TypeError):
            logger.warning("cpq layout variant: unreadable layout variant=%r", variant)
        cache[key] = names
    return cache[key]


def layout_variant_for(
    workspace_id: int, catalog_prefix: str, node_var: str | None,
    governed_names: Iterable[str] | Callable[[], Iterable[str]] | None = None,
    source: LayoutFileSource | None = None,
) -> str:
    """Variant key whose layout applies to model node `node_var`.

    1. A stored variant whose Configuration Flow rule lists the node
       (case-insensitive). 2. Else the variant whose control set covers most
       of `governed_names` (ties: first stored). 3. Else the sentinel, or the
       first stored variant when no sentinel row exists. No variant stored
       at all -> the sentinel.
    """
    keys = stored_variant_keys(workspace_id, catalog_prefix, source)
    if not keys:
        return DEFAULT_LAYOUT_VARIANT
    node = (node_var or "").strip().lower()
    if node:
        flows = flow_nodes_by_variable(workspace_id, catalog_prefix)
        for key in keys:
            if node in flows.get(key.lower(), ()):
                return key
    if callable(governed_names):
        governed_names = governed_names()  # lazy: only the fallback needs it
    names = {n for n in (governed_names or ()) if n}
    if names:
        scored = [(len(names & _control_set(workspace_id, catalog_prefix, k, source)), k)
                  for k in keys]
        best = max(score for score, _k in scored)
        if best > 0:
            return next(k for score, k in scored if score == best)
    return DEFAULT_LAYOUT_VARIANT if DEFAULT_LAYOUT_VARIANT in keys else keys[0]


def effective_variant(
    workspace_id: int, catalog_prefix: str, variant: str,
    source: LayoutFileSource | None = None,
) -> str:
    """Variant a display-order load should use. Flag off, or an explicitly
    requested non-sentinel variant: `variant` unchanged (today's behaviour).
    Flag on and the sentinel requested: resolved from the bound model."""
    from aryx.cpq.layout_and_join_data import layout_variant_context as ctx  # noqa: PLC0415
    if variant != DEFAULT_LAYOUT_VARIANT or not ctx.layout_variants_enabled():
        return variant
    if not stored_variant_keys(workspace_id, catalog_prefix, source):
        return variant
    try:
        node = ctx.current_model_node()
        chosen = layout_variant_for(
            workspace_id, catalog_prefix, node, lambda: ctx.current_governed_names(workspace_id, catalog_prefix), source)
        _log_variant_choice(workspace_id, catalog_prefix, node, chosen)
        return chosen
    except Exception:  # noqa: BLE001 -- variant choice must never break a turn
        logger.warning("cpq layout variant: choice failed, using %r", variant, exc_info=True)
        return variant


_LOGGED_CHOICES: set[tuple] = set()           # one line per distinct choice per process, never per call


def _log_variant_choice(workspace_id: int, catalog_prefix: str, node: str | None, chosen: str) -> None:
    """ask.layout.variant (DEBUG): which stored layout a turn uses and why. Reason FLOW_RULE = the model node is listed by the
    chosen layout's Configuration Flow rule; NO_MODEL_NODE = no node was bound, so the layout is a guess (governed names, else
    the oldest upload). Diagnostic only, never changes the choice."""
    try:
        from aryx.raven_log import raven_log, would_log  # noqa: PLC0415 -- diagnostic only

        key = (workspace_id, catalog_prefix, (node or "").lower(), chosen)
        if key in _LOGGED_CHOICES or len(_LOGGED_CHOICES) > 500 or not would_log("DEBUG"):
            return
        _LOGGED_CHOICES.add(key)
        flows = flow_nodes_by_variable(workspace_id, catalog_prefix)
        in_flow = bool(node) and (node or "").strip().lower() in flows.get(chosen.lower(), ())
        reason = "FLOW_RULE" if in_flow else ("NO_MODEL_NODE" if not node else "NODE_NOT_IN_ANY_FLOW_RULE")
        raven_log("DEBUG", "P4", "ask.layout.variant layout variant chosen for the turn", context={
            "selected_option": chosen, "available_options": stored_variant_keys(workspace_id, catalog_prefix)[:8],
            "reason_code": reason, "model_node": node or "",
            "flow_rule_nodes": {k: sorted(v)[:6] for k, v in list(flows.items())[:6]}})
    except Exception:  # noqa: BLE001 -- a diagnostic must never change the choice
        return
