"""Free-text-attribute constraint description and ask-worthiness (Phase 4
step 2 extraction from ``cpq/engine.py``, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). None of these need
engine-instance callback.
"""

from __future__ import annotations

import re

from aryx.cpq.bml.bml import BmlEvaluator
from aryx.cpq.state import ConfigAttr, ValidationRule
from aryx.cpq.turn_intent.patterns2 import _ALLOWED_CHARS_RE


def _describe_char_allowlist(script: str | None) -> str | None:
    # Raven review, 2026-07-28: this previously did a blind first-match
    # search with no guard against conditional branching or
    # reassignment — the established sibling pattern for exactly this
    # ambiguity class is bml.py's evaluate_constant_return, which bails
    # to None on any `if (` in the script and walks multiple
    # assignments in source order so the LAST one wins (never describes
    # a stale/conditionally-overridden value as if it were the real
    # constraint). Matched here for the same reason.
    if not script:
        return None
    if re.search(r'\bif\s*\(', script, re.IGNORECASE):
        return None
    matches = list(_ALLOWED_CHARS_RE.finditer(script))
    if not matches:
        return None
    chars = matches[-1].group(1)
    if not chars:
        return None
    has_upper = any(c.isupper() for c in chars)
    has_lower = any(c.islower() for c in chars)
    has_digit = any(c.isdigit() for c in chars)
    specials = sorted({c for c in chars if not c.isalnum()})
    parts: list[str] = []
    if has_upper and has_lower:
        parts.append("letters")
    elif has_upper:
        parts.append("uppercase letters")
    elif has_lower:
        parts.append("lowercase letters")
    if has_digit:
        parts.append("digits")
    if specials:
        parts.append("the characters " + " ".join(specials))
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + ", and " + parts[-1]

def describe_free_text_constraint(attr: ConfigAttr, validation_rules: list["ValidationRule"] | None,
) -> str | None:
    """Plain-language description of a no-option attr's real constraint,
    for a Q&A "what values are allowed" question the attr has no
    options to answer with (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md
    Amendment 20 follow-up — confirmed live: agencyDomainName_ID_swSoln
    is free text with zero options, so the existing options-listing
    fast path has nothing to show, and its own ValidationRule's
    human-authored `message` ("Invalid selection") isn't descriptive
    either). Only describes the one script idiom confirmed above;
    returns None (never guesses) for any other rule shape.
    """
    target_ids = {attr.entity_id, attr.source_id}
    for rule in validation_rules or []:
        if rule.target_attr_id not in target_ids:
            continue
        desc = _describe_char_allowlist(rule.condition_script)
        if desc:
            return desc
    return None

def should_ask_free_text_attr(
    attr: ConfigAttr,
    validation_rules: list["ValidationRule"] | None,
    bml_eval: "BmlEvaluator | None",
) -> bool:
    """Generic (not catalog-specific) replacement for Amendment 19's
    reverted blanket "has a ValidationRule -> ask" heuristic (Amendment
    20, docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md). Every deterministic
    signal available in this data (required flag, default_value, script
    shape, hiding-rule visibility) was confirmed identical between a
    genuine case and Amendment 20's false-positive case — so this
    escalates to a Tier-2 LLM judgment (Amendment 22), same discipline
    as every other "no cheaper signal exists" case in this codebase.
    Returns False (never asks) when there's no governing ValidationRule
    at all, or when bml_eval wasn't supplied — same opt-out convention
    every other bml_eval=None caller already gets elsewhere.
    """
    if bml_eval is None:
        return False
    target_ids = {attr.entity_id, attr.source_id}
    rule = next(
        (r for r in (validation_rules or []) if r.target_attr_id in target_ids),
        None,
    )
    if rule is None:
        return False
    return bml_eval.classify_ask_worthy(
        attr.display_label, rule.message, rule.condition_script, attr.entity_id,
    )
