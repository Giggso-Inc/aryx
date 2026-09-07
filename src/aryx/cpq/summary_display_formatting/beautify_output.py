"""The two Beautify renderers -- aligned plain text and structured rows
(Phase 4 step 10 extraction from ``cpq/engine.py`` -- see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Both are thin presentation layers over the single row set
`_beautify_sectioned_rows` builds; neither does any filtering of its
own. No LLM call in either path.

`_beautify_sectioned_rows` and the `_BEAUTIFY_*_SECTION` constants are
reached through the passed-in `engine` instance rather than imported,
so the original ``self.<name>`` lookups (and any patch of them) behave
exactly as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from aryx.cpq.state import ConfigAttr


def beautify_text(
    engine: Any,
    product_name: str,
    display_filled: dict[str, str],
    attrs: list["ConfigAttr"] | None = None,
    filled_source: dict[str, str] | None = None,
    required_vns: frozenset[str] | None = None,
) -> str:
    """Human-readable ``Label : Value`` block for the Beautify button.

    Reuses filled_summary_pairs' noise/low-signal filtering (§ above) so
    Beautify shows the same substantive fields as the conversational
    summary — as aligned key:value lines instead of prose, no LLM call.
    Used as-is by clients that display plain text (e.g. Streamlit's
    st.code). Clients that render a real table use
    beautify_rows()'s structured pairs instead of parsing this string.

    filled_source — optional (default None, preserving the original
    flat single-list output exactly). When supplied, renders TWO
    headed sections — "Mandatory User Input" then "System-Configured
    / Recommended" — using `_is_mandatory_input_attr`'s Tier A/B/C
    signal, matching native Oracle CPQ's own visual grouping instead
    of one undifferentiated list.

    required_vns — optional (default `None`); forwarded to
    `_beautify_sectioned_rows` for Tier C (see its own docstring and
    `mandatory_tier_c_vns`).
    """
    rows = engine._beautify_sectioned_rows(
        product_name, display_filled, attrs, filled_source, required_vns=required_vns,
    )
    if filled_source is None:
        pairs = [(label, value) for _section, label, value in rows]
        width = max(len(label) for label, _ in pairs)
        return "\n".join(f"{label.ljust(width)} : {value}" for label, value in pairs)
    width = max(len(label) for _section, label, _value in rows)
    lines: list[str] = []
    for section in (engine._BEAUTIFY_MANDATORY_SECTION, engine._BEAUTIFY_SYSTEM_SECTION):
        section_rows = [(label, value) for sec, label, value in rows if sec == section]
        if not section_rows:
            continue
        lines.append(f"**{section}:**")
        lines.extend(f"{label.ljust(width)} : {value}" for label, value in section_rows)
        lines.append("")
    return "\n".join(lines).rstrip("\n")


def beautify_rows(
    engine: Any,
    product_name: str,
    display_filled: dict[str, str],
    attrs: list["ConfigAttr"] | None = None,
    filled_source: dict[str, str] | None = None,
    required_vns: frozenset[str] | None = None,
) -> list[dict[str, str]]:
    """Structured [{label, value, section}, ...] pairs for clients that
    render a real tabular UI (e.g. the Next.js Beautify panel) instead
    of plain text — same data and filtering as beautify_text(), just
    not flattened into a display string. No LLM call.

    filled_source — optional (default None). When supplied, each row
    carries a `"section"` key — "Mandatory User Input" or "System-
    Configured / Recommended" — via `_is_mandatory_input_attr`'s Tier
    A/B/C signal, the SAME one `build_payload`'s `scope_required_and_
    edited` uses to scope `config_data` (Tier C excepted there — see
    docs/CPQ_ConfigData_Payload_Mandatory_Fix_Scope_2026_08_19.md), so
    the views can never silently drift apart on what counts as
    "genuinely required" within their own intended scope.
    When `filled_source` is omitted, rows carry no `"section"` key at
    all — output shape and row set are byte-for-byte identical to
    before this parameter existed (same convention `beautify_text`
    already uses for its own `filled_source is None` case).

    required_vns — optional (default `None`); forwarded to
    `_beautify_sectioned_rows` for Tier C (see its own docstring and
    `mandatory_tier_c_vns`).
    """
    rows = engine._beautify_sectioned_rows(
        product_name, display_filled, attrs, filled_source, required_vns=required_vns,
    )
    if filled_source is None:
        return [{"label": label, "value": value} for _section, label, value in rows]
    return [
        {"section": section, "label": label, "value": value}
        for section, label, value in rows
    ]
