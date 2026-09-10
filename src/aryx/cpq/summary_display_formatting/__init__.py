"""Summary / display-formatting cluster (Phase 4 step 10 extraction
from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Everything that turns the engine's resolved `display_filled` state into
something a human reads back -- the conversational summary and both
Beautify views -- grouped as one layer because all of it hangs off the
single filtered item set `_filled_summary_triples` produces:

* `exclusion_filters` -- the "should this attr get a line at all?"
  predicates: `_is_noise_var` (structural integration/system-prefix
  detection), `_attr_hidden_from_submission` /
  `_attr_is_transient_set_type` (the shared single source of truth
  `build_payload` and the pre-quote QA listing both call), and
  `_is_summary_excluded` (which mirrors those two so the summary can
  never show a field that will never be submitted).
* `summary_items` -- `_filled_summary_triples`, which owns ALL the
  filtering the rest of the cluster builds on, plus its
  `filled_summary_pairs` label/value projection.
* `summary_categories` -- `_summary_category`'s variable_name-fragment
  classification and its grouped, display-ordered consumer
  `categorized_summary_groups`.
* `beautify_sections` -- `_beautify_sectioned_rows`: one row set, two
  renderers, so the plain-text and tabular Beautify views can never
  drift apart on rows or on the Mandatory/System split.
* `beautify_output` -- `beautify_text` / `beautify_rows`, pure
  presentation over those rows.
* `render_summary` -- `render_filled_summary`, the deterministic no-LLM
  fallback rendering of `categorized_summary_groups`.

Every intra-cluster collaborator (and `_is_html_value` /
`_is_mandatory_input_attr` from outside it) is reached back through the
passed-in `engine` instance rather than by calling the local function,
and the module-level category tables off the engine MODULE object, so
the original ``self.<name>`` / bare-global lookups -- and any patch of
them -- behave exactly as before.

Re-exports every function so ``from aryx.cpq.summary_display_formatting
import <name>`` works regardless of which submodule defines it.
"""

from __future__ import annotations

from aryx.cpq.summary_display_formatting.beautify_output import (
    beautify_rows,
    beautify_text,
)
from aryx.cpq.summary_display_formatting.beautify_sections import (
    _beautify_sectioned_rows,
)
from aryx.cpq.summary_display_formatting.exclusion_filters import (
    _attr_hidden_from_submission,
    _attr_is_transient_set_type,
    _is_noise_var,
    _is_summary_excluded,
)
from aryx.cpq.summary_display_formatting.render_summary import (
    render_filled_summary,
)
from aryx.cpq.summary_display_formatting.summary_categories import (
    _summary_category,
    categorized_summary_groups,
)
from aryx.cpq.summary_display_formatting.summary_items import (
    _filled_summary_triples,
    filled_summary_pairs,
)

__all__ = [
    "_attr_hidden_from_submission",
    "_attr_is_transient_set_type",
    "_beautify_sectioned_rows",
    "_filled_summary_triples",
    "_is_noise_var",
    "_is_summary_excluded",
    "_summary_category",
    "beautify_rows",
    "beautify_text",
    "categorized_summary_groups",
    "filled_summary_pairs",
    "render_filled_summary",
]
