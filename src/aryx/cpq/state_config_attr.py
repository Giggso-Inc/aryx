"""CPQ configuration-attribute dataclasses — MenuOption and ConfigAttr,
extracted from the knowledge graph's BigMachines-derived attribute
metadata.

Split out of `cpq/state.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MenuOption:
    """One selectable value for a configuration attribute."""

    item_value: str    # API backend code sent to CPQ BOM API (e.g. "US")
    display_name: str  # Friendly label shown to the sales rep (e.g. "United States")
    order: int = 999


@dataclass
class ConfigAttr:
    """One configuration attribute extracted from the knowledge graph."""

    entity_id: int
    variable_name: str   # CPQ backend key (e.g. "hWVersion_astro")
    display_label: str   # Human label shown in conversation
    required: bool
    default_value: str
    options: list[MenuOption]  # empty → free-text input
    order: int = 999
    tier: str = "independent"  # "independent" | "dependent"
    # Source-native id (e.g. BigMachines attribute id from the ingested XML).
    # Rule inputs/actions reference attributes by THIS id, not by the aryx
    # entity_id — rule joins must resolve through both.
    source_id: int | None = None
    # "single" (dropdown/radio, one value) | "multi" (checkbox, allowed set
    # from rules) | "boolean" (fixed Yes/No, no menu options at all).
    # Derived from BM attribute metadata — see classify_select_type() in
    # engine.py (CPQ_CASCADE_CONVERSATION_PLAN.md §4).
    select_type: str = "single"
    # Source-derived catalog prefix (see engine._catalog_prefix), e.g.
    # "ApxNextConfig" or "Sl3500EConfig" — "" when unresolved. Lets rule
    # loaders scope to the same ingested catalog this attr came from, so a
    # workspace holding more than one product's XML export never lets one
    # catalog's rules act on another's attributes.
    catalog_prefix: str = ""
    # Raw BM set_type code from the source XML ("1" transaction-line,
    # "2" transient UI/action-layer, "3" other). set_type=2 attrs must be
    # EXCLUDED from the BOM API payload — confirmed live: the real CPQ API
    # rejected every set_type=2 attr sent ("has an invalid payload") while
    # accepting identically-shaped set_type=1 menus, and the APX catalog's
    # own set_type=2 population (_price_book_var_name, mergePackage,
    # update, clearPackageJson, ...) shows the layer is transient fields,
    # not transaction attributes. Distinct from select_type (UI shape).
    set_type: str = ""
    # True for BM attrs flagged hidden=1 in the source XML — never shown to
    # the customer or added to `pending`, but still eligible for its own
    # default_value (BML scripts elsewhere may reference it) instead of
    # being dropped from the graph entirely.
    hidden: bool = False
    # True for BM attrs flagged hide_in_trans=1 — the source system's own
    # "don't submit this at transaction/order time" marker (confirmed live
    # against the real CPQ API: productInformationText_astro and
    # productSelectionHelptext_astro both carry this flag and both got
    # "cannot be modified" from the real API when included in a submission
    # payload). Distinct from `hidden` (never shown in the UI) — a field can
    # be visible/computed for display but still excluded from the BOM
    # submission itself; see CpqEngine.build_payload.
    hide_in_trans: bool = False
    # True for BM attrs flagged is_array_control_attr=1 — the source
    # system's own marker that this attr drives a native-UI grid editor
    # (e.g. a mounting-type quantity table), not a plain scalar/menu
    # question. Its real target quantity attrs are typically hidden=1 and
    # sized/populated by a rec/constraint rule conditioned on this control
    # (see docs/CPQ_SVX_LAYOUT_FLOW_AND_QUANTITY_GRID_PLAN.md §5 Change B).
    is_array_control: bool = False
    # True for BM attrs flagged auto_lock=1 — confirmed live (docs/
    # CPQ_SESSION_2_OPEN_ISSUES.md, auto_lock double-wrap finding) this
    # overrides the set_type=="2" exclusion in build_payload: a set_type=="2"
    # attr with auto_lock=1 (e.g. archeType_viSoln, modelSelectionSelectModel_
    # viSoln) is a real, includable value that ships double-wrapped
    # ({"value": {"value":..,"displayValue":..}}), not dropped like the
    # genuinely transient set_type=="2"/auto_lock=0 attrs.
    auto_lock: bool = False
    # BigMachines composite "array set" membership (docs/
    # CPQ_ARRAY_SET_PAYLOAD_PLAN.md) — a driver/control attr (already
    # flagged is_array_control above) plus ordered member columns (e.g.
    # Mounting Type's selector + its own per-row quantity), grouped by a
    # shared bm_config_attr_set id and serialized as one _index-keyed row
    # per selection rather than flat per-column lists. None/"" = not part
    # of any array-set.
    array_set_id: int | None = None
    array_set_role: str = ""              # "driver" | "member" | ""
    array_col_order: int = 999            # member ordinal within the set's row
    # DRIVER attrs only — the set's own variable_name (from the
    # bm_config_attr_set driver row, a distinct, never-ConfigAttr-ingested
    # entity) precomputed into the real wire-format top-level key, e.g.
    # "_setmountingTypeArrayset_viSoln". Members leave this "" — the
    # wrapper key is looked up via the driver, never reconstructed by
    # build_payload from a template.
    array_set_wrapper_key: str = ""
