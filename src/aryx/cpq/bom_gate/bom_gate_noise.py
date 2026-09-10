"""Shared "noise var" / synthetic-engine-var detection for the BOM gate.

Split out of `cpq/bom_gate.py` (Raven Style Compliance Plan, Phase 2b,
2026-09-03). Used by both provenance checking and required-field checking.
Zero test patches against this module — confirmed via grep.
"""
from __future__ import annotations

# Engine-computed helper values that live in `filled` purely so BML scripts
# can read them (e.g. hiding-rule conditions doing SPLIT()/findinarray() on
# the master string) -- never a real catalog option, never something a
# customer answered, and never present in the real BOM payload (build_
# payload's own layout-intersection already keeps it out, confirmed live
# 2026-08-11). `_is_noise_var` alone doesn't catch this one -- it has no
# underscore prefix and no all-caps integration-style segment -- so it's
# named explicitly here, the same way this module already special-cases
# known non-catalog synthetic values rather than guessing from shape alone.
_SYNTHETIC_ENGINE_VARS = frozenset({"hiddenMasterStringForAstroPortable_astro"})


def _is_noise_var(variable_name: str) -> bool:
    """True for underscore-prefixed or integration/system-prefixed vars --
    same structural check as CpqEngine._is_noise_var (engine.py), duplicated
    here rather than imported to avoid a bom_gate<->engine import coupling.

    Confirmed live (2026-08-09): a real catalog's `required=True` flag on
    attrs like `_price_book_var_name`/`_BM_USER_CURRENCY`/`_BM_USER_GROUPS`/
    `_BM_USER_LANGUAGE`/`_BM_USER_NUMBER_FORMAT`/`_configOperationContext`
    reflects Oracle CPQ's own account/session-context integration -- these
    are populated by the calling CRM/account layer, never by product
    configuration, and are already excluded from the real BOM payload
    (build_payload's own `_is_noise_var` check) and never asked in
    conversation (auto_fill's own `_is_noise_var` check). Without this same
    exclusion here, `find_missing_required_fields` wrongly reported them as
    "missing required data" and blocked completion on fields Aryx was never
    going to fill by design.
    """
    if variable_name.startswith("_"):
        return True
    head = variable_name.split("_", 1)[0]
    return len(head) >= 2 and head.isalpha() and head.isupper()
