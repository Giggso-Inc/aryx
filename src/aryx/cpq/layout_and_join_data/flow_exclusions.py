"""Product/model flow mutual exclusivity for the payload, and the structural
model-context mirror detection it depends on (Phase 4 step 5 extraction from
``cpq/engine.py``, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

``model_context_mirror_vns`` was a ``@staticmethod`` and needs nothing;
``payload_flow_exclusions`` calls back onto both instance methods (each of
which tests replace on the instance), so it takes an explicit ``engine``
first parameter.
"""

from __future__ import annotations

from aryx.cpq.state import ConfigAttr


def model_context_mirror_vns(attrs: list[ConfigAttr]) -> set[str]:
    """Variable names of model-context MIRROR attrs — pointer-default
    attrs whose referenced attribute is an underscore-prefixed runtime
    context field (the platform's own `_bm_model_*`-style punch-in
    family). Fully structural: an attr qualifies when its
    default_value equals ANOTHER attr's variable name AND that name
    starts with "_" — no attribute names in code (matches
    modelname_all -> _bm_model_variable_name in both ingested
    exports, and nothing else, per the Issue 11 survey).
    """
    vns = {a.variable_name for a in attrs}
    return {
        a.variable_name for a in attrs
        if not a.options
        and a.default_value in vns
        and a.default_value != a.variable_name
        and a.default_value.startswith("_")
    }


def payload_flow_exclusions(
    engine, workspace_id: int, catalog_prefix: str, attrs: list[ConfigAttr],
) -> set[str]:
    """Product/model flow mutual exclusivity for the payload
    (Issue 11 follow-up, docs/CPQ_PRODUCT_SWITCH_ISSUE.md): a quote is
    identified by its product selection OR its model context — never
    both.

    The flow signal is the catalog's own layout data
    (resolve_always_ask_skips): non-empty means the single active
    native-UI flow HIDES the product selector (model flow — e.g. SVX),
    so the product selector is excluded and model mirrors ship.
    Empty means the product selector is genuinely part of this
    catalog's flow, or the flow is ambiguous/unresolvable (e.g. APX
    Next's two active flows) — product flow: the product identifies
    the quote and the model-context mirrors are excluded instead
    (confirmed live: APX shipped modelname_all="aPXNext" alongside
    productSelectionProduct_all, violating the integration's
    one-or-the-other contract).
    """
    skips = engine.resolve_always_ask_skips(workspace_id, catalog_prefix, attrs)
    if skips:
        return skips  # model flow — product excluded, mirrors ship
    return engine.model_context_mirror_vns(attrs)  # product flow
