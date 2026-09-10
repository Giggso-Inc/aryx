"""``next_question_prompt`` -- build the hybrid question shown to the
sales rep for one pending attr (Phase 4 step 2 extraction from
``cpq/engine.py``, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Needs the live ``CpqEngine`` instance (``engine`` param): checks whether
an attr is a real grid selector via ``engine.resolve_array_grid_links``.
"""

from __future__ import annotations

from aryx.cpq.engine import _MAX_ENUMERATED_OPTIONS, _presentable
from aryx.cpq.state import ConfigAttr, ValidationRule
from aryx.cpq.turn_intent.free_text import describe_free_text_constraint
from aryx.cpq.turn_intent.labels import disambiguated_label
from aryx.cpq.turn_intent.next_question_helpers import (
    narrow_constrained_item_values, oversized_options_prompt,
)


# ── Next question ─────────────────────────────────────────────────────────

def next_question_prompt(
    engine,
    attr: ConfigAttr,
    context_sentence: str = "",
    constrained_item_values: list[str] | None = None,
    validation_rules: list["ValidationRule"] | None = None,
    attrs: list[ConfigAttr] | None = None,
    already_selected: "list[str] | set[str] | None" = None,
) -> str:
    """Build the hybrid question shown to the sales rep for one pending attr.

    already_selected — optional (default `None`, no-op for every
    existing caller). item_values the customer already picked for a
    select_type=="multi" grid-selector attr being asked AGAIN for
    more rows (docs/CPQ_SVX_MOUNTING_TYPE_ARRAY_GRID_MULTI_SELECT_
    PLAN_2026_08_25.md) — excluded from the numbered list so a re-ask
    only ever offers options genuinely still open, never re-lists one
    already answered. Generic: applies to any select_type=="multi"
    attr, no attribute or catalog name involved.

    context_sentence — explains WHY this attr is being asked based on rules
      (e.g. "Since 5G was selected, we now need a compatible antenna.").
    constrained_item_values — when active constraint rules apply, only these
      item_values are presented in the numbered list.
    validation_rules — when given, a free-text attr (no options) proactively
      shows its format constraint up front (e.g. "must only contain letters,
      digits, and the characters - . _") instead of a bare "Please provide a
      value." — confirmed live a rep has no way to know the expected format
      otherwise, since BigMachines' own source data has no help-text field
      for these attrs at all (docs/CPQ_UNIFIED_INTENT_CLASSIFIER_PLAN.md
      Amendment 21's describe_free_text_constraint, previously only reachable
      reactively via a Q&A question — now shown proactively too). None when
      not supplied (default), same opt-out convention as bml_eval=None
      elsewhere — never guesses a constraint that can't be described.

    attrs — optional (default `None`, preserving the bare `attr.display_
      label` every existing caller already showed). When given, the
      question header uses `disambiguated_label(attr, attrs)` instead —
      live-confirmed gap (2026-08-21): `mountType_viSoln` and
      `mountingTypeArray_viSoln` both carry the literal label "Mounting
      Type"; `_label_collision_for` (ask_api.py) deliberately excludes
      an already-ANSWERED sibling from its "which one did you mean"
      re-ask (correct — nothing left to disambiguate BETWEEN), but that
      left the remaining single pending attr's raw, still-colliding
      label on screen with zero indication it's a DIFFERENT attribute
      from the one just answered under the identical text. Catalog-
      agnostic — no attribute name hardcoded, same generic mechanism
      `disambiguated_label` already uses for cascade-announcement text.
    """
    # See next_question_helpers.py for the two split-out helpers below --
    # split purely to keep this file under the file-size cap.
    constrained_item_values = narrow_constrained_item_values(attr, constrained_item_values)

    # Use _presentable (not _valid) so codes like "NA" (North America) appear
    # in the numbered list even though _valid("NA")=False prevents auto-fill.
    _already_selected = set(already_selected) if already_selected else None
    effective_opts = [
        o for o in attr.options
        if _presentable(o.item_value)
        and (constrained_item_values is None or o.item_value in constrained_item_values)
        and (_already_selected is None or o.item_value not in _already_selected)
    ]
    ctx_prefix = f"{context_sentence}\n\n" if context_sentence else ""
    _label = disambiguated_label(attr, attrs) if attrs else attr.display_label
    if effective_opts:
        if len(effective_opts) > _MAX_ENUMERATED_OPTIONS:
            return oversized_options_prompt(ctx_prefix, _label, effective_opts)
        numbered = "\n".join(
            f"{i + 1}. {opt.display_name}"
            for i, opt in enumerate(effective_opts)
        )
        # An optional multi-select reaching this prompt at all is, by
        # construction, a grid selector (resolve_array_grid_links) —
        # every OTHER optional multi-select is auto-filled empty
        # without ever being asked (auto_fill's own optional-tier
        # branch). ask_api.py already recognizes "skip"/"none"/"no...
        # needed" as a valid decline for exactly this case (confirmed
        # live: mountingTypeArray_viSoln correctly resolves to an
        # empty selection), but the prompt never told the user that —
        # confirmed live: nobody would think to type "skip" without
        # being told it's an option.
        skip_hint = (
            "\n\n*(Optional — say \"skip\" or \"none needed\" if you "
            "don't need any.)*"
            if attr.select_type == "multi" and not attr.required else ""
        )
        # Raven review, PR #277 (medium): the comment above ("the only
        # multi-selects that reach this far") is true for the common
        # optional-and-auto-filled-empty case, but isn't a structural
        # guarantee — a REQUIRED multi-select with no picks yet, or any
        # future caller shape, could reach here without being a real
        # grid selector. Check the actual structural signal
        # (resolve_array_grid_links, the same one auto_fill/
        # grid_selector_vns already key off) instead of inferring it
        # from select_type alone, so an ordinary multi-select always
        # keeps the plain "choose one:" text. `attrs` is None for a
        # handful of older callers that never passed the full catalog —
        # those fall back to the plain text too, never guessing.
        _is_grid_selector = (
            attr.select_type == "multi" and attrs is not None
            and attr.variable_name in engine.resolve_array_grid_links(attrs)
        )
        if _is_grid_selector:
            # Grid selectors let the customer fill several rows: one at
            # a time across turns (apply_answer), or several at once in
            # one reply (apply_multi_answer already scans a reply for
            # every option named). "choose one" undersold that —
            # confirmed live: a customer picking exactly one narrowed
            # option (of 5-6 legal ones) was never invited to add more,
            # even though every other still-valid option remained
            # perfectly legal.
            already_note = (
                f" You've already added {len(_already_selected)} — "
                if _already_selected else " "
            )
            return (
                f"{ctx_prefix}**{_label}** —{already_note}choose one or "
                f"more of what's left "
                f"(you can name several at once):\n\n{numbered}{skip_hint}"
            )
        return f"{ctx_prefix}**{_label}** — choose one:\n\n{numbered}{skip_hint}"
    constraint_desc = describe_free_text_constraint(attr, validation_rules)
    constraint_hint = (
        f"\n\n*Must only contain {constraint_desc}.*" if constraint_desc else ""
    )
    return f"{ctx_prefix}**{_label}**\n\nPlease provide a value.{constraint_hint}"
