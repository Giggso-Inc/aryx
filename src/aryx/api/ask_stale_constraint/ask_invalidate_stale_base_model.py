"""Clearing the Data-Table-governed Base Model attribute when one of its
real derivation inputs changes, split out of `api/ask_api.py` (Phase 4/
11-phase ask_api decomposition, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-
03.md). Pop logic unchanged from the original inline definition; the
`workspace_id`/`catalog_prefix` params were added by CPQ_Hardcode_Audit_
dev_oci_2026-09-25.md's T1 Phase 3 pilot slice (shadow-only at first,
now real -- see `_invalidate_stale_base_model`'s own docstring).
"""

from __future__ import annotations

from typing import Any

from aryx.cpq.catalog_profile import BASE_MODEL_LITERAL, resolve_base_model_vn, resolve_region_vn

# docs/CPQ_STALE_BASE_MODEL_CASCADE_CONFLICT_PLAN_2026_08_20.md
# Re-exported from catalog_profile.py (the single source of truth for
# this literal, CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T1 Phase 3
# "scoped" rollout) rather than re-declared here -- keeps every one of
# this literal's ~16 call sites across the codebase agreeing on the same
# string, instead of risking the exact T10-style drift this audit is
# named for.
_BASE_MODEL_VN = BASE_MODEL_LITERAL
# Every input Base Model's own re-derivation reads (engine.py:7958-7975):
# Product (via _cpq_model_candidates), and Country/Region (via
# resolve_region_allow_value) when Product alone doesn't already resolve
# it. Hardware Version is included because it's the real, live-reproduced
# trigger (Hardware Version change -> Product invalidated -> re-answered)
# even though Base Model's own derivation code never reads it directly --
# changing it is what makes Product (a real derivation input) go stale in
# the first place. Widened 2026-08-20 after auditing every Data-Table
# resolver function in data_table_resolver.py and confirming Base Model is
# the ONLY scoping-key attribute of its kind in this catalog -- but its
# OWN derivation has two triggers (Product, Country/Region), and the
# original fix only covered one of them.
#
# Region's member is NOT included in this static set (unlike the other
# three) -- CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T1 Phase 3: this is a
# membership check against `changed_attr.variable_name`, the REAL name the
# catalog ingested for whatever attribute just changed. A catalog whose
# real Region variable name differs from the literal would silently never
# trigger this invalidation on a real Region change -- unlike Product
# (`_DECISION_ANCHOR_VNS`'s circularity problem, ruled structurally out of
# scope), Region's real name IS resolvable here (workspace_id/`session.
# filled` are both already in scope), so it's computed per-call via
# `resolve_region_vn` and unioned in below instead of hardcoded.
_BASE_MODEL_STATIC_TRIGGER_VNS = frozenset({
    "hWVersion_astro", "productSelectionProduct_all",
    "ultimateDestinationCountry",
})


def _invalidate_stale_base_model(
    session: Any, changed_attr: Any, dependent_eids: "set[int]",
    by_eid: dict[int, Any], workspace_id: int, catalog_prefix: str = "",
) -> None:
    """Base Model (modelSelectionbaseModel_astro) is Data-Table-governed, not
    rule-graph-governed -- find_cascade_dependents can never see it as a
    dependent of Hardware Version, Product, or Country/Region, so it goes
    stale and later trips a false 'confirmed conflict' in find_confirmed_
    data_table_conflicts, which uses it purely as a scoping key (not
    necessarily one of the two attrs it names) to select which real Data
    Table rows to check the CURRENT Hardware Version/Product pair against
    -- a stale key means checking against the wrong hardware generation's
    rows entirely.
    docs/CPQ_STALE_BASE_MODEL_CASCADE_CONFLICT_PLAN_2026_08_20.md.

    Safe to always clear when triggered: modelSelectionbaseModel_astro
    already has its own from-scratch re-derivation path (engine.py:7957,
    `if not filled.get(_BASE_MODEL_VN)`) that every subsequent rule pass
    attempts unconditionally. Confirmed via an end-to-end pipeline test
    (test_cpq_stale_base_model_cascade_2026_08_20.py) that this does NOT
    necessarily resolve within the SAME turn as the trigger -- Base
    Model's own derivation reads Product, so if Product itself was just
    invalidated by this same cascade (the common case), Base Model stays
    correctly unresolved until Product is answered, possibly a later
    turn. What's guaranteed either way: it never resolves to the stale
    pre-trigger value -- worst case it's absent (asked or silently
    skipped, per its own governance), never wrong.

    Triggers on attribute IDENTITY, not on whether its value actually
    changed -- a no-op "change" to an already-current value still forces
    a re-derivation. Deliberate: the caller (`_handle_cascade`) doesn't
    cheaply know the outcome of `apply_answer` yet at this point in the
    turn, and re-derivation itself is idempotent and cheap (a handful of
    Data Table row scans, no LLM call), so trading a rare redundant
    recompute for never missing a real one is the right side to err on.

    CPQ_Hardcode_Audit_dev_oci_2026-09-25.md T1 Phase 3: `workspace_id`/
    `catalog_prefix` feed `resolve_base_model_vn`, which resolves the
    REAL key Base Model's value is stored under for the session's
    actual CPQ model, falling back to the `modelSelectionbaseModel_
    astro` literal (unchanged today, per live-confirmed testing: no
    real workspace in this environment currently has attrToVarMapping
    coverage for this role) whenever resolution is unavailable. This
    started as a shadow-only, log-only comparison (pilot slice,
    2c3c842a) and became real once every OTHER call site for this same
    literal was switched over together (2026-09-25) -- clearing under a
    different key than every read site still hardcoding the literal
    would be a worse bug than not clearing at all. The Region member of
    the trigger set is resolved the same way, per-call, for the same
    reason -- see `_BASE_MODEL_STATIC_TRIGGER_VNS`'s own comment.
    """
    changed_names = {changed_attr.variable_name} | {
        by_eid[eid].variable_name for eid in dependent_eids if eid in by_eid
    }
    region_vn = resolve_region_vn(session.filled, workspace_id, catalog_prefix)
    trigger_vns = _BASE_MODEL_STATIC_TRIGGER_VNS | {region_vn}
    if changed_names & trigger_vns:
        base_model_vn = resolve_base_model_vn(session.filled, workspace_id, catalog_prefix)
        session.filled.pop(base_model_vn, None)
        session.display_filled.pop(base_model_vn, None)
        session.filled_source.pop(base_model_vn, None)
