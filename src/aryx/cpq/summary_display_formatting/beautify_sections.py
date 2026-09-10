"""The shared (section, label, value) row set behind both Beautify
outputs (Phase 4 step 10 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

One row builder, two renderers (`beautify_text` / `beautify_rows`), so
the plain-text and tabular views can never drift apart on either the
row set or the Mandatory/System section split.

`_filled_summary_triples`, `_is_mandatory_input_attr` and the
`_BEAUTIFY_*_SECTION` constants are all reached through the passed-in
`engine` instance rather than imported, so the original ``self.<name>``
lookups (and any patch of them) behave exactly as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.state import ConfigAttr


def _beautify_sectioned_rows(
    engine: Any,
    product_name: str,
    display_filled: dict[str, str],
    attrs: list["ConfigAttr"] | None,
    filled_source: dict[str, str] | None,
    required_vns: frozenset[str] | None = None,
) -> list[tuple[str, str, str]]:
    """Shared (section, label, value) rows for beautify_text/beautify_rows.

    When `filled_source` is supplied, splits the output into two
    sections using the SAME `_is_mandatory_input_attr` signal
    `build_payload`'s `scope_required_and_edited` uses to scope
    `config_data` — one scoping key, three consumers (docs/CPQ_
    GOVERNED_BLINDPICK_AND_CONFIGDATA_BEAUTIFY_FIX_PLAN_2026_08_14.md,
    extended 2026-08-19 with Tier C — docs/CPQ_Beautify_Mandatory_
    Section_Miscategorization_2026_08_19.md). This matches native
    Oracle CPQ's own "Mandatory User Input" box vs. everything else,
    instead of one flat, undifferentiated list.

    `filled_source=None` (the default, for existing callers that don't
    pass it) preserves the original single-section behavior exactly —
    every row lands in the Mandatory section so the flat "Product +
    every substantive field" list callers already depend on is
    byte-for-byte unchanged; only callers that opt in by passing
    `filled_source` get the two-section split.

    `required_vns` — optional (default `None`); `mandatory_tier_c_vns`'s
    result, forwarded into `_is_mandatory_input_attr` (Tier C) for the
    split above. Also passed to `_filled_summary_triples` so the
    underlying row set's `_is_summary_excluded` boolean-value gate
    (via `is_mandatory`) sees the same Mandatory classification.
    """
    triples = engine._filled_summary_triples(
        display_filled, attrs, sources=filled_source, required_vns=required_vns,
    )
    attr_by_vn = {a.variable_name: a for a in attrs} if attrs else {}
    rows: list[tuple[str, str, str]] = [
        (engine._BEAUTIFY_MANDATORY_SECTION, "Product", product_name),
    ]
    for var, label, value in triples:
        if filled_source is None:
            section = engine._BEAUTIFY_MANDATORY_SECTION
        else:
            attr = attr_by_vn.get(var)
            section = (
                engine._BEAUTIFY_MANDATORY_SECTION
                if engine._is_mandatory_input_attr(
                    var, attr, filled_source.get(var), required_vns=required_vns,
                )
                else engine._BEAUTIFY_SYSTEM_SECTION
            )
        rows.append((section, label, value))
    return rows
