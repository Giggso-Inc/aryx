"""Governance / sibling-exclusivity / country-region cluster -- the two
auto-fill governance sets (`rule_governed_ids`, `governed_target_ids`)
and the "Product"-label noise filter built on them, the
exclusive-sibling-family detector + its mutating apply pass and the
label-stem normalizer they group by, the country/region resolvers, and
the BML Tier-2 prefetch + context-sentence builders (Phase 4 step 7
extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Grouped together as the "which attrs may the engine answer for itself,
and which must it ask" layer: the governance sets decide auto-fill
eligibility, the sibling-exclusivity pass undoes a weakly-sourced
auto-fill and re-asks the real governing attribute instead, and the
country/region resolvers are the one decision-required pair the
governance sets explicitly exclude. `build_context_sentence` explains
whichever question survives all of that; `bml_prefetch_requests`
pre-warms the very scripts those rules will consult.

Every module reaches module-level ``engine.py`` state
(``_COUNTRY_TO_REGION``, ``_DECISION_REQUIRED_KEYS``, the country alias
helpers) and ``CpqEngine`` staticmethods through the engine MODULE
object rather than ``from ... import``, both to defer lookups past
``engine.py``'s own import order and so any patch of those names is
still honored.

Re-exports every function so ``from aryx.cpq.governance_and_sibling_
exclusivity import <name>`` works regardless of which submodule
actually defines it.
"""

from __future__ import annotations

from aryx.cpq.governance_and_sibling_exclusivity.bml_prefetch import (
    bml_prefetch_requests,
    build_context_sentence,
)
from aryx.cpq.governance_and_sibling_exclusivity.country import (
    is_recognized_country,
)
from aryx.cpq.governance_and_sibling_exclusivity.governed_targets import (
    governed_target_ids,
)
from aryx.cpq.governance_and_sibling_exclusivity.label_stem import (
    normalized_label_stem,
)
from aryx.cpq.governance_and_sibling_exclusivity.region import derive_region
from aryx.cpq.governance_and_sibling_exclusivity.rule_governed import (
    product_label_noise_vns,
    rule_governed_ids,
)
from aryx.cpq.governance_and_sibling_exclusivity.sibling_enforce import (
    enforce_exclusive_sibling_families,
)
from aryx.cpq.governance_and_sibling_exclusivity.sibling_exclusions import (
    exclusive_sibling_family_exclusions,
)

__all__ = [
    "bml_prefetch_requests",
    "build_context_sentence",
    "derive_region",
    "enforce_exclusive_sibling_families",
    "exclusive_sibling_family_exclusions",
    "governed_target_ids",
    "is_recognized_country",
    "normalized_label_stem",
    "product_label_noise_vns",
    "rule_governed_ids",
]
