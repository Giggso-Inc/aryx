"""ask.layout.variant: the layout a turn uses and why (ws 1267: APX 3000 showed only ~10 of the Portable layout's attributes and
nothing in the log said which layout was loaded). Logging only; the choice itself is unchanged."""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.layout_and_join_data import layout_variant as lv
from aryx.cpq.layout_and_join_data import layout_variant_context as ctx

FLOWS = {"portable": frozenset({"apx3000"}), "mobile": frozenset({"apx7500"})}


def _run(node, chosen="portable"):
    lv._LOGGED_CHOICES.clear()
    logged: list = []
    with patch.object(ctx, "layout_variants_enabled", return_value=True), \
            patch.object(ctx, "current_model_node", return_value=node), \
            patch.object(lv, "stored_variant_keys", return_value=["portable", "mobile"]), \
            patch.object(lv, "flow_nodes_by_variable", return_value=FLOWS), \
            patch.object(lv, "layout_variant_for", return_value=chosen), \
            patch("aryx.raven_log.would_log", return_value=True), \
            patch("aryx.raven_log.raven_log", side_effect=lambda *a, **k: logged.append((a, k))):
        got = lv.effective_variant(1267, "p", lv.DEFAULT_LAYOUT_VARIANT)
        lv.effective_variant(1267, "p", lv.DEFAULT_LAYOUT_VARIANT)             # same choice again: not logged twice
    return got, logged


def test_the_choice_is_returned_unchanged_and_logged_once_with_the_flow_reason():
    got, logged = _run("aPX3000")
    assert got == "portable" and len(logged) == 1
    ctxt = logged[0][1]["context"]
    assert ctxt["reason_code"] == "FLOW_RULE" and ctxt["selected_option"] == "portable" and ctxt["model_node"] == "aPX3000"


def test_no_model_node_is_reported_as_a_guess():
    _got, logged = _run(None, chosen="mobile")
    assert logged[0][1]["context"]["reason_code"] == "NO_MODEL_NODE"


def test_a_node_no_flow_rule_lists_is_reported():
    _got, logged = _run("aPX9999")
    assert logged[0][1]["context"]["reason_code"] == "NODE_NOT_IN_ANY_FLOW_RULE"


def test_a_failing_log_never_changes_the_choice():
    lv._LOGGED_CHOICES.clear()
    with patch.object(ctx, "layout_variants_enabled", return_value=True), \
            patch.object(ctx, "current_model_node", return_value="aPX3000"), \
            patch.object(lv, "stored_variant_keys", return_value=["portable"]), \
            patch.object(lv, "layout_variant_for", return_value="portable"), \
            patch.object(lv, "flow_nodes_by_variable", side_effect=RuntimeError("x")), \
            patch("aryx.raven_log.would_log", return_value=True):
        assert lv.effective_variant(1267, "p", lv.DEFAULT_LAYOUT_VARIANT) == "portable"
