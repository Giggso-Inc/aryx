"""The chat summary hands the multi-select selections to the derived required set,
as the beautify call site does (PR review M1). Synthetic names only."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.api.ask_response_building import ask_cpq_summary_text as mod
import aryx.api.ask_api  # noqa: F401 -- the summary imports it lazily
from aryx.cpq.state import ConfigAttr


def test_summary_passes_filled_multi_to_the_required_set():
    attr = ConfigAttr(entity_id=1, variable_name="featureSet", display_label="Features", required=False,
                      default_value="", options=[], select_type="multi", catalog_prefix="Cat")
    engine = MagicMock()
    engine.mandatory_tier_c_vns.return_value = frozenset()
    engine.categorized_summary_groups.return_value = []
    with patch("aryx.api.ask_api._cpq_engine", engine):
        mod._cpq_summary_text({}, [attr], set(), "P", 1, sources={}, filled={},
                              filled_multi={"featureSet": ["A", "B"]})
    kwargs = engine.mandatory_tier_c_vns.call_args.kwargs
    assert kwargs["filled_multi"] == {"featureSet": ["A", "B"]}
