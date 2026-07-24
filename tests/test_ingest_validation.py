"""Ingest validation layer (CM-2): ground truth + zero-loss checks.

Uses synthetic in-test XML/CSV data — never the sample file (no hardcoding).
"""
from __future__ import annotations

from aryx.pipeline.ingest_validation import (
    CheckResult,
    GroundTruth,
    ValidationReport,
    _raw_xml_counts,
    ground_truth_from_tabular,
)

_PRODUCT_CSV = (
    b"_element_type,id,name,price\n"
    b"product,P1,Widget A,9.99\n"
    b"product,P2,Widget B,14.99\n"
    b"product,P2,Widget B dup,14.99\n"  # duplicate id -> merges into one entity
)
_CATEGORY_CSV = (
    b"_element_type,id,name,product_id\n"
    b"category,C1,Widgets,P1\n"
    b"category,C2,Gadgets,P2\n"
    b"category,C3,Orphans,P9\n"  # dangling FK -> P9 doesn't exist
)

_PLANS = [
    {"filename": "shop_product.csv", "data": _PRODUCT_CSV},
    {"filename": "shop_category.csv", "data": _CATEGORY_CSV},
]


def test_ground_truth_counts_and_ids() -> None:
    gt = ground_truth_from_tabular(_PLANS)
    assert gt.datasets["shop_product"].rows == 3
    assert gt.datasets["shop_product"].id_values == {"P1", "P2"}
    assert gt.datasets["shop_product"].element_tag == "product"
    assert gt.datasets["shop_category"].rows == 3


def test_ground_truth_fk_inventory() -> None:
    gt = ground_truth_from_tabular(_PLANS)
    assert len(gt.fk_refs) == 1
    fk = gt.fk_refs[0]
    assert fk.child_dataset == "shop_category"
    assert fk.parent_dataset == "shop_product"
    assert fk.fk_column == "product_id"
    assert fk.resolvable_child_ids == {"C1", "C2"}  # C3's P9 is dangling
    assert fk.dangling_values == {"P9"}


def test_ground_truth_endswith_tag_fallback() -> None:
    """FK column referencing a tag by suffix (bm_layout_model_id -> layout_model tag)."""
    plans = [
        {"filename": "x_bm_layout_model.csv",
         "data": b"_element_type,id,name\nbm_layout_model,L1,Left\n"},
        {"filename": "x_bm_prop.csv",
         "data": b"_element_type,id,layout_model_id\nbm_prop,R1,L1\n"},
    ]
    gt = ground_truth_from_tabular(plans)
    assert len(gt.fk_refs) == 1
    assert gt.fk_refs[0].parent_dataset == "x_bm_layout_model"
    assert gt.fk_refs[0].resolvable_child_ids == {"R1"}


def test_empty_ground_truth_aborts_not_passes() -> None:
    """Zero expectations must abort as ground_truth_empty, never vacuous PASS."""
    from aryx.pipeline.ingest_validation import validate_workspace
    report = validate_workspace(1, GroundTruth(), dsn="postgresql://unused")
    assert not report.passed
    assert report.checks[0].actual == "ground_truth_empty"


def test_report_passed_semantics() -> None:
    r = ValidationReport(workspace_id=1)
    r.checks.append(CheckResult("a", "PASS", 1, 1))
    r.checks.append(CheckResult("b", "WARN", 2, 3))
    r.checks.append(CheckResult("c", "SKIP", "-", "-"))
    assert r.passed  # WARN/SKIP don't fail
    r.checks.append(CheckResult("d", "FAIL", 5, 0))
    assert not r.passed
    assert "expected=5" in r.failures()[0]


def test_raw_xml_counts() -> None:
    xml = (b"<shop>"
           b"<product id='P1'><category id='C1' name='x'/></product>"
           b"<product id='P2'><category id='C1' name='x'/></product>"
           b"</shop>")
    counts = _raw_xml_counts(xml, {"product", "category"})
    assert counts == {"product": 2, "category": 2}
