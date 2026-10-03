"""Completing a confirmed mid-session product switch, split out of
`_run_cpq_turn_inner` (Phase 10/11-phase ask_api decomposition, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Originally a nested closure
capturing `session` from the enclosing turn function; rewritten here to
take `session` as an explicit parameter so it can be called from outside
`_run_cpq_turn_inner` once that function is itself split apart. Logic
unchanged from the original inline definition. `logger` is read through
the ask_api MODULE object (not imported by name) for consistency with
the rest of this decomposition.
"""

from __future__ import annotations

from typing import Any

from aryx.raven_log import raven_log, would_log


_PRODUCT_SNAPSHOT_CAP = 5


def _complete_product_switch(session: Any, new_product: str, new_country: str) -> None:
    """Snapshot the outgoing product's state, restore the incoming
    product's own prior state if it was visited earlier this session,
    and commit the switch. `new_country` is carried over as-is (already
    validated by the caller, or simply never set) — never blindly
    cleared, so a client who already gave a valid country for the new
    product doesn't have to repeat it.

    Restored values are NOT trusted blindly — Step 2/3 below feed
    session.filled into auto_fill as `already_filled` on every turn
    regardless of where it came from, so a restored value that's no
    longer valid under current rules/constraints is naturally dropped
    and re-asked, exactly like any other turn's continuation (see
    docs/CPQ_MULTI_PRODUCT_SESSION_SNAPSHOT_PLAN.md §3)."""
    from aryx.api import ask_api as _ask_api_module
    _from_product = getattr(session, "product_name", "") or ""
    _caller_country_given = bool(new_country)
    session.cascade_log.append({
        "event": "product_switch", "from": session.product_name,
        "to": new_product, "turn": getattr(session, "turn", None),
    })
    # Snapshot the OUTGOING product before wiping it — even a
    # product visited only once is captured, ready for a much later
    # switch-back. Skipped on the very first-ever turn (no prior
    # product to snapshot). Re-inserted (not just updated) so dict
    # iteration order tracks recency for the cap below.
    if session.product_name:
        session.product_snapshots.pop(session.product_name, None)
        session.product_snapshots[session.product_name] = {
            "filled": dict(session.filled),
            "filled_multi": dict(session.filled_multi),
            "display_filled": dict(session.display_filled),
            "filled_source": dict(session.filled_source),
            "country": session.country,
            "negated_vns": list(session.negated_vns),
            "product_entity_id": session.product_entity_id,
        }
        while len(session.product_snapshots) > _PRODUCT_SNAPSHOT_CAP:
            oldest = next(iter(session.product_snapshots))
            session.product_snapshots.pop(oldest)
            if would_log("DEBUG"):
                raven_log("DEBUG", "P4", "ask.switch.snapshot_evicted oldest product snapshot dropped at cap",
                          context={"reason_code": "SNAPSHOT_CAP_EXCEEDED", "evicted_product": oldest,
                                   "snapshot_cap": _PRODUCT_SNAPSHOT_CAP,
                                   "turn": getattr(session, "turn", None)})

    snap = session.product_snapshots.get(new_product)
    if snap:
        session.filled = dict(snap["filled"])
        session.filled_multi = dict(snap["filled_multi"])
        session.display_filled = dict(snap["display_filled"])
        session.filled_source = dict(snap["filled_source"])
        session.negated_vns = list(snap["negated_vns"])
        session.product_entity_id = snap["product_entity_id"]
        # Only fall back to the snapshot's own country when THIS turn's
        # caller didn't already determine one — both call sites
        # (confirm_switch's carried-over country, switch_country's
        # freshly-validated replacement) always pass a non-empty value
        # when they have one; new_country is empty here only when
        # neither had anything to contribute (docs/CPQ_MULTI_PRODUCT_
        # SESSION_SNAPSHOT_PLAN.md §"Country carry-over — RESOLVED").
        # The snapshot's country needs no re-validation either: it was
        # captured while THIS SAME product was previously configured,
        # so it was already valid for it.
        if not new_country:
            new_country = snap["country"]
        _ask_api_module.logger.info(
            "cpq_switch: restored prior snapshot for product=%r turn=%s "
            "(%d filled attrs)", new_product, session.turn, len(snap["filled"]),
        )
    else:
        session.filled = {}
        session.filled_multi = {}
        session.display_filled = {}
        session.filled_source = {}
        session.negated_vns = []
        session.product_entity_id = 0

    session.pending_variables = []
    session.status = "configuring"
    session.country = new_country
    # NOTE: catalog_prefix is not a CpqSession field — it's derived
    # fresh from attrs[0].catalog_prefix every turn in Step 2 below,
    # so there's nothing session-scoped to reset here.
    session.product_name = new_product
    session.pending_switch_product = ""
    session.pending_switch_candidates = []
    session.pending_anchor = ""
    # The pre-switch anchor text is stale once the switch completes, but
    # was never cleared here -- _seed_product_select_from_anchor tries it
    # as a fallback seed candidate (ranked ABOVE the already-confirmed new
    # session.product_name) on every turn afterward, indefinitely, risking
    # a fuzzy match against the OLD product's description instead of the
    # new one (CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T3). pending_switch
    # _question already carries this switch's own triggering text
    # correctly (set/cleared by ask_step2_anchor_gates.py), so dropping
    # this stale fallback removes a wrong-match risk, not a real signal.
    session.product_anchor_question = ""
    _ask_api_module.logger.info(
        "cpq_switch: switched turn=%s new_product=%r country=%r — config state %s",
        session.turn, new_product, new_country or "(none — will be asked fresh)",
        "restored from snapshot" if snap else "reset",
    )
    raven_log("INFO", "P4", "ask.switch.completed product switch committed", context={
        "selected_option": "restore_snapshot" if snap else "reset_config",
        "available_options": ["restore_snapshot", "reset_config"],
        "reason_code": "PRIOR_SNAPSHOT_FOUND" if snap else "NO_PRIOR_SNAPSHOT",
        "from_product": _from_product, "to_product": new_product,
        "country_source": "caller" if _caller_country_given
        else "snapshot" if new_country else "none",
        "restored_filled_count": len(session.filled or {}) if snap else 0,
        "snapshot_count": len(getattr(session, "product_snapshots", None) or {}),
        "turn": getattr(session, "turn", None)})
