"""Rule-specificity / dependency-graph cluster (Phase 4 step 9
extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Grouped as the "which rule/attribute comes first, and why" layer, all
four members sharing one dependency graph built from rule conditions:

* `_rule_condition_edges` -- the shared, UNFILTERED condition_vn ->
  target_vn edge extraction plus the BM-native-id -> variable_name map.
* `_attribute_depth_ranks` -- cycle-safe longest-path-from-root depth
  per attribute over those edges ("how specific is this attribute").
* `rank_rules_by_specificity` -- orders hiding/recommendation rules
  coarsest-condition-first using those depths (or, when supplied, the
  catalog's full layout order), so "last rule wins" resolves conflicts
  by provable specificity.
* `_dependency_ordered_keys` -- the payload-key-ordering consumer of the
  same edges, restricted to the keys actually being emitted.

Both edge consumers reach `_rule_condition_edges` back through
``CpqEngine`` on the engine MODULE object rather than calling the local
function, so the original ``CpqEngine._rule_condition_edges`` /
``self._attribute_depth_ranks`` lookups (and any patch of them) behave
exactly as before.

Re-exports every function so ``from aryx.cpq.rule_specificity_ranking
import <name>`` works regardless of which submodule defines it.
"""

from __future__ import annotations

from aryx.cpq.rule_specificity_ranking.condition_edges import (
    _attribute_depth_ranks,
    _rule_condition_edges,
)
from aryx.cpq.rule_specificity_ranking.dependency_order import (
    _dependency_ordered_keys,
)
from aryx.cpq.rule_specificity_ranking.specificity_rank import (
    rank_rules_by_specificity,
)

__all__ = [
    "_attribute_depth_ranks",
    "_dependency_ordered_keys",
    "_rule_condition_edges",
    "rank_rules_by_specificity",
]
