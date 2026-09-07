"""NL-hint-extraction / product-mention-detection cluster (Phase 4
step 11 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Everything that turns a customer's raw NL question into structured
signal BEFORE `auto_fill`/`evaluate_rules_loop` ever runs -- the
anchor-detection layer:

* `question_hints` -- `is_cpq_question`, `extract_hints`.
* `flag_hints` -- `_build_flag_keyword_index`, `extract_flag_hints`.
* `unresolvable_context` -- `find_unresolvable_context_attrs`.
* `ingested_products` -- `_ingested_product_names`,
  `ingested_product_alias_map`.
* `model_leaves` -- `single_model_variable_name`,
  `model_variable_candidates`.
* `model_path` -- `model_catalog_path`.
* `product_mention` -- `detect_product_mention`.
* `fuzzy_scoring` -- `_question_tokens`, `_fuzzy_score_candidates`.
* `product_suggestions` -- `suggest_product_candidates`.
* `country_availability` -- `check_country_availability`.
* `entity_fetch` -- `_batch_fetch`, `_is_layout_noise`,
  `_match_family_name`, the shared building blocks the rest of this
  package leans on.
* `catalog_scoping` -- `_scope_to_catalog`.
* `product_option_fetch` -- `_fetch_product_option_list`.
* `product_hint_resolve` -- `resolve_product_hint`.
* `families` -- `list_ingested_families`.

`extract_catalog_hints` and `load_product_config` (2 of the 8
deliberately-deferred oversized methods) sit in this same region of
`engine.py` but were NOT moved -- any of the functions above that call
them do so via the passed-in `engine` instance.

Re-exports every function so ``from aryx.cpq.nl_hint_extraction import
<name>`` works regardless of which submodule defines it.
"""

from __future__ import annotations

from aryx.cpq.nl_hint_extraction.catalog_scoping import _scope_to_catalog
from aryx.cpq.nl_hint_extraction.country_availability import (
    check_country_availability,
)
from aryx.cpq.nl_hint_extraction.entity_fetch import (
    _batch_fetch,
    _is_layout_noise,
    _match_family_name,
)
from aryx.cpq.nl_hint_extraction.families import list_ingested_families
from aryx.cpq.nl_hint_extraction.flag_hints import (
    _build_flag_keyword_index,
    extract_flag_hints,
)
from aryx.cpq.nl_hint_extraction.fuzzy_scoring import (
    _fuzzy_score_candidates,
    _question_tokens,
)
from aryx.cpq.nl_hint_extraction.ingested_products import (
    _ingested_product_names,
    ingested_product_alias_map,
)
from aryx.cpq.nl_hint_extraction.model_leaves import (
    model_variable_candidates,
    single_model_variable_name,
)
from aryx.cpq.nl_hint_extraction.model_path import model_catalog_path
from aryx.cpq.nl_hint_extraction.product_hint_resolve import resolve_product_hint
from aryx.cpq.nl_hint_extraction.product_mention import detect_product_mention
from aryx.cpq.nl_hint_extraction.product_option_fetch import (
    fetch_product_option_list,
)
from aryx.cpq.nl_hint_extraction.product_suggestions import (
    suggest_product_candidates,
)
from aryx.cpq.nl_hint_extraction.question_hints import extract_hints, is_cpq_question
from aryx.cpq.nl_hint_extraction.unresolvable_context import (
    find_unresolvable_context_attrs,
)

__all__ = [
    "_batch_fetch",
    "_build_flag_keyword_index",
    "_fuzzy_score_candidates",
    "_ingested_product_names",
    "_is_layout_noise",
    "_match_family_name",
    "_question_tokens",
    "_scope_to_catalog",
    "check_country_availability",
    "detect_product_mention",
    "extract_flag_hints",
    "extract_hints",
    "fetch_product_option_list",
    "find_unresolvable_context_attrs",
    "ingested_product_alias_map",
    "is_cpq_question",
    "list_ingested_families",
    "model_catalog_path",
    "model_variable_candidates",
    "resolve_product_hint",
    "single_model_variable_name",
    "suggest_product_candidates",
]
