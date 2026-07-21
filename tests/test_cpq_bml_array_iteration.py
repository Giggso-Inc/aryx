"""Regression tests: array-iteration BML idiom recognition.

Approach A (recognizer, docs/CPQ_BML_ARRAY_ITERATION_TIER_PLAN.md):
`parse_array_iteration()` structurally recognizes the
`range(control_attr) -> for idx in ... -> if selector[idx]=="literal"
(AND qty[idx]>n)? -> ...` idiom, confirmed present across all 3 available
catalog exports (SVX, APX NEXT/DM4400, SL3500e).

Approach B (ingestion-time graph enrichment, this plan's chosen approach):
`_detect_script_data_flow_links()` runs that SAME recognizer once, at
ingestion, over every bm_function row and materializes what it finds as
fk_link specs pointing at the referenced bm_config_attr rows by
variable_name — reusing the existing `_detect_fk_links` link-materialization
path rather than inventing new pipeline plumbing.
"""
from __future__ import annotations

import csv
import io

from aryx.cpq.bml import parse_array_iteration
from aryx.pipeline.doc_discovery import _detect_script_data_flow_links

_BOOLEAN_VARIANT_SCRIPT = (
    'arrayRange = range(mountingArrayControl_viSoln);\n'
    'for idx in arrayRange {\n'
    '    if(mountingTypeArray_viSoln[idx]=="Shirt Magnetic Mount" '
    'AND mountingTypeArrayqty_viSoln[idx]>0)\n'
    '    { val=true; }\n'
    '}\n'
    'return val;'
)

_QTY_COPY_VARIANT_SCRIPT = (
    'arrayRange = range(mountingArrayControl_viSoln);\n'
    'for idx in arrayRange {\n'
    '    if(mountingTypeArray_viSoln[idx]=="Shirt Magnetic Mount")\n'
    '    { val=mountingTypeArrayqty_viSoln[idx]; }\n'
    '}\n'
    'return val;'
)

_UNRELATED_SCRIPT = (
    'if (containskey(quantityDict, "key")) {\n'
    '    for each in items { val = jsonarraysize(each); }\n'
    '}\n'
    'return val;'
)


# ── parse_array_iteration (Approach A's recognizer, reused by Approach B) ──

def test_parse_array_iteration_recognizes_the_mounting_type_shape():
    shape = parse_array_iteration(_BOOLEAN_VARIANT_SCRIPT)
    assert shape is not None
    assert shape.control_attr == "mountingArrayControl_viSoln"
    assert shape.selector_attr == "mountingTypeArray_viSoln"
    assert shape.literal_value == "Shirt Magnetic Mount"
    assert shape.qty_attr == "mountingTypeArrayqty_viSoln"


def test_parse_array_iteration_recognizes_the_quantity_copy_variant():
    shape = parse_array_iteration(_QTY_COPY_VARIANT_SCRIPT)
    assert shape is not None
    assert shape.control_attr == "mountingArrayControl_viSoln"
    assert shape.selector_attr == "mountingTypeArray_viSoln"
    assert shape.qty_attr == "mountingTypeArrayqty_viSoln"


def test_parse_array_iteration_returns_none_for_unrecognized_loop_shapes():
    assert parse_array_iteration(_UNRELATED_SCRIPT) is None


def test_parse_array_iteration_returns_none_for_empty_script():
    assert parse_array_iteration("") is None
    assert parse_array_iteration(None) is None  # type: ignore[arg-type]


# ── _detect_script_data_flow_links (Approach B: ingestion-time enrichment) ─

def _csv_bytes(header: list[str], rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _fn_plan(rows: list[list[str]]) -> dict:
    return {
        "ontology_type": "SvxConfigBmFunction",
        "filename": "function.csv",
        "match_keys": ["id"],
        "data": _csv_bytes(["id", "script_text"], rows),
    }


def _attr_plan() -> dict:
    return {
        "ontology_type": "SvxConfigBmConfigAttr",
        "filename": "attr.csv",
        "match_keys": ["variable_name"],
        "data": _csv_bytes(
            ["variable_name", "name"],
            [
                ["mountingArrayControl_viSoln", "Mounting Array Control"],
                ["mountingTypeArray_viSoln", "Mounting Type"],
                ["mountingTypeArrayqty_viSoln", "Mounting Type Quantity"],
            ],
        ),
    }


def test_detect_script_data_flow_links_finds_array_iteration_in_bm_function():
    plans = [
        _fn_plan([["1", _BOOLEAN_VARIANT_SCRIPT]]),
        _attr_plan(),
    ]
    links = _detect_script_data_flow_links(plans)

    names = {lk["name"] for lk in links}
    assert names == {
        "BMFUNCTION_ARRAY_ITERATES", "BMFUNCTION_READS_SELECTOR",
        "BMFUNCTION_READS_QUANTITY",
    }
    for lk in links:
        assert lk["source_type"] == "SvxConfigBmFunction"
        assert lk["target_type"] == "SvxConfigBmConfigAttr"
        assert lk["target_attr"] == "variable_name"

    # The recognized fact must be materialized as real columns on the
    # bm_function plan's own CSV data (Approach B's whole point — a
    # permanent fact link_by_attribute's value-equality join can consume).
    fn_plan = plans[0]
    rows = list(csv.reader(io.StringIO(fn_plan["data"].decode("utf-8"))))
    header, data_row = rows[0], rows[1]
    row_map = dict(zip(header, data_row))
    assert row_map["_array_control_attr_ref"] == "mountingArrayControl_viSoln"
    assert row_map["_array_selector_attr_ref"] == "mountingTypeArray_viSoln"
    assert row_map["_array_qty_attr_ref"] == "mountingTypeArrayqty_viSoln"


def test_detect_script_data_flow_links_skips_unrecognized_scripts():
    plans = [
        _fn_plan([["1", _UNRELATED_SCRIPT]]),
        _attr_plan(),
    ]
    links = _detect_script_data_flow_links(plans)
    assert links == [], (
        "a bm_function plan with no recognizable array-iteration script "
        "must produce no link specs at all"
    )


def test_detect_script_data_flow_links_returns_empty_without_a_bm_function_plan():
    # No BmFunction-typed plan present — nothing to analyze, must not crash.
    plans = [_attr_plan()]
    assert _detect_script_data_flow_links(plans) == []


def test_ingestion_links_merge_with_fk_links_without_duplication():
    from aryx.pipeline.doc_discovery import _detect_fk_links

    plans = [
        _fn_plan([["1", _BOOLEAN_VARIANT_SCRIPT], ["2", _UNRELATED_SCRIPT]]),
        _attr_plan(),
    ]
    fk_links = _detect_fk_links(plans)
    flow_links = _detect_script_data_flow_links(plans)

    fk_names = {lk["name"] for lk in fk_links}
    flow_names = {lk["name"] for lk in flow_links}
    assert not (fk_names & flow_names), (
        "the two link sources must never collide on the same edge name"
    )
    assert len(flow_links) == 3, (
        "one recognized script still yields exactly the 3 array-fact links, "
        "regardless of the other, unrecognized row in the same plan"
    )
