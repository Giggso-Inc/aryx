"""Derive the Base Model option from already-known attribute values (D10).

Port of aryxent PR 8: before the Base Model attr falls through to its
full raw-list always-ask anchor, narrow the model's real base models to
exactly one using Whitelist evidence from the attrs known this turn.
Gated by ``cpq_derive_base_model_enabled``; never guesses among 2+.
"""
from __future__ import annotations

import logging
from typing import Any, TypedDict

from aryx.config import get_settings
from aryx.cpq.data_table.data_table_derive_base_model import (
    derive_base_model_from_known_attrs, explain_known_attrs, model_base_models,
)
from aryx.cpq.logging_context import install_run_id_logging
from aryx.raven_log import raven_log, would_log
from aryx.cpq.resolved_model_candidates import resolved_model_first_candidates
from aryx.cpq.state import MenuOption

# Source tags of values that were guessed, not known (never derivation evidence).
_BLIND_SOURCE_PREFIXES = ("blind_pick", "default_first_available")

logger = logging.getLogger(__name__)
install_run_id_logging(__name__)


def _blind_attrs(sources: dict[str, str] | None) -> frozenset[str]:
    """Attributes whose value was guessed (blind-filled): never derivation evidence."""
    return frozenset(vn for vn, src in (sources or {}).items() if str(src).startswith(_BLIND_SOURCE_PREFIXES))


class _Seen(TypedDict):
    """What one derivation attempt saw, for the not-derived diagnostic."""
    candidates: list[str]
    results: dict[str, str | None]
    reason: str


def derived_base_model_option(
    options: list[MenuOption], filled: dict[str, str],
    workspace_id: int | None, catalog_prefix: str,
    cache: dict[tuple[int, str], tuple] | None,
    sources: dict[str, str] | None = None,
) -> MenuOption | None:
    """The Base Model option derived from `filled`, or None (flag off / no
    workspace / no options / not narrowed to one real option). Never raises. When `sources` (the
    per-turn source tags) is given, blind-filled values (source tag starting
    ``blind_pick`` or ``default_first_available``) are not used as evidence.

    When nothing is derived and DEBUG is on, the diagnostic records why. With several candidate models its
    `reason_code` describes the last candidate that produced a code (`DERIVED_CODE_NOT_AN_OPTION`) and otherwise
    `NOT_NARROWED_TO_ONE`; `results` has each candidate's own outcome."""
    if workspace_id is None or not options:
        return None
    if not get_settings().cpq_derive_base_model_enabled:
        return None
    seen: _Seen = {"candidates": [], "results": {}, "reason": "NOT_NARROWED_TO_ONE"}
    try:
        product = filled.get("productSelectionProduct_all", "")
        ignore = _blind_attrs(sources)
        candidates = resolved_model_first_candidates(product, workspace_id, catalog_prefix, cache)
        seen["candidates"] = candidates
        if not candidates:
            seen["reason"] = "NO_CANDIDATE_MODEL_PRODUCT_BLANK" if not product else "NO_CANDIDATE_MODEL"
        for cpq_model in candidates:
            derived = derive_base_model_from_known_attrs(
                cpq_model, filled, workspace_id, catalog_prefix, cache,
                ignore_attrs=ignore,
            )
            seen["results"][cpq_model] = derived
            if derived is None:
                continue
            match = next((o for o in options if o.item_value == derived), None)
            if match is None:
                seen["reason"] = "DERIVED_CODE_NOT_AN_OPTION"
                continue
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
    _log_not_derived(seen, filled, options, cache, workspace_id, catalog_prefix, sources)
    return None


def _log_not_derived(
    seen: _Seen, filled: dict[str, str], options: list[MenuOption],
    cache: dict[Any, Any] | None, workspace_id: int, catalog_prefix: str,
    sources: dict[str, str] | None,
) -> None:
    """DEBUG line: why no base model was derived; never affects the fill pass.

    Deduplicated per per-turn cache by OUTCOME (reason, candidates and the set of known attributes that are not
    blind-filled), not once per turn: the rules loop runs several fill passes against one cache, and an early pass
    must not hide a later one that fails for a different reason or that knows more attributes (`known_attr_match`
    depends on them). An identical repeat is still skipped."""
    try:
        if not would_log("DEBUG"):
            return
        ignore = _blind_attrs(sources)
        known = frozenset(k for k, v in filled.items() if v and k not in ignore)
        key = ("_derive_base_model_not_derived_logged", workspace_id, catalog_prefix,
               seen["reason"], tuple(seen["candidates"][:6]), known)
        if cache is not None:
            if key in cache:
                return
            cache[key] = True
        counts = {m: len(model_base_models(m, workspace_id, catalog_prefix, cache)) for m in seen["candidates"][:6]}
        reason = seen["reason"]
        if reason == "NOT_NARROWED_TO_ONE" and counts and not any(counts.values()):
            reason = "NO_BASE_MODEL_ROWS"      # the candidate models have no constraint rows at all
        explained = _explain_first_model_with_rows(seen["candidates"], counts, filled, sources, workspace_id,
                                                   catalog_prefix, cache)
        raven_log("DEBUG", "P4", "ask.base_model.not_derived why no base model was derived this pass", context={
            "selected_option": "left_for_customer", "available_options": ["derived", "left_for_customer"],
            "reason_code": reason, "candidates": seen["candidates"][:6],
            "base_models_per_candidate": counts,
            "results": {m: r for m, r in list(seen["results"].items())[:6]},
            "option_count": len(options), "product_filled": bool(filled.get("productSelectionProduct_all")),
            "known_attr_count": sum(1 for v in filled.values() if v), "known_attr_match": explained,
            "blind_attr_count": len(ignore)})
    except Exception:  # noqa: BLE001 -- a diagnostic must never change the fill
        logger.debug("cpq: not_derived diagnostic failed", exc_info=True)


def _explain_first_model_with_rows(
    candidates: list[str], counts: dict[str, int], filled: dict[str, str], sources: dict[str, str] | None,
    workspace_id: int, catalog_prefix: str, cache: dict[Any, Any] | None,
) -> list[dict[str, Any]]:
    """`explain_known_attrs` for the first candidate model that has base models (names and counts only)."""
    model = next((m for m in candidates if counts.get(m)), None)
    if model is None:
        return []
    return explain_known_attrs(model, filled, workspace_id, catalog_prefix, cache, ignore_attrs=_blind_attrs(sources))
