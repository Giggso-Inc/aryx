"""Resolving an ambiguous gateway result's already-known attribute (fast
path) or falling to a fresh grounded clarify prompt, split out of
`_llm_first_gateway_turn` (Phase 7/11-phase ask_api decomposition, docs/
RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md) purely to keep the sibling
`ask_handle_llm_first_gateway_turn.py` under the line cap. Shared by both
the "clarify" action branch and the "dispatch"-mapped-to-AMBIGUOUS
branch, which were near-identical inline blocks in the original function
— factored into one helper here rather than duplicated. Logic unchanged
from those original inline blocks. `_cpq_engine` is read through the
ask_api MODULE object (not imported by name) since at least one test
replaces the whole singleton via `patch("aryx.api.ask_api._cpq_engine")`.
"""

from __future__ import annotations

from typing import Any

from aryx.api.ask_attr_recompute.ask_attr_query_and_classify_usage import _with_classify_usage
from aryx.api.ask_pending_clarify.ask_pending_clarify_answer import _set_pending_clarify_and_answer
from aryx.api.ask_pending_clarify.ask_pending_clarify_apply import _apply_pending_clarify_resolution


def _resolve_or_reask_ambiguous(
    req: "Any", session: Any, attrs: list, gw: Any,
    hiding_rules: list, rec_rules: list, con_rules: list, bml_eval: Any,
    clarifying_question: str | None, tool_name: str,
) -> dict[str, Any]:
    """docs/CPQ_AMBIGUOUS_CLARIFY_DISCARDS_RESOLVED_EVIDENCE_PLAN_2026_08_
    21.md — the gateway can be confident about the ATTRIBUTE (its own
    rationale says so) while still calling the turn AMBIGUOUS because
    only the VALUE is unclear (e.g. "UHF band" vs real options "UHF
    R1"/"UHF R2"). `gw.result.variable_name` already carries that
    resolved attribute; the generic clarify path otherwise re-derives
    attribute candidates from raw text instead, throwing it away and
    asking "which attribute" instead of "which value" -- live-confirmed:
    a message unambiguously naming "Primary Frequency" still triggered a
    5-attribute disambiguation because "frequency" is a generic word
    shared by every sibling frequency attr's label. Re-validated against
    `attrs` here rather than trusted blindly, matching every other
    LLM-supplied identifier crossing into real dispatch logic in this
    file. `_apply_pending_clarify_resolution` itself requires the attr to
    already be in session.filled (a real change, not a first-time fill)
    before attempting anything, so this is a no-op for a genuinely-
    unfilled attribute.

    docs/config_consistency_issues_2026-07-30.md issue 1 — never offer a
    currently-hidden-for-this-product attribute as a disambiguation
    candidate. Computed BEFORE the fast path (Raven review, PR #264
    finding M1) — the fast path used to bypass this entirely, routing
    straight into `_apply_pending_clarify_resolution` even when the
    gateway's resolved attribute is currently hidden for this product.
    """
    from aryx.api import ask_api as _ask_api_module
    _cpq_engine = _ask_api_module._cpq_engine
    _hidden_vns = _cpq_engine.apply_hiding_rules(
        attrs, session.filled, hiding_rules, bml_eval, filled_multi=session.filled_multi,
    )[2]
    if (
        gw.result.variable_name
        and any(a.variable_name == gw.result.variable_name for a in attrs)
        and gw.result.variable_name not in _hidden_vns
        and hiding_rules is not None and rec_rules is not None and con_rules is not None
    ):
        return _with_classify_usage(
            _apply_pending_clarify_resolution(
                req, session, attrs, gw.result.variable_name, req.question,
                hiding_rules, rec_rules, con_rules, bml_eval,
            ),
            gw.prompt_tokens, gw.completion_tokens,
        )
    return _set_pending_clarify_and_answer(
        req, session, attrs,
        original_question=req.question,
        clarifying_question=clarifying_question,
        con_rules=con_rules,
        bml_eval=bml_eval,
        prompt_tokens=gw.prompt_tokens,
        completion_tokens=gw.completion_tokens,
        tool_name=tool_name,
        hidden_vns=_hidden_vns,
        hiding_rules=hiding_rules,
        rec_rules=rec_rules,
    )
