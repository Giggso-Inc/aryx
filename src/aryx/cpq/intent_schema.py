"""Phase 0 deliverable — docs/CPQ_LLM_INTENT_FIRST_UNIVERSAL_PLAN.md.

Structured intent-classification contract for the planned LLM-first
classifier. Defines WHAT the LLM is asked to return per turn — never a
raw catalog identifier (variable_name/item_value/entity_id), only
plain-language target descriptions the deterministic resolution layer
(existing detect_*/apply_answer functions in engine.py) resolves
afterward. See the plan doc §5 for the two-layer rationale.

Not wired into the live turn flow yet (that starts at Phase 1 — shadow
mode). This module is the schema only: a JSON-Schema dict for the
structured-output LLM call, plus a matching dataclass for the parsed,
validated result. Both must be kept in sync — `INTENT_RESULT_JSON_SCHEMA`
is what the model is constrained to produce; `IntentResult` is what the
rest of the codebase consumes after `parse_intent_result` validates it.

Category note (plan doc §5 refinement): `label_collision` and
`change_request_collision` are deliberately NOT categories here. Under
the two-layer design, "the target is ambiguous because 2+ real attrs
match" is something the DETERMINISTIC resolution layer discovers when it
tries to resolve a `target_description` — not something the LLM decides
upfront. Folding them into the classifier would require the LLM to know
about catalog-specific label collisions in advance, which defeats the
whole point of it working from plain language. They surface downstream
as a resolution-layer AMBIGUOUS outcome instead (see `AMBIGUOUS` category
below, and the "resolution failure" path in the plan doc's mitigation
table, risk #4).

As of the Raven Style Compliance Plan's Phase 2a (2026-09-03), this file
is a pure re-export hub: the shared enums live in `cpq.intent_schema_
enums`, the plain-language IntentResult contract lives in `cpq.intent_
schema_result`, and the gateway quarantine contract lives in `cpq.intent_
schema_gateway`. Every importer across the codebase uses direct-name
imports (`from aryx.cpq.intent_schema import X`) with zero whitebox
patches on this module — confirmed via grep before splitting — so this
re-export list is the only compatibility surface needed.
"""

from __future__ import annotations

from aryx.cpq.intent_schema_enums import Confidence, IntentCategory
from aryx.cpq.intent_schema_gateway import (
    GATEWAY_INTENT_JSON_SCHEMA,
    GatewayIntentResult,
    _GATEWAY_NO_TARGET_CATEGORIES,
    _is_signed_digit_quantity_text,
    parse_gateway_intent,
    validate_gateway_quarantine,
)
from aryx.cpq.intent_schema_result import (
    INTENT_RESULT_JSON_SCHEMA,
    ChangeTarget,
    IntentResult,
    parse_intent_result,
)

__all__ = [
    "GATEWAY_INTENT_JSON_SCHEMA",
    "INTENT_RESULT_JSON_SCHEMA",
    "ChangeTarget",
    "Confidence",
    "GatewayIntentResult",
    "IntentCategory",
    "IntentResult",
    "_GATEWAY_NO_TARGET_CATEGORIES",
    "_is_signed_digit_quantity_text",
    "parse_gateway_intent",
    "parse_intent_result",
    "validate_gateway_quarantine",
]
