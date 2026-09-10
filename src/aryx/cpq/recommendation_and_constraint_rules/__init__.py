"""Recommendation / constraint / validation rule cluster -- the four
``_load_value_rules`` projections, the BML evaluator factory, the
recommendation apply + resync passes, the validation-warning pass, and
the read-only rule-consistency cross-check (Phase 4 step 6 extraction
from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Grouped together because they are one pipeline over a single rule fetch:
the loaders all project the SAME ``_load_value_rules`` tuple, the apply/
resync/validation passes consume those lists against the same filled
state (sharing the declarative-condition and attr-index machinery), and
``find_rule_inconsistencies`` re-runs the apply side to audit its result.

``_load_value_rules`` and ``apply_constraint_rules`` deliberately stay on
``CpqEngine`` for now (both oversized, each needs its own decomposition);
this package reaches them back through the ``engine`` instance.

Re-exports every function so ``from aryx.cpq.recommendation_and_
constraint_rules import <name>`` works regardless of which submodule
actually defines it.
"""

from __future__ import annotations

from aryx.cpq.recommendation_and_constraint_rules.apply_recommendations import (
    apply_recommendation_rules,
)
from aryx.cpq.recommendation_and_constraint_rules.apply_validation import (
    apply_validation_rules,
)
from aryx.cpq.recommendation_and_constraint_rules.bml_evaluator import (
    build_bml_evaluator,
)
from aryx.cpq.recommendation_and_constraint_rules.inconsistencies import (
    find_rule_inconsistencies,
)
from aryx.cpq.recommendation_and_constraint_rules.loaders import (
    load_constraint_rules,
    load_recommendation_and_constraint_rules,
    load_recommendation_rules,
    load_validation_rules,
)
from aryx.cpq.recommendation_and_constraint_rules.resync import (
    resync_stale_recommendations,
)

__all__ = [
    "apply_recommendation_rules",
    "apply_validation_rules",
    "build_bml_evaluator",
    "find_rule_inconsistencies",
    "load_constraint_rules",
    "load_recommendation_and_constraint_rules",
    "load_recommendation_rules",
    "load_validation_rules",
    "resync_stale_recommendations",
]
