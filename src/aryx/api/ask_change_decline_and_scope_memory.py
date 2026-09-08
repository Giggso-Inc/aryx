"""Change-decline detection and constrained-option helpers, split out of
`ask_api.py` (final sweep, Phase 11/11-phase ask_api decomposition,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). `_is_global_change_
decline` returns True only for an explicit request to make no changes
at all — a replacement clause wins over decline wording so "I don't
want any attributes; use Hardware Version" keeps flowing to normal
resolution instead of being cancelled. `_remember_attr_scope` persists
the option list just shown (PROMPT 7) so a typo on the next turn
re-asks within that scope, never the full catalog. `_constrain_
excluding_rejected` drops the option matching a replacement clause's
rejected text from the allowed set — option-level rejection, distinct
from `session.negated_vns`'s attribute-level suppression. Logic
unchanged from the original inline definitions. `_cpq_engine` is read
through the ask_api module object (not imported by name) since at
least one test replaces the whole singleton via `patch("aryx.api.
ask_api._cpq_engine")`.
"""

from __future__ import annotations

import re
from typing import Any

from aryx.cpq.pending_scope import candidates_from_attr_options, set_pending_scope
from aryx.cpq.replacement_clause import extract_replacement_clause

from aryx.api import ask_api as _ask_api_module

# docs/CPQ_COMPOUND_CHANGE_AND_QUESTION_CLARIFY_ISSUE.md §10 (QA issue #2):
# no decline detector existed anywhere on the pending "which value?" path —
# "I don't want to change product" fell straight into apply_answer as an
# attempted (and failed) Product value. Stemmed with \w* on the verb forms
# (change/changing/changed) rather than one literal, learning directly from
# the earlier clarify-decline regex missing "wanted" vs "want" (§6) —
# deliberately does NOT match bare "no" alone, since that's a legitimate
# value for yes/no-shaped attrs.
_CHANGE_VALUE_DECLINE_RE = re.compile(
    r"don'?t\s+want\w*|do\s+not\s+want\w*"
    r"|no\s+chang\w*|not\s+chang\w*"
    r"|leave\s+it|keep\s+it"
    r"|never\s*mind"
    r"|cancel\s+(this|that|it)"
    r"|skip\s+(this|that)",
    re.IGNORECASE,
)


def _is_change_value_decline(reply: str) -> bool:
    return bool(_CHANGE_VALUE_DECLINE_RE.search(reply or ""))


# Thin wrapper — pure logic lives in aryx.cpq.replacement_clause so offline
# regression / unit tests can load it without FastAPI. Ask-api keeps the
# historical private name for call sites and monkeypatches.
# PROMPT 6: returns (wanted, rejected); contrast-first reversed forms.
def _extract_replacement_clause(text: str) -> tuple[str | None, str | None]:
    """See ``aryx.cpq.replacement_clause.extract_replacement_clause``."""
    return extract_replacement_clause(text)


_GLOBAL_CHANGE_SCOPE_RE = re.compile(
    r"\b(?:any\s+(?:attributes?|fields?|settings?)|anything)\b",
    re.IGNORECASE,
)


def _is_global_change_decline(reply: str) -> bool:
    """Return True only for an explicit request to make no changes at all.

    A replacement clause wins over decline wording so messages such as
    "I don't want any attributes; use Hardware Version" keep flowing to
    normal resolution instead of being cancelled.
    """
    normalized = (reply or "").replace("’", "'")
    wanted, _rejected = _extract_replacement_clause(normalized)
    return (
        wanted is None
        and _is_change_value_decline(normalized)
        and bool(_GLOBAL_CHANGE_SCOPE_RE.search(normalized))
    )


def _remember_attr_scope(
    session: Any,
    attr: Any,
    constrained_item_values: list[str] | None,
    origin_question: str = "",
) -> None:
    """Persist the option list we just showed (PROMPT 7)."""
    if attr is None or not getattr(attr, "options", None):
        return
    cands = candidates_from_attr_options(attr.options, constrained_item_values)
    if not cands:
        return
    vn = getattr(attr, "variable_name", "") or ""
    kind = (
        "product_options"
        if "productselection" in vn.lower().replace("_", "")
        or vn.lower() == "productselectionproduct_all"
        else "attr_options"
    )
    set_pending_scope(
        session,
        kind=kind,
        candidates=cands,
        origin_question=origin_question,
        attr_vn=vn,
        asked_turn=getattr(session, "turn", 0),
    )


def _constrain_excluding_rejected(
    attr: Any,
    rejected_text: str | None,
    base_constrained: list[str] | None,
) -> list[str] | None:
    """Drop the option matching ``rejected_text`` from the allowed set.

    Option-level rejection (not VN-level): ``session.negated_vns`` tracks
    *attributes* suppressed by "exclude any X", while a replacement rejects
    a *value* on the target attr. Constrained-values is the correct path.
    """
    if not rejected_text or not getattr(attr, "options", None):
        return base_constrained
    rej = _ask_api_module._cpq_engine.apply_answer(attr, rejected_text)
    if not rej:
        return base_constrained
    excluded_iv = rej[0]
    base = (
        list(base_constrained)
        if base_constrained is not None
        else [o.item_value for o in attr.options]
    )
    filtered = [v for v in base if v != excluded_iv]
    # Never return an empty allow-list — that would force match failure even
    # for the wanted value if option inventory was unexpected.
    if not filtered:
        return base_constrained
    return filtered
