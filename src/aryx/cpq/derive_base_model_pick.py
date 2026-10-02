"""Derive the Base Model option from already-known attribute values (D10).

Port of aryxent PR 8: before the Base Model attr falls through to its
full raw-list always-ask anchor, narrow the model's real base models to
exactly one using Whitelist evidence from the attrs known this turn.
Gated by ``cpq_derive_base_model_enabled``; never guesses among 2+.
"""
from __future__ import annotations

import logging

from aryx.config import get_settings
from aryx.cpq.data_table.data_table_derive_base_model import derive_base_model_from_known_attrs
from aryx.cpq.logging_context import install_run_id_logging
from aryx.raven_log import raven_log
from aryx.cpq.resolved_model_candidates import resolved_model_first_candidates
from aryx.cpq.state import MenuOption

# Source tags of values that were guessed, not known (never derivation evidence).
_BLIND_SOURCE_PREFIXES = ("blind_pick", "default_first_available")

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)


def derived_base_model_option(
    options: list[MenuOption], filled: dict[str, str],
    workspace_id: int | None, catalog_prefix: str,
    cache: dict[tuple[int, str], tuple] | None,
    sources: dict[str, str] | None = None,
) -> MenuOption | None:
    """The Base Model option derived from `filled`, or None (flag off / no
    workspace / no options / not narrowed to one real option). Never raises. When `sources` (the
    per-turn source tags) is given, blind-filled values (source tag starting
    ``blind_pick`` or ``default_first_available``) are not used as evidence."""
    if workspace_id is None or not options:
        return None
    if not get_settings().cpq_derive_base_model_enabled:
        return None
    try:
        product = filled.get("productSelectionProduct_all", "")
        ignore = frozenset(
            vn for vn, src in (sources or {}).items()
            if str(src).startswith(_BLIND_SOURCE_PREFIXES)
        )
        for cpq_model in resolved_model_first_candidates(product, workspace_id, catalog_prefix, cache):
            derived = derive_base_model_from_known_attrs(
                cpq_model, filled, workspace_id, catalog_prefix, cache,
                ignore_attrs=ignore,
            )
            if derived is None:
                continue
            match = next((o for o in options if o.item_value == derived), None)
            if match is not None:
                logger.info("cpq: derived_base_model cpq_model=%r derived=%r", cpq_model, derived)
                raven_log("INFO", "P4", "ask.base_model.derived base model derived from known attributes",
                          context={"selected_option": derived, "available_options": [o.item_value for o in options][:20],
                                   "reason_code": "DERIVED_FROM_KNOWN_ATTRS", "policy_version": "derive_base_model_v1",
                                   "cpq_model": cpq_model, "ignored_blind_attrs": len(ignore)})
                return match
    except Exception as exc:  # noqa: BLE001 -- derivation must never break the fill pass
        logger.exception("cpq: derive base model failed")
        raven_log("WARN", "P3", "ask.base_model.derive_failed derivation skipped, fill pass continues",
                  error_code="ARYX_ASK_BASE_MODEL_DERIVE_FAILED",
                  context={"triggering_error": type(exc).__name__, "attempt": 1, "max_attempts": 1,
                           "backoff_ms": 0, "recovery_selected": "skip_derivation", "fallback_target": None,
                           "exit_condition": "degraded", "result": "degraded"})
    return None
