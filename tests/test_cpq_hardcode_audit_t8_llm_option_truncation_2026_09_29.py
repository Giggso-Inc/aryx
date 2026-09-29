"""CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T8: the 15/40/200 option-list
caps shown to the LLM silently drop real options above the cap -- not
changed here (a real latency/token tradeoff needing product input), only
made observable via a warning log when truncation actually happens.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

from aryx.api.ask_llm.ask_llm_classify_change_intent import _llm_classify_change_intent
from aryx.api.ask_llm.ask_llm_classify_intent_universal import _llm_classify_intent_universal
from aryx.api.ask_llm.ask_llm_extract_multi_attr_hints import _llm_extract_multi_attr_hints
from aryx.api.ask_llm.ask_llm_resolve_pending_answer import _llm_resolve_pending_answer
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption


def _menu(n: int) -> list[MenuOption]:
    return [MenuOption(item_value=f"OPT{i}", display_name=f"Option {i}", order=i) for i in range(n)]


def _attr(vn: str, n_options: int) -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name=vn, display_label=vn,
        required=False, default_value="", select_type="single",
        options=_menu(n_options),
    )


def test_classify_change_intent_warns_when_options_exceed_15(caplog):
    attr = _attr("wide_attr", 20)
    session = CpqSession(product_name="p")
    session.filled = {"wide_attr": "Option 0"}
    with (
        patch("aryx.api.ask_api.llm_runtime.chat", return_value=("null", 1, 1)),
        caplog.at_level(logging.WARNING),
    ):
        _llm_classify_change_intent("change wide_attr", [attr], session, workspace_id=1)
    warnings = [r.message for r in caplog.records if "cpq_llm_options_truncated" in r.message]
    assert len(warnings) == 1
    assert "variable_name=wide_attr" in warnings[0]
    assert "cap=15" in warnings[0]
    assert "5 option(s)" in warnings[0]


def test_classify_change_intent_no_warning_under_cap(caplog):
    attr = _attr("narrow_attr", 5)
    session = CpqSession(product_name="p")
    session.filled = {"narrow_attr": "Option 0"}
    with (
        patch("aryx.api.ask_api.llm_runtime.chat", return_value=("null", 1, 1)),
        caplog.at_level(logging.WARNING),
    ):
        _llm_classify_change_intent("change narrow_attr", [attr], session, workspace_id=1)
    assert not any("cpq_llm_options_truncated" in r.message for r in caplog.records)


def test_classify_intent_universal_warns_when_options_exceed_15(caplog):
    attr = _attr("wide_attr", 16)
    session = CpqSession(product_name="p")
    session.pending_variables = ["wide_attr"]
    with (
        patch("aryx.api.ask_api.llm_runtime.chat", return_value=("null", 1, 1)),
        caplog.at_level(logging.WARNING),
    ):
        _llm_classify_intent_universal("pick something", [attr], session, workspace_id=1)
    warnings = [r.message for r in caplog.records if "cpq_llm_options_truncated" in r.message]
    assert len(warnings) == 1
    assert "cap=15" in warnings[0]
    assert "1 option(s)" in warnings[0]


def test_extract_multi_attr_hints_warns_when_options_exceed_40(caplog):
    attr = _attr("wide_attr", 45)
    with (
        patch("aryx.api.ask_api.llm_runtime.chat", return_value=("null", 1, 1)),
        caplog.at_level(logging.WARNING),
    ):
        _llm_extract_multi_attr_hints("bundled fact sentence", [attr], workspace_id=1)
    warnings = [r.message for r in caplog.records if "cpq_llm_options_truncated" in r.message]
    assert len(warnings) == 1
    assert "cap=40" in warnings[0]
    assert "5 option(s)" in warnings[0]


def test_resolve_pending_answer_warns_when_options_exceed_200(caplog):
    attr = _attr("wide_attr", 205)
    with (
        patch("aryx.api.ask_api.llm_runtime.chat", return_value=("null", 1, 1)),
        caplog.at_level(logging.WARNING),
    ):
        _llm_resolve_pending_answer("some long sentence", attr, workspace_id=1)
    warnings = [r.message for r in caplog.records if "cpq_llm_options_truncated" in r.message]
    assert len(warnings) == 1
    assert "cap=200" in warnings[0]
    assert "5 option(s)" in warnings[0]
