"""LLM narration call, segment parsing, and the two-level fallback chain
for `_cpq_summary_text`, split out of `api/ask_api.py` (Phase 3/11-phase
ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md)
purely to keep the sibling `ask_cpq_summary_text.py` under the line cap.
Logic unchanged from the original inline try/except block. `_cpq_engine`
and `logger` are read through the ask_api MODULE object (not imported by
name) since ask_api tests patch several of its own module-level names by
dotted path.
"""

from __future__ import annotations

import re
import time
from typing import Callable

from aryx.llm import llm_runtime
from aryx.api.ask_response_building.ask_cpq_summary_prompt import _CPQ_SEGMENT_DELIM
from aryx.api.ask_standard_pipeline import _strip_think
from aryx.cpq.engine import SUMMARY_FALLBACK_CATEGORY
from aryx.cpq.state import CpqSession
from aryx.raven_log import raven_log

_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')


def _rlog(level: str, crit: str, event: str, opt: str, reason: str, code: str = "", **ctx) -> None:
    """One raven record per narration-chain branch: counts/flags only, never text or prompt."""
    raven_log(level, crit, f"ask.response.summary_{event}", error_code=code, context={  # type: ignore[arg-type]
        "selected_option": opt, "reason_code": reason, "available_options": [
            "llm_narration", "deterministic_bullets", "raw_state_table"], **ctx})


def _rec(err: str, attempt: int, target: str, exit_condition: str, result: str) -> dict:
    """Recovery fields for a fallback record."""
    return {"triggering_error": err, "attempt": attempt, "max_attempts": attempt, "backoff_ms": 0,
            "recovery_selected": target, "fallback_target": target,
            "exit_condition": exit_condition, "result": result}


