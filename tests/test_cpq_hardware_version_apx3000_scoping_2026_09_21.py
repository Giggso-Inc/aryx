"""docs/Hardware_Version_APX3000_Product_Anchoring_Issue.md v2.2's merged
recommendation: resolve the specific device from the customer's own
original wording, then confirm via real attrSequence data whether Hardware
Version is ever governed for that device's CPQModel(s) -- confirmed real
finding: `hWVersion_astro` has exactly two menu options, both APX-NEXT-
specific, and its own gating rule lives under `bm_catalog_aPXNext_BOM`,
not the shared `aSTRO25` family root every device (APX 3000, APX 900,
etc.) is pooled under.

This test suite covers the new, deliberately one-sided override:
`CpqEngine._hardware_version_confirmed_not_applicable` can only ever make
Hardware Version LESS forced than today, never more, and only when the
device is confidently resolved AND real data confirms it. Every ambiguous/
unresolved case must fall through to today's unchanged "still mandatory"
behavior -- confirmed per the "fall through, never guess" choice made for
this fix.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine


def test_returns_false_with_no_hint_text():
    assert CpqEngine._hardware_version_confirmed_not_applicable(
        None, workspace_id=97, catalog_prefix="Astro25Configdata",
    ) is False
    assert CpqEngine._hardware_version_confirmed_not_applicable(
        "", workspace_id=97, catalog_prefix="Astro25Configdata",
    ) is False


def test_returns_false_with_no_workspace_id():
    assert CpqEngine._hardware_version_confirmed_not_applicable(
        "I want APX 3000 for United States", workspace_id=None,
    ) is False


def test_returns_false_when_hint_resolves_to_no_candidates(monkeypatch):
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: (),  # unresolved / ambiguous -- never guess
    )
    assert CpqEngine._hardware_version_confirmed_not_applicable(
        "some ambiguous or unrecognized phrase", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    ) is False


def test_returns_false_when_hardware_version_is_governed_for_a_candidate(monkeypatch):
    """APX NEXT case: resolved candidate genuinely IS governed for Hardware
    Version -- must stay mandatory, exactly like today."""
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: ("APXNEXTENHANCED",),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: True,
    )
    assert CpqEngine._hardware_version_confirmed_not_applicable(
        "I want to configure APX NEXT for USA", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    ) is False


def test_returns_true_when_confidently_resolved_and_never_governed(monkeypatch):
    """APX 3000 case: a real, resolvable CPQModel candidate exists, and
    real attrSequence data confirms Hardware Version is never governed for
    it -- this is the one case that should now suppress the question."""
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: ("APX3000",),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: False,
    )
    assert CpqEngine._hardware_version_confirmed_not_applicable(
        "I want APX 3000 for United States", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    ) is True


def test_returns_false_when_any_of_multiple_candidates_is_governed(monkeypatch):
    """Multiple real CPQModel candidates resolved -- if EVEN ONE is
    governed for Hardware Version, never suppress (mirrors the existing
    'any' convention _dt_never_governed_anywhere already uses elsewhere in
    this file for the same kind of question)."""
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: ("APX3000", "APXNEXTENHANCED"),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: cm == "APXNEXTENHANCED",
    )
    assert CpqEngine._hardware_version_confirmed_not_applicable(
        "some text matching two real products", workspace_id=97,
        catalog_prefix="Astro25Configdata",
    ) is False
