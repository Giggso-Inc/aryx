"""display_backfill.plan_display_backfill -- the pure planning half of
scripts/backfill_cpq_display_names.py (docs/ingestion/
CPQ_XML_DISPLAY_NAMES_PLAN_2026-10-05.md §4).

Shapes mirror what the pre-fix raw-graph path left in aryx_entity for
workspace 1126: wrapper entities (``label``/``bm_name``/``name``) are
RESOLVED, so identical wrapper text is merged into one entity shared by
many parents via CONTAINS.
"""
from __future__ import annotations

from aryx.cpq_ingestion.raw_graph.display_backfill import plan_display_backfill, types_fully_removed

FAMILY, CATALOG, ATTR_A, ATTR_B = 1, 2, 3, 4
LABEL, BM_NAME, NAME_SHARED, DESC_TEXT = 10, 11, 12, 13


def _workspace():
    entities = {
        FAMILY: {"id": "17691416877", "variable_name": "aSTRO25_bom"},
        CATALOG: {"id": "17691417058", "bm_variable_name": "aPXNext_BOM"},
        ATTR_A: {"id": "a", "qty_attr_id": "0", "variable_name": "boolContinue1"},
        ATTR_B: {"id": "b", "qty_attr_id": "0", "variable_name": "boolContinue2"},
        LABEL: {"en": "ASTRO®25_BOM"},
        BM_NAME: {"en": "APX™ NEXT"},
        NAME_SHARED: {"en": "Shared Name"},
        DESC_TEXT: {"text": "plain"},
    }
    tag_of = {FAMILY: "bm_prd_family", CATALOG: "bm_catalog", ATTR_A: "bm_config_attr",
              ATTR_B: "bm_config_attr", LABEL: "label", BM_NAME: "bm_name",
              NAME_SHARED: "name", DESC_TEXT: "description"}
    contains = [(FAMILY, LABEL), (CATALOG, BM_NAME), (ATTR_A, NAME_SHARED),
                (ATTR_B, NAME_SHARED), (ATTR_A, DESC_TEXT)]
    return entities, tag_of, contains


def test_plan_family_gets_label_name_and_display_label():
    plan = plan_display_backfill(*_workspace())
    fam = plan.updates[FAMILY]
    assert (fam["label"], fam["name"], fam["display_label"]) == ("ASTRO®25_BOM", "aSTRO25_bom", "ASTRO®25_BOM")


def test_plan_catalog_name_from_bm_variable_name_display_from_bm_name():
    cat = plan_display_backfill(*_workspace()).updates[CATALOG]
    assert (cat["name"], cat["display_label"]) == ("aPXNext_BOM", "APX™ NEXT")


def test_plan_merged_wrapper_entity_folds_onto_every_parent():
    plan = plan_display_backfill(*_workspace())
    assert (plan.updates[ATTR_A]["name"], plan.updates[ATTR_B]["name"]) == ("Shared Name", "Shared Name")


def test_plan_wrapper_entities_listed_for_removal():
    plan = plan_display_backfill(*_workspace())
    assert sorted(plan.wrapper_entity_ids) == [LABEL, BM_NAME, NAME_SHARED]


def test_plan_text_only_tag_is_not_a_wrapper():
    """description here is text-only -- a structural leaf the pre-fix run
    simply didn't fold; same rule as the ingestion pass: not this fix's call."""
    plan = plan_display_backfill(*_workspace())
    assert DESC_TEXT not in plan.wrapper_entity_ids and "description" not in plan.updates[ATTR_A]


def test_plan_does_not_mutate_input_entities():
    entities, tag_of, contains = _workspace()
    plan_display_backfill(entities, tag_of, contains)
    assert "name" not in entities[FAMILY]


def test_plan_unchanged_entity_not_in_updates():
    entities, tag_of, contains = _workspace()
    entities[5] = {"name": "already", "other": "x"}
    tag_of[5] = "thing"
    assert 5 not in plan_display_backfill(entities, tag_of, contains).updates


def test_plan_replanning_after_keep_wrappers_does_not_duplicate_label():
    """Review finding M1 (PR #437): --keep-wrappers (or a wrapper-delete
    chunk failing after attribute updates already committed) leaves the
    wrapper entity in place while the parent already carries the folded
    value. Replanning from that state must not turn ``label`` into
    ``["ASTRO®25_BOM", "ASTRO®25_BOM"]`` on a second --apply."""
    entities, tag_of, contains = _workspace()
    first = plan_display_backfill(entities, tag_of, contains)
    entities[FAMILY] = dict(entities[FAMILY], **first.updates[FAMILY])  # simulate --apply
    second = plan_display_backfill(entities, tag_of, contains)
    assert FAMILY not in second.updates or second.updates[FAMILY]["label"] == "ASTRO®25_BOM"
    # Review finding N8 (PR #437): the wrapper must still be listed for
    # deletion on the retry -- the planner skipping the already-folded
    # VALUE must not also skip marking the wrapper entity itself redundant.
    assert second.wrapper_entity_ids == first.wrapper_entity_ids


def test_plan_wrapper_with_a_child_of_its_own_is_kept():
    entities, tag_of, contains = _workspace()
    entities[20] = {"id": "z"}
    tag_of[20] = "item"
    contains.append((LABEL, 20))
    plan = plan_display_backfill(entities, tag_of, contains)
    assert LABEL not in plan.wrapper_entity_ids and "label" not in plan.updates[FAMILY]


def test_plan_parentless_wrapper_entity_is_kept():
    entities, tag_of, contains = _workspace()
    entities[21] = {"en": "orphan"}
    tag_of[21] = "label"
    assert 21 not in plan_display_backfill(entities, tag_of, contains).wrapper_entity_ids


def test_plan_entity_with_unknown_tag_is_never_a_wrapper():
    entities, tag_of, contains = _workspace()
    del tag_of[LABEL]
    plan = plan_display_backfill(entities, tag_of, contains)
    assert LABEL not in plan.wrapper_entity_ids


def test_plan_empty_workspace_is_empty_plan():
    plan = plan_display_backfill({}, {}, [])
    assert (plan.updates, plan.wrapper_entity_ids) == ({}, [])


def test_plan_empty_wrapper_entity_in_a_locale_tag_still_folds():
    """Live ws 1126: one of 47 label entities is {} (an empty <label/>);
    without this the whole label tag was skipped and the family kept no label."""
    entities, tag_of, contains = _workspace()
    entities[30] = {}
    tag_of[30] = "label"
    entities[6] = {"variable_name": "other_bom"}
    tag_of[6] = "bm_prd_family"
    contains.append((6, 30))
    plan = plan_display_backfill(entities, tag_of, contains)
    assert plan.updates[FAMILY]["label"] == "ASTRO®25_BOM" and 30 in plan.wrapper_entity_ids


# ── types_fully_removed (Raven review finding 2: no ghost ontology types) ──

def test_types_fully_removed_lists_type_whose_every_entity_is_deleted():
    assert types_fully_removed({10: "XLabel", 11: "XLabel", 1: "XFamily"}, [10, 11]) == ["XLabel"]


def test_types_fully_removed_skips_type_with_a_surviving_entity():
    assert types_fully_removed({10: "XLabel", 11: "XLabel"}, [10]) == []


def test_types_fully_removed_nothing_removed_is_empty():
    assert types_fully_removed({10: "XLabel"}, []) == []