def _narrate_cpq_summary(
    sys: str,
    user: str,
    expected_segments: int,
    groups: list,
    workspace_id: int,
    display_filled: dict[str, str],
    attrs: list,
    rule_governed_ids: set[int],
    sources: dict[str, str] | None,
    product_quantity: int | None,
    required_vns: set,
    finish: Callable[[str], str],
    product_anchor_hint: str | None = None,
    catalog_prefix: str = "",
) -> str:
    """LLM-narrate the summary, verify every curated fact survived, and
    fall back through deterministic bullets to a raw state table on any
    miss — see `_cpq_summary_text`'s own docstring for the full contract.
    """
    from aryx.api import ask_api as _ask_api_module
    curated_fields = {
        label: value for _cat, pairs in groups
        if _cat != SUMMARY_FALLBACK_CATEGORY
        for label, value in pairs
    }
    try:
        # ARYX_LLM_REASON_MODEL (role="answer"), not menial — this narration
        # is the customer-facing summary of a real quote; the same reasoning
        # tier already used for CPQ's own BML Tier-2 script fallback.
        _nar_t0 = time.monotonic()
        text, _it, _ot = llm_runtime.chat("answer", sys, user, workspace_id=workspace_id)
        _nar_ms = int((time.monotonic() - _nar_t0) * 1000)
        _ask_api_module.logger.info(
            "cpq_perf: summary narration LLM call took %.3fs",
            time.monotonic() - _nar_t0,
        )
        text = _strip_think(text).strip()
        segments = [s.strip() for s in text.split(_CPQ_SEGMENT_DELIM)]
        if len(segments) == expected_segments and all(segments):
            lead_in = _SENTENCE_SPLIT.split(segments[0])[0].strip()
            lines = [lead_in]
            for (category, _pairs), segment in zip(groups, segments[1:]):
                if category == SUMMARY_FALLBACK_CATEGORY:
                    # Meant to be one short line already (per the prompt) —
                    # still cap to the first sentence so a model that rambles
                    # anyway can't blow past the "plain-text line" contract.
                    segment = _SENTENCE_SPLIT.split(segment)[0].strip()
                # Every other category is real bullet lines, one per fact —
                # capping to "first sentence" here would truncate to a
                # single bullet, so the full segment is kept verbatim.
                lines.append(f"\n**{category}:**\n{segment}")
            draft = "\n".join(lines)
            # summary_guard: every CURATED value (curated_fields, not the
            # raw display_filled dict) must appear in the narration
            from aryx.cpq.summary_guard import (
                fields_missing_from_summary, raw_state_table,
            )
            missing = fields_missing_from_summary(draft, curated_fields)
            if not missing:
                # Product Quantity is already embedded in `draft` via
                # `groups` (Product Name category) — no finish() append.
                _rlog("INFO", "P4", "narrated llm summary accepted", "llm_narration",
                      "SUMMARY_GUARD_PASSED", segment_count=len(segments), llm_ms=_nar_ms,
                      curated_field_count=len(curated_fields), answer_len=len(draft))
                return draft
            _ask_api_module.logger.info(
                "summary_guard: LLM summary missing %s — regenerating via "
                "deterministic bullets", missing[:5],
            )
            _rlog("WARN", "P3", "guard_miss llm narration missing facts", "deterministic_bullets",
                  "LLM_NARRATION_MISSING_FIELDS", "ARYX_ASK_SUMMARY_GUARD_MISS",
                  missing_count=len(missing), llm_ms=_nar_ms,
                  **_rec("SummaryGuardMiss", 1, "deterministic_bullets", "guard_check", "fallback"))
            second = _ask_api_module._cpq_engine.render_filled_summary(
                display_filled, attrs, rule_governed_ids=rule_governed_ids,
                sources=sources, product_quantity=product_quantity,
                required_vns=required_vns,
                product_anchor_hint=product_anchor_hint, workspace_id=workspace_id,
                catalog_prefix=catalog_prefix,
            )
            missing2 = fields_missing_from_summary(second, curated_fields)
            if not missing2:
                # Same reasoning as `draft` above — already embedded.
                _rlog("DEBUG", "P4", "bullets deterministic summary accepted",
                      "deterministic_bullets", "BULLETS_GUARD_PASSED",
                      answer_len=len(second) if isinstance(second, str) else None)
                return second
            _ask_api_module.logger.warning(
                "summary_guard: deterministic bullet fallback ALSO missing "
                "%s — falling back to raw_state_table", missing2[:5],
            )
            _rlog("ERROR", "P2", "raw_table bullets also missing facts", "raw_state_table",
                  "BULLETS_MISSING_FIELDS", "ARYX_ASK_SUMMARY_RAW_TABLE_FALLBACK",
                  missing_count=len(missing2),
                  **_rec("SummaryGuardMiss", 2, "raw_state_table", "guard_check", "degraded"))
            stub = CpqSession()
            stub.display_filled = dict(display_filled)
            stub.filled_source = dict(sources or {})
            # raw_state_table has no category concept at all (flat,
            # alphabetized) — finish()'s trailing-append is still the
            # right behavior here, the one remaining caller of it.
            return finish(raw_state_table(stub, attrs))
        _ask_api_module.logger.debug(
            "cpq: summary narration returned %d segments (expected %d) — "
            "using bullet fallback", len(segments), expected_segments)
        _rlog("WARN", "P3", "segments llm segment count mismatch", "deterministic_bullets",
              "SEGMENT_COUNT_MISMATCH", "ARYX_ASK_SUMMARY_SEGMENT_MISMATCH",
              segment_count=len(segments), expected_segments=expected_segments, llm_ms=_nar_ms,
              **_rec("SegmentMismatch", 1, "deterministic_bullets", "segment_check", "fallback"))
    except Exception as exc:  # noqa: BLE001
        _ask_api_module.logger.debug(
            "cpq: summary narration failed — using bullet fallback",
            exc_info=True,
        )
        _rlog("WARN", "P3", "failed llm narration raised", "deterministic_bullets",
              "NARRATION_EXCEPTION", "ARYX_ASK_SUMMARY_NARRATION_FAILED",
              dependency_name="llm", workspace_id=workspace_id,
              **_rec(type(exc).__name__, 1, "deterministic_bullets", "exception", "fallback"))
    return _ask_api_module._cpq_engine.render_filled_summary(
        display_filled, attrs, rule_governed_ids=rule_governed_ids, sources=sources,
        product_quantity=product_quantity, required_vns=required_vns,
        product_anchor_hint=product_anchor_hint, workspace_id=workspace_id,
        catalog_prefix=catalog_prefix)
