"""Seeding `productSelectionProduct_all` from the anchor text once a
product switch or the initial turn's own NL detection already proved
`session.product_name` against this catalog, split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the
original inline block. `_cpq_engine` and `logger` are read through the
ask_api MODULE object (not imported by name) since at least one test
replaces the whole singleton via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.product_match_exact_first import resolved_model_seed_texts
from aryx.cpq.session_guard.session_guard import push_snapshot


def _seed_product_select_from_anchor(session: Any, attrs: list) -> None:
    """A product-switch (or the initial turn's own NL detection) already
    PROVED session.product_name against this catalog — asking the
    productSelectionProduct_all question again on the very next turn
    would ignore that proof and re-derive it from a reply ("yes") that
    carries no product hint at all. Seed it directly via the same fuzzy
    option-matcher normal answers use, mirroring the confirmed-country
    carry-over. Guarded on "not yet filled" so this only fires once
    (turn 1, or the turn right after _complete_product_switch reset
    session.filled) and never clobbers a value a later turn's real
    answer already set.

    Seed productSelectionProduct_all only AFTER Hardware is known on
    hardware-based catalogs (mandatory HW). Seeding from family name
    early caused Product to look "answered" or raced ahead of Hardware.
    On non-hardware catalogs, keep prior seed-from-anchor behavior.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    _hw_attrs = [a for a in attrs if _cpq_engine._is_hardware_version_attr(a)]
    _hw_ready = (
        not _hw_attrs
        or any(a.variable_name in session.filled for a in _hw_attrs)
    )
    if not (
        _hw_ready
        and "productSelectionProduct_all" not in session.filled
    ):
        return
    _product_attr = next(
        (a for a in attrs if a.variable_name == "productSelectionProduct_all"), None,
    )
    if _product_attr is None:
        return
    _seed_candidates = [
        c for c in (
            *resolved_model_seed_texts(_product_attr.options),  # D11: [] unless flag on
            session.pending_switch_question,
            session.product_anchor_question,
            session.product_name,
        ) if c
    ]
    for _candidate_text in _seed_candidates:
        _match = _cpq_engine.apply_answer(_product_attr, _candidate_text)
        if _match:
            _item_value, _display_name = _match
            # PR #205 review fix (High finding #4): this seeds a genuine
            # first-time fill of Product from anchor text, one of the
            # `apply_answer` sites the ISSUE-003 fix plan flagged for
            # the same undo-snapshot audit. Not covered by any enclosing
            # cascade handler's own snapshot (unlike the `_handle_
            # cascade`/`_handle_cascade_multi` sites, which already push
            # one at their own top) — genuinely uncovered until now.
            push_snapshot(session, reason="product_anchor_seed")
            session.filled["productSelectionProduct_all"] = _item_value
            session.display_filled["productSelectionProduct_all"] = _display_name
            session.filled_source["productSelectionProduct_all"] = "product_anchor"
            _ask_api_module.logger.info(
                "cpq: seeded productSelectionProduct_all=%r from %r "
                "turn=%s — skips a redundant re-ask",
                _item_value, _candidate_text, session.turn,
            )
            break
