"""Config-attr UI/selection-shape classification, split out of `cpq/
engine.py`'s module-level scope (Phase 4, docs/RAVEN_STYLE_COMPLIANCE_
PLAN_2026-09-03.md -- module-level helper extraction beyond the 8
previously-deferred methods, done purely to shrink engine.py further).
Re-exported from `aryx.cpq.engine` (see the import there) so every
existing `from aryx.cpq.engine import classify_select_type` caller/test
keeps working unchanged. Logic unchanged from the original inline
definition.
"""

from __future__ import annotations

from typing import Any


def classify_select_type(attrs: dict[str, Any]) -> str:
    """Classify a config attr's UI/selection shape from its raw BM attrs.

    Confirmed derivation (CPQ_CASCADE_CONVERSATION_PLAN.md §4). The
    multi-select branch was exercised end-to-end for the first time against
    a real submission: the reference sample this classifier was originally
    verified against had is_array_control_attr uniformly "0", so multi-select
    coverage relied solely on that one flag — untested and, it turned out,
    incomplete. A real payload submission confirmed 13 attributes with
    is_array_control_attr=="0" were rejected by the live CPQ API expecting
    an array-set payload, including one ("Carrier Selection") whose own
    variable_name literally contains "MultiSelect". Checking
    display_type in {"6","8"} and attr_type=="1" (both confirmed live to be
    100% exclusive to the rejected attributes — zero overlap with any of
    the 83 that were accepted) closes that gap.

    Priority matters: array-control signals checked first, then the boolean
    pair, then the scalar data_type codes, else default to "single" —
    dropdowns (display_type=="3") and any other shape (free-text, etc.)
    both fall through to "single" safely.

    date/currency/integer/float — added per the real CPQ API payload
    contract (docs/CPQ_RULE_TOOL_FLOW_PLAN.md §15b/16): these were
    previously invisible to this classifier (falling through to "single"
    and serialized like a menu value) despite real attrs of each type
    existing in a real ingested catalog — confirmed via data_type samples:
    5="subscriptionStartDate"/"subscriptionEndDate" (date), 7=
    "solutionCategoryListPrice_astro" (currency/price), 3=ID/counter
    fields like "_configuration_id" (integer), 2="_BM_USER_EXCHANGE_RATE"
    (float). Checked AFTER multi/boolean (those signals are more specific
    and must win on any overlap) but BEFORE the "single" fallback.
    """
    if (str(attrs.get("is_array_control_attr", "")).strip() == "1"
            or str(attrs.get("attr_type", "")).strip() == "1"
            or str(attrs.get("display_type", "")).strip() in ("6", "8")):
        return "multi"
    if (str(attrs.get("display_type", "")).strip() == "10"
            or str(attrs.get("data_type", "")).strip() == "4"):
        return "boolean"
    data_type = str(attrs.get("data_type", "")).strip()
    if data_type == "5":
        return "date"
    if data_type == "7":
        return "currency"
    if data_type == "3":
        return "integer"
    if data_type == "2":
        return "float"
    return "single"
