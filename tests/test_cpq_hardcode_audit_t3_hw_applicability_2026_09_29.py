"""docs/CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T3 -- Tier A used to mark
ANY Hardware Version attr structurally mandatory (`_is_hardware_version_
attr`) with no applicability check at all. `_is_mandatory_input_attr`'s
Tier A now ALSO consults the same, already-wired-in-two-other-places
applicability check (`CpqEngine._hardware_version_confirmed_not_
applicable`, see tests/test_cpq_hardware_version_apx3000_scoping_2026_09_21
.py for its own full contract) via 4 new optional params (`hint_text`/
`workspace_id`/`catalog_prefix`/`_dt_cache`), all defaulting to `None`/
``""`` so every existing caller that doesn't opt in keeps today's
behavior byte-for-byte -- `_hardware_version_confirmed_not_applicable`
itself returns `False` whenever `hint_text` is falsy or `workspace_id`
is `None` (its own early-return), so `not False == True` and the HW
branch is unchanged.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, MenuOption


def _menu(*values: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(values, start=1)]


def _hw_attr(entity_id: int = 1) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, variable_name="hWVersion_astro", display_label="Hardware Version",
        required=False, default_value="", select_type="single",
        options=_menu("APX NEXT ENHANCED", "APX NEXT STANDARD"),
    )


def test_hw_attr_stays_tier_a_with_no_hint_or_workspace_passed():
    """Backward compatibility: omitting the new params (every existing
    caller) keeps Hardware Version an unconditional Tier A anchor,
    exactly today's behavior -- `_hardware_version_confirmed_not_
    applicable` itself returns False with hint_text=None/workspace_id=
    None, so this needs no patching to prove."""
    engine = CpqEngine()
    attr = _hw_attr()
    assert engine._is_mandatory_input_attr("hWVersion_astro", attr, "rule") is True


def test_hw_attr_not_tier_a_when_confirmed_not_applicable():
    """A hint_text/workspace_id/cache combination that makes the
    applicability check return True (device confidently resolved, real
    attrSequence data confirms HW never governed for it -- the APX 3000
    case) must suppress Tier A for this attr, assuming no other Tier A
    condition applies (this vn matches none of the others)."""
    engine = CpqEngine()
    attr = _hw_attr()
    with patch.object(
        CpqEngine, "_hardware_version_confirmed_not_applicable",
        return_value=True,
    ) as mocked:
        assert engine._is_mandatory_input_attr(
            "hWVersion_astro", attr, "rule",
            hint_text="I want APX 3000 for United States",
            workspace_id=97, catalog_prefix="Astro25Configdata",
        ) is False
    mocked.assert_called_once_with(
        "I want APX 3000 for United States", 97, "Astro25Configdata", None,
    )


def test_hw_attr_stays_tier_a_when_confirmed_still_applicable():
    """The applicability check returning False (HW genuinely still
    applicable, e.g. APX NEXT) -- Tier A stays True, same as the
    no-params-passed case, even though hint_text/workspace_id WERE
    supplied this time."""
    engine = CpqEngine()
    attr = _hw_attr()
    with patch.object(
        CpqEngine, "_hardware_version_confirmed_not_applicable",
        return_value=False,
    ):
        assert engine._is_mandatory_input_attr(
            "hWVersion_astro", attr, "rule",
            hint_text="I want APX NEXT for United States",
            workspace_id=97, catalog_prefix="Astro25Configdata",
        ) is True


def test_hw_attr_real_applicability_check_apx3000_end_to_end(monkeypatch):
    """No mock of `_hardware_version_confirmed_not_applicable` itself --
    patches the two lower-level data hooks it calls (same convention
    tests/test_cpq_hardware_version_apx3000_scoping_2026_09_21.py uses)
    to prove the real method, reached through Tier A, suppresses HW for
    a confidently-resolved APX 3000 hint."""
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_resolve_product_cpq_models_from_hint",
        lambda *a, **k: ("APX3000",),
    )
    monkeypatch.setattr(
        "aryx.cpq.engine.dt_attr_ever_governed_for_cpq_model",
        lambda cm, vn, *a, **k: False,
    )
    engine = CpqEngine()
    attr = _hw_attr()
    assert engine._is_mandatory_input_attr(
        "hWVersion_astro", attr, "rule",
        hint_text="I want APX 3000 for United States",
        workspace_id=97, catalog_prefix="Astro25Configdata",
    ) is False


def test_real_session_product_anchor_question_reaches_beautify_text():
    """End-to-end proof for one real production call site
    (api/ask_attach_share_flags.py's `_attach_share_flags` passes
    `session.product_anchor_question` into `beautify_text`/
    `beautify_rows` as `product_anchor_hint`): the session's own hint
    text, threaded all the way through `beautify_text` ->
    `_beautify_sectioned_rows` -> `_filled_summary_triples` ->
    `_is_mandatory_input_attr`, suppresses Hardware Version's Mandatory
    section membership exactly like the direct unit test above, proving
    the plumbing -- not just the leaf function -- is wired."""
    engine = CpqEngine()
    attr = _hw_attr()
    display_filled = {"hWVersion_astro": "APX NEXT ENHANCED"}
    filled_source = {"hWVersion_astro": "rule"}
    with patch.object(
        CpqEngine, "_hardware_version_confirmed_not_applicable",
        return_value=True,
    ) as mocked:
        rows = engine.beautify_rows(
            "APX 3000", display_filled, [attr], filled_source,
            product_anchor_hint="I want APX 3000 for United States",
            workspace_id=97, catalog_prefix="Astro25Configdata",
        )
    # Called twice: once from `_filled_summary_triples`'s own is_mandatory
    # computation, once from `_beautify_sectioned_rows`'s section split --
    # both must see the same hint, proving the plumbing threads it through
    # every hop, not just one.
    assert mocked.call_count == 2
    for call in mocked.call_args_list:
        assert call.args == (
            "I want APX 3000 for United States", 97, "Astro25Configdata", None,
        )
    section_by_label = {row["label"]: row["section"] for row in rows}
    assert section_by_label.get("Hardware Version") == engine._BEAUTIFY_SYSTEM_SECTION
